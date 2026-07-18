"""
Заполняет базу тестовыми данными.
Запуск: python seed.py
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.ext.asyncio import AsyncSession
from app.database import AsyncSessionLocal, engine
from app.models import Base, Category, Product


async def seed():
    # Создаём таблицы
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # Категории
        cats = [
            Category(name="Уход за лицом", slug="face"),
            Category(name="Уход за телом", slug="body"),
            Category(name="Декоративная косметика", slug="makeup"),
            Category(name="Ароматы", slug="perfume"),
        ]
        for c in cats:
            db.add(c)
        await db.flush()

        # Товары
        products = [
            Product(name="Крем для лица SPF50", description="Увлажняющий крем с защитой от солнца", price=1290, stock=50, category_id=cats[0].id, image_url="https://images.unsplash.com/photo-1556228578-8c89e6adf883?w=400"),
            Product(name="Сыворотка с витамином C", description="Антиоксидантная сыворотка для сияния кожи", price=2490, stock=30, category_id=cats[0].id, image_url="https://images.unsplash.com/photo-1620916566398-39f1143ab7be?w=400"),
            Product(name="Мицеллярная вода", description="Нежное очищение без смывания", price=590, stock=100, category_id=cats[0].id, image_url="https://images.unsplash.com/photo-1601049541271-7daf75a7c290?w=400"),
            Product(name="Скраб для тела", description="Кофейный скраб с маслом ши", price=890, stock=40, category_id=cats[1].id, image_url="https://images.unsplash.com/photo-1608248597279-f99d160bfcbc?w=400"),
            Product(name="Масло для тела", description="Питательное масло с витамином E", price=1190, stock=25, category_id=cats[1].id, image_url="https://images.unsplash.com/photo-1585652757141-4e462a1ef622?w=400"),
            Product(name="Помада матовая", description="Стойкая помада 24 часа", price=790, stock=60, category_id=cats[2].id, image_url="https://images.unsplash.com/photo-1586495777744-4e6232bf2f86?w=400"),
            Product(name="Тушь для ресниц", description="Объём и длина", price=690, stock=80, category_id=cats[2].id, image_url="https://images.unsplash.com/photo-1512207736890-6ffed8a84e8d?w=400"),
            Product(name="Тональный крем", description="Лёгкое покрытие, натуральный финиш", price=1490, stock=45, category_id=cats[2].id, image_url="https://images.unsplash.com/photo-1522338242992-e1a54906a8da?w=400"),
            Product(name="Парфюм Rose Garden", description="Цветочный аромат с нотками розы и жасмина", price=3990, stock=20, category_id=cats[3].id, image_url="https://images.unsplash.com/photo-1541643600914-78b084683702?w=400"),
            Product(name="Парфюм Ocean Blue", description="Свежий морской аромат", price=2990, stock=15, category_id=cats[3].id, image_url="https://images.unsplash.com/photo-1523293182086-7651a899d37f?w=400"),
        ]
        for p in products:
            db.add(p)
        await db.commit()

    print("✅ База данных заполнена тестовыми данными!")
    print(f"   Категорий: {len(cats)}")
    print(f"   Товаров: {len(products)}")


if __name__ == "__main__":
    asyncio.run(seed())
