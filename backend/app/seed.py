import random
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import Base, engine
from app.models import Order, Product, Stock


PRODUCTS = [
    ("无线鼠标", "数码配件", 59.9),
    ("机械键盘", "数码配件", 289.0),
    ("USB-C扩展坞", "数码配件", 169.0),
    ("蓝牙耳机", "数码配件", 199.0),
    ("移动硬盘", "数码配件", 399.0),
    ("保温杯", "生活用品", 49.0),
    ("折叠雨伞", "生活用品", 35.0),
    ("双肩背包", "生活用品", 159.0),
    ("桌面收纳盒", "办公用品", 29.9),
    ("笔记本套装", "办公用品", 24.9),
    ("无线充电器", "数码配件", 89.0),
    ("显示器支架", "办公用品", 129.0),
    ("护眼台灯", "办公用品", 119.0),
    ("手机支架", "数码配件", 19.9),
    ("便携咖啡杯", "生活用品", 45.0),
    ("旅行收纳袋", "生活用品", 39.9),
    ("降噪耳机", "数码配件", 599.0),
    ("人体工学椅垫", "办公用品", 99.0),
    ("智能插座", "数码配件", 69.0),
    ("便携水壶", "生活用品", 55.0),
]


def initialize_database(db: Session) -> None:
    Base.metadata.create_all(bind=db.get_bind())
    if db.scalar(select(func.count()).select_from(Product)):
        return

    rng = random.Random(20260930)
    products = [
        Product(name=name, category=category, price=price)
        for name, category, price in PRODUCTS
    ]
    db.add_all(products)
    db.flush()
    db.add_all(
        Stock(product_id=product.id, quantity=rng.randint(8, 350))
        for product in products
    )

    today = date.today()
    orders = []
    for _ in range(200):
        product = rng.choice(products)
        quantity = rng.randint(1, 8)
        order_date = today - timedelta(days=rng.randrange(90))
        orders.append(
            Order(
                product_id=product.id,
                quantity=quantity,
                amount=round(float(product.price) * quantity, 2),
                created_at=datetime.combine(order_date, time(hour=rng.randrange(24))),
            )
        )
    db.add_all(orders)
    db.commit()


def initialize() -> None:
    with Session(engine) as db:
        initialize_database(db)
