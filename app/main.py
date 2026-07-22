from decimal import Decimal
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, ConfigDict
import json
import httpx

from app.database import engine, get_db
from app.models import Base, User, Category, Product, CartItem, Order, OrderItem, OrderStatus

BOT_TOKEN = "8875866899:AAEM-8DRNWIhwHfsRDQy3YvA3SxzwnEzeug"
SELLER_IDS = [7890854793, 940063562]


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    slug: str

class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str] = None
    price: Decimal
    image_url: Optional[str] = None
    stock: int
    is_active: bool
    category: Optional[CategoryOut] = None

class ProductCreate(BaseModel):
    name: str
    description: Optional[str] = None
    price: float
    stock: int = 0
    image_url: Optional[str] = None
    category_id: Optional[int] = None

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    stock: Optional[int] = None
    image_url: Optional[str] = None
    is_active: Optional[bool] = None
    category_id: Optional[int] = None

class CartItemAdd(BaseModel):
    product_id: int
    quantity: int = 1

class CartItemUpdate(BaseModel):
    quantity: int

class CartItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product: ProductOut
    quantity: int

class CartOut(BaseModel):
    items: list[CartItemOut]
    total: Decimal

class OrderCreate(BaseModel):
    delivery_address: str
    phone: str

class OrderStatusUpdate(BaseModel):
    status: OrderStatus

class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product: ProductOut
    quantity: int
    price_at_purchase: Decimal

class OrderOut(BaseModel):
    id: int
    status: OrderStatus
    delivery_address: Optional[str]
    phone: Optional[str] = None
    total_price: Decimal
    created_at: str
    items: list[OrderItemOut] = []


async def get_current_user(
    x_init_data: str = Header("", alias="X-Init-Data"),
    db: AsyncSession = Depends(get_db),
) -> User:
    telegram_id = None
    username = None
    full_name = None
    try:
        from urllib.parse import parse_qsl, unquote
        vals = dict(parse_qsl(unquote(x_init_data), keep_blank_values=True))
        user_data = json.loads(vals.get("user", "{}"))
        telegram_id = user_data.get("id")
        username = user_data.get("username")
        full_name = f"{user_data.get('first_name', '')} {user_data.get('last_name', '')}".strip()
    except Exception:
        pass
    if not telegram_id:
        raise HTTPException(401, "Invalid init data")
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        user = User(telegram_id=telegram_id, username=username, full_name=full_name)
        db.add(user)
        await db.flush()
    return user


def check_seller(x_seller_key: str):
    if x_seller_key != BOT_TOKEN:
        raise HTTPException(403, "Forbidden")


async def notify_seller(order_id: int, total: Decimal, address: str, phone: str, items: list, buyer: str, buyer_id: int):
    items_text = "\n".join([f"• {i.product.name} × {i.quantity} = {int(i.price_at_purchase * i.quantity)} ₽" for i in items])
    text = (
        f"🛍 <b>Новый заказ #{order_id}!</b>\n\n"
        f"👤 Покупатель: {buyer}\n"
        f"📞 Телефон: {phone}\n"
        f"📦 Товары:\n{items_text}\n\n"
        f"💰 Итого: <b>{int(total)} ₽</b>\n"
        f"📍 Адрес: {address}"
    )
    keyboard = {
        "inline_keyboard": [[
            {"text": "🚚 Отправлен", "callback_data": f"seller_shipped_{order_id}_{buyer_id}"},
            {"text": "❌ Отменён", "callback_data": f"seller_cancelled_{order_id}_{buyer_id}"},
        ]]
    }
    try:
        async with httpx.AsyncClient() as client:
            for seller_id in SELLER_IDS:
                await client.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={"chat_id": seller_id, "text": text, "parse_mode": "HTML", "reply_markup": keyboard},
                    timeout=5
                )
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()

app = FastAPI(title="Cosmetics API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/categories/", response_model=list[CategoryOut])
async def list_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Category))
    return result.scalars().all()


@app.get("/api/v1/products/", response_model=list[ProductOut])
async def list_products(
    category_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = 0,
    limit: int = 40,
    db: AsyncSession = Depends(get_db),
):
    q = select(Product).where(Product.is_active == True).options(selectinload(Product.category))
    if category_id:
        q = q.where(Product.category_id == category_id)
    if search:
        q = q.where(Product.name.ilike(f"%{search}%"))
    q = q.offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@app.get("/api/v1/products/{product_id}", response_model=ProductOut)
