import psycopg2
import logging
import sys
import clickhouse_connect


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


OLTP_CREDENTIALS = {
    "dbname": "marketplace_oltp",
    "user": "admin",
    "password": "admin",
    "port": 5432,
    "host": "localhost",
}
OLAP_CREDENTIALS = {
    "host": "localhost",
    "username": "analyst",
    "password": "analyst",
    "port": 8123,
    "database": "marketplace_olap",
}

init_queries_oltp = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(50) UNIQUE NOT NULL,
        email VARCHAR(100) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        phone VARCHAR(20),
        first_name VARCHAR(50),
        last_name VARCHAR(50),
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        category VARCHAR(100) NOT NULL,
        price DECIMAL(10, 2) NOT NULL,
        stock INTEGER NOT NULL DEFAULT 0,
        is_available BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS orders (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        total_amount DECIMAL(10, 2) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS order_items (
        id SERIAL PRIMARY KEY,
        order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
        product_id INTEGER NOT NULL REFERENCES products(id),
        quantity INTEGER NOT NULL CHECK (quantity > 0),
        price_at_purchase DECIMAL(10, 2) NOT NULL,
        UNIQUE(order_id, product_id)
    );
    """,
    # Индексы создаются в той же транзакции
    """
    CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);
    CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
    CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);
    CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
    """
]

olap_queries = [
    """
CREATE TABLE IF NOT EXISTS fact_sales
(
    -- 1. Ключи из OLTP-систем (для связности и точечных проверок при отладке)
    order_id        UInt64,
    order_item_id   UInt64,
    user_id         UInt32,
    product_id      UInt32,

    -- 2. Денормализованные данные из DB_Users (CRM)
    -- В OLAP мы не делаем JOIN с users, мы сразу храним нужные атрибуты здесь
    username        String,
    user_email      String,

    -- 3. Денормализованные данные из DB_Cart (Товары)
    product_name    String,
    product_category LowCardinality(String), -- ⚡ Критичная оптимизация ClickHouse для строк с низкой кардинальностью (например, "Электроника")

    -- 4. Данные из DB_Payments и order_items (Транзакции)
    order_status    LowCardinality(String), -- pending, paid, shipped, delivered, cancelled
    quantity        UInt16,
    price_at_purchase Decimal32(2),         -- Аналог DECIMAL(10, 2) в ClickHouse (экономит место и ускоряет расчеты)
    
    -- Вычисляемое поле: выручка по строке заказа (рассчитывается при вставке)
    line_total      Decimal32(2) MATERIALIZED quantity * price_at_purchase,

    -- 5. Временные метки (основа для аналитики за периоды)
    order_created_at DateTime,
    order_date       Date MATERIALIZED toDate(order_created_at) -- ⚡ Автоматически извлекает дату для партиционирования
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(order_date)              -- Разбиение на партиции по месяцам (ускоряет запросы с фильтром по дате)
ORDER BY (order_date, product_category, order_id) -- Первичный ключ сортировки (определяет физический порядок данных на диске)
SETTINGS index_granularity = 8192;
    """,
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS mv_daily_sales_by_category
ENGINE = SummingMergeTree()                    -- Специальный движок, который автоматически суммирует значения при слиянии частей
PARTITION BY toYYYYMM(day)
ORDER BY (day, product_category)
AS SELECT
    order_date AS day,
    product_category,
    countDistinct(order_id) AS unique_orders,  -- Количество уникальных заказов
    sum(quantity) AS total_items_sold,         -- Продано единиц товара
    sum(line_total) AS total_revenue           -- Общая выручка
FROM fact_sales
WHERE order_status IN ('paid', 'shipped', 'delivered') -- Фильтруем только успешные транзакции (защита от фрода/отмен)
GROUP BY day, product_category;
    """
]


def init_oltp(creds, queries):
    try:
        logger.info(f"Попытка подключения к БД '{creds['dbname']}' на {creds['host']}...")
        
        with psycopg2.connect(**creds) as conn:
            logger.info("Подключение успешно установлено.")
            
            # Курсор также является контекстным менеджером и закроется автоматически
            with conn.cursor() as cur:
                logger.info("Начало инициализации схемы БД...")

                for query in queries:
                    cur.execute(query)
                logger.info("Схема иниициализирована.")

    except psycopg2.OperationalError as conn_err:
        # Этот блок сработает, если вообще не удалось подключиться (неверный пароль, БД недоступна)
        logger.critical(f"Не удалось подключиться к базе данных: {conn_err}", exc_info=True)
        sys.exit(1)
    except Exception as e:
        # Ловушка для любых других непредвиденных ошибок
        logger.critical(f"Критическая непредвиденная ошибка: {e}", exc_info=True)
        sys.exit(1)


def init_olap(creds, queries):
    try:
        logger.info(f"Попытка подключения к БД '{creds['database']}' на {creds['host']}...")
        client = clickhouse_connect.get_client(**creds)
        print(client.command("SELECT VERSION()"))

        for query in queries:
            client.command(query)
        logger.info("Схема иниициализирована.")
    except Exception as e:
        logger.critical(f"Критическая непредвиденная ошибка: {e}", exc_info=True)
        sys.exit(1)


def main():
    init_oltp(OLTP_CREDENTIALS, init_queries_oltp)
    init_olap(OLAP_CREDENTIALS, olap_queries)


if __name__ == "__main__":
    main()