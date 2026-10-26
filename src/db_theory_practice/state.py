from dataclasses import dataclass
from datetime import datetime


@dataclass
class User:
    user_id: int  # primary key id пользователя
    created_at: datetime  # дата и время регистрации
    city: str  # город пользователя
    status: str  # статус пользователя
    updated_at: datetime  # дата и время обновления статуса


@dataclass
class Product:
    product_id: int  # id товара
    name: str   # название продукта
    price: float  # цена продукта
    cat_id: int  # foreign key для категории
    created_at: datetime  # дата и время создания товара
    updated_at: datetime  # дата и время обновления товара


@dataclass
class Category:
    cat_id: int  # primary key для категории
    category: str  # категория товара


@dataclass
class Order:
    order_id: int  # id заказа
    user_id: int  # foreign key id пользователя
    created_at: datetime  # дата и время создания
    updated_at: datetime  # дата и время обновления
    status: str  # статус заказа
    total: float  # общая сумма заказа


@dataclass
class OrderItem:
    order_item_id: int  # id позиции заказа (для товаров, которые повторяются)
    order_id: int  # foreign key id заказа
    product_id: int  # foreign key id товара
    price_at_order: float  # цена на момент покупки
    quantity: int  # кол-во товаров


@dataclass
class CartItem:
    cart_item_id: int # id позиции в корзине
    status: str  # статус товара в корзине
    user_id: int  # foreign key id пользователя
    product_id: int  # foreign key id товара
    quantity: int  # кол-во товаров
    created_at: datetime  # дата и время создания
    updated_at: datetime  # дата и время обновления