async def get_product(product_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Product).where(Product.id == product_id).options(selectinload(Product.category))
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")
    return product


@app.post("/api/v1/products/", response_model=ProductOut, status_code=201)
async def create_product(
    data: ProductCreate,
    x_seller_key: str = Header("", alias="X-Seller-Key"),
    db: AsyncSession = Depends(get_db),
):
    check_seller(x_seller_key)
    product = Product(**data.model_dump())
    db.add(product)
    await db.flush()
    await db.refresh(product)
    result = await db.execute(select(Product).where(Product.id == product.id).options(selectinload(Product.category)))
    return result.scalar_one()


@app.patch("/api/v1/products/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: int,
    data: ProductUpdate,
    x_seller_key: str = Header("", alias="X-Seller-Key"),
    db: AsyncSession = Depends(get_db),
):
    check_seller(x_seller_key)
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")
    for key, value in data.model_dump(exclude_none=True).items():
        setattr(product, key, value)
    await db.flush()
    result = await db.execute(select(Product).where(Product.id == product_id).options(selectinload(Product.category)))
    return result.scalar_one()


@app.delete("/api/v1/products/{product_id}", status_code=204)
async def delete_product(
    product_id: int,
    x_seller_key: str = Header("", alias="X-Seller-Key"),
    db: AsyncSession = Depends(get_db),
):
    check_seller(x_seller_key)
    await db.execute(delete(Product).where(Product.id == product_id))


