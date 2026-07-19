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
SELLER_ID = 7890854793


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

class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product: ProductOut
    quantity: int
    price_at_purchase: Decimal

class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: OrderStatus
    delivery_address: Optional[str]
    total_price: Decimal
    created_at: str
    items: list[OrderItemOut] = []

    @classmethod
    def from_order(cls, order: Order):
        return cls(
            id=order.id,
            status=order.status,
            delivery_address=order.delivery_address,
            total_price=order.total_price,
            created_at=order.created_at.isoformat(),
            items=order.items,
        )


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


async def notify_seller(order_id: int, total: Decimal, address: str, items: list, buyer: str):
    items_text = "\n".join([f"• {i.product.name} × {i.quantity} = {int(i.price_at_purchase * i.quantity)} ₽" for i in items])
    text = (
        f"🛍 <b>Новый заказ #{order_id}!</b>\n\n"
        f"👤 Покупатель: {buyer}\n"
        f"📦 Товары:\n{items_text}\n\n"
        f"💰 Итого: <b>{int(total)} ₽</b>\n"
        f"📍 Адрес: {address}"
    )
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": SELLER_ID, "text": text, "parse_mode": "HTML"},
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
    await notify_seller(order.id, total, data.delivery_address, order_items, buyer)
    return {"id": order.id, "total_price": str(total)}


@app.get("/api/v1/orders/")
async def my_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Order).where(Order.user_id == current_user.id)
        .options(selectinload(Order.items).selectinload(OrderItem.product))
        .order_by(Order.created_at.desc())
    )
    orders = result.scalars().all()
    return [OrderOut.from_order(o) for o in orders]


@app.get("/health")
async def health():
    return {"status": "ok"}