@app.get("/api/v1/cart/", response_model=CartOut)
async def get_cart(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(
        select(CartItem).where(CartItem.user_id == current_user.id)
        .options(selectinload(CartItem.product).selectinload(Product.category))
    )
    items = result.scalars().all()
    total = sum(Decimal(str(i.product.price)) * i.quantity for i in items)
    return CartOut(items=items, total=total)


@app.post("/api/v1/cart/", status_code=201)
async def add_to_cart(
    data: CartItemAdd,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Product).where(Product.id == data.product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")
    result = await db.execute(
        select(CartItem).where(CartItem.user_id == current_user.id, CartItem.product_id == data.product_id)
    )
    item = result.scalar_one_or_none()
    if item:
        item.quantity += data.quantity
    else:
        item = CartItem(user_id=current_user.id, product_id=data.product_id, quantity=data.quantity)
        db.add(item)
    await db.flush()
    return {"ok": True}


@app.patch("/api/v1/cart/{product_id}")
async def update_cart_item(
    product_id: int,
    data: CartItemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if data.quantity <= 0:
        await db.execute(delete(CartItem).where(CartItem.user_id == current_user.id, CartItem.product_id == product_id))
        return {"ok": True}
    result = await db.execute(
        select(CartItem).where(CartItem.user_id == current_user.id, CartItem.product_id == product_id)
    )
    item = result.scalar_one_or_none()
    if item:
        item.quantity = data.quantity
    return {"ok": True}


@app.delete("/api/v1/cart/{product_id}", status_code=204)
async def remove_from_cart(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await db.execute(delete(CartItem).where(CartItem.user_id == current_user.id, CartItem.product_id == product_id))


@app.post("/api/v1/orders/", status_code=201)
async def create_order(
    data: OrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(CartItem).where(CartItem.user_id == current_user.id)
        .options(selectinload(CartItem.product))
    )
    cart = result.scalars().all()
    if not cart:
        raise HTTPException(400, "Cart is empty")
    total = Decimal("0")
    order = Order(user_id=current_user.id, delivery_address=data.delivery_address, total_price=0)
    db.add(order)
    await db.flush()
    order_items = []
    for item in cart:
        order_item = OrderItem(
            order_id=order.id,
            product_id=item.product_id,
            quantity=item.quantity,
            price_at_purchase=item.product.price,
        )
        db.add(order_item)
        order_items.append(order_item)
        total += Decimal(str(item.product.price)) * item.quantity
    order.total_price = total
    await db.execute(delete(CartItem).where(CartItem.user_id == current_user.id))
    await db.flush()
    for oi in order_items:
        oi.product = next(i.product for i in cart if i.product_id == oi.product_id)
    buyer = current_user.full_name or current_user.username or str(current_user.telegram_id)
    await notify_seller(order.id, total, data.delivery_address, data.phone, order_items, buyer, current_user.telegram_id)
    return {"id": order.id, "total_price": str(total)}


@app.patch("/api/v1/orders/{order_id}/status")
async def update_order_status(
    order_id: int,
    data: OrderStatusUpdate,
    x_seller_key: str = Header("", alias="X-Seller-Key"),
):
    if x_seller_key != BOT_TOKEN:
        raise HTTPException(403, "Forbidden")
    async with AsyncSession(engine) as db:
        result = await db.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(404, "Order not found")
        order.status = data.status
        await db.commit()
    return {"ok": True}


@app.get("/api/v1/orders/")
async def my_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Order).where(Order.user_id == current_user.id)
        .options(
            selectinload(Order.items)
            .selectinload(OrderItem.product)
            .selectinload(Product.category)
        )
        .order_by(Order.created_at.desc())
    )
    orders = result.scalars().all()
    result_list = []
    for o in orders:
        result_list.append(OrderOut(
            id=o.id,
            status=o.status,
            delivery_address=o.delivery_address,
            total_price=o.total_price,
            created_at=o.created_at.isoformat(),
            items=o.items,
        ))
    return result_list


@app.post("/api/v1/seed")
async def seed_db(db: AsyncSession = Depends(get_db)):
    cats = [
        Category(name="Уход за лицом", slug="face"),
        Category(name="Уход за телом", slug="body"),
        Category(name="Декоративная косметика", slug="makeup"),
        Category(name="Ароматы", slug="perfume"),
    ]
    for c in cats:
        db.add(c)
    await db.flush()
    products = [
        Product(name="Крем для лица SPF50", description="Увлажняющий крем с защитой от солнца", price=1290, stock=50, category_id=cats[0].id, image_url="https://images.unsplash.com/photo-1556228578-8c89e6adf883?w=400"),
        Product(name="Сыворотка с витамином C", description="Антиоксидантная сыворотка", price=2490, stock=30, category_id=cats[0].id, image_url="https://images.unsplash.com/photo-1620916566398-39f1143ab7be?w=400"),
        Product(name="Мицеллярная вода", description="Нежное очищение", price=590, stock=100, category_id=cats[0].id, image_url="https://images.unsplash.com/photo-1601049541271-7daf75a7c290?w=400"),
        Product(name="Скраб для тела", description="Кофейный скраб с маслом ши", price=890, stock=40, category_id=cats[1].id, image_url="https://images.unsplash.com/photo-1608248597279-f99d160bfcbc?w=400"),
        Product(name="Масло для тела", description="Питательное масло с витамином E", price=1190, stock=25, category_id=cats[1].id, image_url="https://images.unsplash.com/photo-1585652757141-4e462a1ef622?w=400"),
        Product(name="Помада матовая", description="Стойкая помада 24 часа", price=790, stock=60, category_id=cats[2].id, image_url="https://images.unsplash.com/photo-1586495777744-4e6232bf2f86?w=400"),
        Product(name="Тушь для ресниц", description="Объём и длина", price=690, stock=80, category_id=cats[2].id, image_url="https://images.unsplash.com/photo-1512207736890-6ffed8a84e8d?w=400"),
        Product(name="Тональный крем", description="Лёгкое покрытие", price=1490, stock=45, category_id=cats[2].id, image_url="https://images.unsplash.com/photo-1522338242992-e1a54906a8da?w=400"),
        Product(name="Парфюм Rose Garden", description="Цветочный аромат", price=3990, stock=20, category_id=cats[3].id, image_url="https://images.unsplash.com/photo-1541643600914-78b084683702?w=400"),
        Product(name="Парфюм Ocean Blue", description="Свежий морской аромат", price=2990, stock=15, category_id=cats[3].id, image_url="https://images.unsplash.com/photo-1523293182086-7651a899d37f?w=400"),
    ]
    for p in products:
        db.add(p)
    return {"ok": True, "products": len(products)}


@app.get("/health")
async def health():
    return {"status": "ok"}
