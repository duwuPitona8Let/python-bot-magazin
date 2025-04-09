import os
import sqlite3
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv
from yookassa import Configuration, Payment
import uuid


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


load_dotenv()


TOKEN = os.getenv('BOT_TOKEN')
YOOKASSA_SHOP_ID = os.getenv('YOOKASSA_SHOP_ID')
YOOKASSA_SECRET_KEY = os.getenv('YOOKASSA_SECRET_KEY')

if not TOKEN:
    raise ValueError("❌ Токен бота не найден! Создайте файл .env с BOT_TOKEN=ваш_токен")
if not YOOKASSA_SHOP_ID or not YOOKASSA_SECRET_KEY:
    raise ValueError("❌ Параметры ЮKassa не найдены! Добавьте YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY в .env")


print(f"Shop ID: {YOOKASSA_SHOP_ID}")
print(f"Secret Key: {YOOKASSA_SECRET_KEY}")


Configuration.account_id = YOOKASSA_SHOP_ID
Configuration.secret_key = YOOKASSA_SECRET_KEY

bot = Bot(token=TOKEN)
dp = Dispatcher()

ADMIN_IDS = []


class PaymentStates(StatesGroup):
    confirm_payment = State()
    awaiting_payment_confirmation = State()

class AdminStates(StatesGroup):
    menu = State()
    add_product_choose_category_type = State()
    add_product_category = State()
    add_product_name = State()
    add_product_desc = State()
    add_product_price = State()
    add_product_stock = State()
    add_product_promo = State()
    restock_category = State()
    restock_amount = State()
    delete_select_category = State()
    delete_select_product = State()


def init_db():
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()

    cursor.execute('''CREATE TABLE IF NOT EXISTS products
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     category TEXT NOT NULL,
                     name TEXT NOT NULL,
                     description TEXT,
                     price INTEGER NOT NULL,
                     promo_code TEXT UNIQUE,
                     stock INTEGER DEFAULT 1,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS purchases
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     user_id INTEGER NOT NULL,
                     product_id INTEGER NOT NULL,
                     purchase_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     FOREIGN KEY (product_id) REFERENCES products (id))''')

    if not cursor.execute("SELECT 1 FROM products LIMIT 1").fetchone():
        initial_data = [
            ("🍔 Еда", "Макдоналдс", "Скидка 20%", 150, "MCD2023", 15),
            ("🍔 Еда", "KFC", "Бесплатный напиток", 100, "KFCBEST", 10),
            ("🎮 Игры", "Steam", "Ключ для любой игры", 500, "STEAM-1234", 5),
            ("🎮 Игры", "Epic Games", "Рандомный ключ", 400, "EPIC-5678", 3),
            ("📺 Подписки", "Spotify", "3 месяца Premium", 300, "SPOTY-2023", 8),
            ("📺 Подписки", "Netflix", "1 месяц подписки", 350, "NETFLIX-2023", 6)
        ]
        cursor.executemany(
            "INSERT INTO products (category, name, description, price, promo_code, stock) VALUES (?, ?, ?, ?, ?, ?)",
            initial_data
        )
        conn.commit()

    conn.close()

init_db()


def get_categories(include_empty=False):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    query = "SELECT DISTINCT category FROM products" if include_empty else "SELECT DISTINCT category FROM products WHERE stock > 0"
    categories = cursor.execute(query).fetchall()
    conn.close()
    return [cat[0] for cat in categories]

def get_empty_categories():
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DISTINCT p1.category 
        FROM products p1
        WHERE NOT EXISTS (
            SELECT 1 FROM products p2 
            WHERE p2.category = p1.category AND p2.stock > 0
        )
    ''')
    empty_categories = [cat[0] for cat in cursor.fetchall()]
    conn.close()
    return empty_categories

def create_yookassa_payment(amount, description, product_id):
    payment = Payment.create({
        "amount": {
            "value": str(amount),
            "currency": "RUB"
        },
        "confirmation": {
            "type": "redirect",
            "return_url": "https://t.me/kolmakovmagazin_bot"
        },
        "description": description,
        "metadata": {"product_id": str(product_id)},
        "capture": True
    }, uuid.uuid4())
    return payment.id, payment.confirmation.confirmation_url

def admin_kb():
    kb = [
        [KeyboardButton(text="Добавить товар")],
        [KeyboardButton(text="Пополнить категорию")],
        [KeyboardButton(text="Просмотреть остатки")],
        [KeyboardButton(text="Удалить товар")],
        [KeyboardButton(text="Выйти из админки")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def main_kb():
    categories = get_categories(include_empty=True)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=cat, callback_data=f"cat_{cat}")]
        for cat in categories
    ])

def products_kb(category):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    products = cursor.execute(
        "SELECT id, name, price, stock FROM products WHERE category = ?",
        (category,)
    ).fetchall()
    conn.close()
    buttons = [
        [InlineKeyboardButton(
            text=f"{p[1]} - {p[2]}₽ ({p[3]} шт.)",
            callback_data=f"prod_{p[0]}"
        )] for p in products
    ]
    buttons.append([InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def payment_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", callback_data="confirm_payment")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_payment")]
    ])

def support_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆘 Поддержка", url=f"tg://user?id={ADMIN_IDS[0]}")]
    ])


@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "🛍️ Добро пожаловать в магазин!\n"
        "Выберите категорию товаров:",
        reply_markup=main_kb()
    )

@dp.message(Command("admin"))
async def admin_panel(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Доступ запрещён")
        return
    await message.answer("Админ-панель:", reply_markup=admin_kb())
    await state.set_state(AdminStates.menu)

@dp.message(Command("history"))
async def history(message: types.Message):
    try:
        conn = sqlite3.connect('shop.db')
        cursor = conn.cursor()
        purchases = cursor.execute('''
            SELECT pu.id, p.name, p.category, p.price, pu.purchase_date 
            FROM purchases pu
            JOIN products p ON pu.product_id = p.id
            WHERE pu.user_id = ?
            ORDER BY pu.purchase_date DESC
            LIMIT 10
        ''', (message.from_user.id,)).fetchall()
        if not purchases:
            await message.answer("📭 У вас пока нет покупок.")
            return
        text = "📜 История ваших покупок:\n\n"
        for purchase_id, name, category, price, date in purchases:
            text += f"🛒 #{purchase_id}\n"
            text += f"Товар: {name} ({category})\n"
            text += f"Цена: {price}₽\n"
            text += f"Дата: {date}\n\n"
        await message.answer(text)
    except Exception as e:
        logger.error(f"Ошибка получения истории: {e}")
        await message.answer("⚠️ Не удалось загрузить историю покупок")
    finally:
        conn.close()

@dp.message(Command("support"))
async def support_command(message: types.Message):
    await message.answer(
        "🛟 Служба поддержки\n\n"
        "Если у вас есть вопросы по покупке или работе бота, "
        "нажмите кнопку ниже чтобы связаться с оператором",
        reply_markup=support_kb()
    )


@dp.message(F.text == "Добавить товар", AdminStates.menu)
async def add_product(message: types.Message, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.button(text="Новая категория", callback_data="new_category")
    builder.button(text="Существующая категория", callback_data="existing_category")
    await message.answer(
        "Выберите тип категории для товара:",
        reply_markup=builder.as_markup()
    )
    await state.set_state(AdminStates.add_product_choose_category_type)

@dp.callback_query(F.data == "new_category", AdminStates.add_product_choose_category_type)
async def new_category(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("Введите название новой категории:")
    await state.set_state(AdminStates.add_product_category)

@dp.callback_query(F.data == "existing_category", AdminStates.add_product_choose_category_type)
async def existing_category(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    categories = get_categories(include_empty=True)
    builder = InlineKeyboardBuilder()
    for cat in categories:
        builder.button(text=cat, callback_data=f"existing_cat_{cat}")
    await callback.message.answer(
        "Выберите существующую категорию:",
        reply_markup=builder.as_markup()
    )
    await state.set_state(AdminStates.add_product_category)

@dp.callback_query(F.data.startswith("existing_cat_"), AdminStates.add_product_category)
async def existing_category_select(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    category = callback.data.split("_", 2)[2]
    await state.update_data(category=category)
    await callback.message.answer("Введите название товара:")
    await state.set_state(AdminStates.add_product_name)

@dp.message(AdminStates.add_product_category)
async def add_product_category(message: types.Message, state: FSMContext):
    await state.update_data(category=message.text)
    await message.answer("Введите название товара:")
    await state.set_state(AdminStates.add_product_name)

@dp.message(AdminStates.add_product_name)
async def add_product_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите описание товара:")
    await state.set_state(AdminStates.add_product_desc)

@dp.message(AdminStates.add_product_desc)
async def add_product_desc(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await message.answer("Введите цену товара:")
    await state.set_state(AdminStates.add_product_price)

@dp.message(AdminStates.add_product_price)
async def add_product_price(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Введите корректную цену товара (число):")
        return
    await state.update_data(price=int(message.text))
    await message.answer("Введите количество товара:")
    await state.set_state(AdminStates.add_product_stock)

@dp.message(AdminStates.add_product_stock)
async def add_product_stock(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Введите корректное количество товара (число):")
        return
    await state.update_data(stock=int(message.text))
    await message.answer("Введите промокод товара (если есть, или 'нет'):")
    await state.set_state(AdminStates.add_product_promo)

@dp.message(AdminStates.add_product_promo)
async def add_product_promo(message: types.Message, state: FSMContext):
    promo_code = message.text.strip() if message.text.strip().lower() != 'нет' else None
    data = await state.get_data()
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO products (category, name, description, price, promo_code, stock) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (data['category'], data['name'], data['description'], data['price'], promo_code, data['stock'])
        )
        conn.commit()
        await message.answer(
            f"✅ Товар успешно добавлен!\n\n"
            f"Категория: {data['category']}\n"
            f"Название: {data['name']}\n"
            f"Цена: {data['price']}₽\n"
            f"Количество: {data['stock']} шт.\n"
            f"Промокод: {promo_code if promo_code else 'отсутствует'}",
            reply_markup=admin_kb()
        )
    except sqlite3.IntegrityError as e:
        if "UNIQUE constraint failed" in str(e):
            await message.answer(
                "❌ Ошибка: промокод уже существует. Введите другой промокод:"
            )
            return
        await message.answer(f"❌ Ошибка базы данных: {str(e)}")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        conn.close()
        await state.set_state(AdminStates.menu)

@dp.message(F.text == "Пополнить категорию", AdminStates.menu)
async def restock_start(message: types.Message, state: FSMContext):
    empty_categories = get_empty_categories()
    if not empty_categories:
        await message.answer("Нет категорий с нулевыми остатками")
        return
    builder = InlineKeyboardBuilder()
    for cat in empty_categories:
        builder.button(text=cat, callback_data=f"restock_cat_{cat}")
    await message.answer(
        "Выберите категорию для пополнения:",
        reply_markup=builder.as_markup()
    )
    await state.set_state(AdminStates.restock_category)

@dp.callback_query(F.data.startswith("restock_cat_"), AdminStates.restock_category)
async def restock_category_select(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    category = callback.data.split("_", 2)[2]
    await state.update_data(restock_category=category)
    await callback.message.answer("Введите количество для добавafersния:")
    await state.set_state(AdminStates.restock_amount)

@dp.message(AdminStates.restock_amount)
async def restock_process(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Введите корректное количество (только число):")
        return
    amount = int(message.text)
    data = await state.get_data()
    category = data['restock_category']
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE products SET stock = stock + ? WHERE category = ?",
            (amount, category)
        )
        conn.commit()
        await message.answer(
            f"✅ Категория {category} успешно пополнена на {amount} единиц!",
            reply_markup=admin_kb()
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        conn.close()
        await state.set_state(AdminStates.menu)

@dp.message(F.text == "Просмотреть остатки", AdminStates.menu)
async def view_stock(message: types.Message):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute("SELECT category, name, stock FROM products ORDER BY category")
    products = cursor.fetchall()
    conn.close()
    if not products:
        await message.answer("Нет товаров в базе")
        return
    text = "📦 Остатки товаров:\n\n"
    current_category = None
    for category, name, stock in products:
        if category != current_category:
            text += f"\n<b>{category}</b>\n"
            current_category = category
        text += f"{name}: {stock} шт.\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "Удалить товар", AdminStates.menu)
async def delete_start(message: types.Message, state: FSMContext):
    categories = get_categories(include_empty=True)
    if not categories:
        await message.answer("Нет доступных категорий.")
        return
    builder = InlineKeyboardBuilder()
    for cat in categories:
        builder.button(text=cat, callback_data=f"delcat_{cat}")
    await message.answer(
        "Выберите категорию для удаления товара:",
        reply_markup=builder.as_markup()
    )
    await state.set_state(AdminStates.delete_select_category)

@dp.callback_query(F.data.startswith("delcat_"), AdminStates.delete_select_category)
async def delete_choose_product(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    category = callback.data.split("_", 1)[1]
    await state.update_data(del_category=category)
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    products = cursor.execute(
        "SELECT id, name FROM products WHERE category = ?",
        (category,)
    ).fetchall()
    conn.close()
    if not products:
        await callback.message.answer("В этой категории нет товаров.")
        return
    builder = InlineKeyboardBuilder()
    for pid, name in products:
        builder.button(text=name, callback_data=f"delprod_{pid}")
    await callback.message.answer(
        "Выберите товар для удаления:",
        reply_markup=builder.as_markup()
    )
    await state.set_state(AdminStates.delete_select_product)

@dp.callback_query(F.data.startswith("delprod_"), AdminStates.delete_select_product)
async def delete_product(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    product_id = int(callback.data.split("_", 1)[1])
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM purchases WHERE product_id = ?", (product_id,))
        cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
        conn.commit()
        await callback.message.answer(
            "✅ Товар успешно удалён.",
            reply_markup=admin_kb()
        )
    except Exception as e:
        await callback.message.answer(
            f"❌ Ошибка при удалении товара: {str(e)}",
            reply_markup=admin_kb()
        )
    finally:
        conn.close()
        await state.set_state(AdminStates.menu)

@dp.message(F.text == "Выйти из админки", AdminStates.menu)
async def exit_admin(message: types.Message, state: FSMContext):
    await message.answer(
        "Админ-панель закрыта",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await state.clear()
    await start(message)


@dp.callback_query(F.data.startswith("cat_"))
async def show_products(callback: types.CallbackQuery):
    await callback.answer()
    try:
        category = callback.data.split("_", 1)[1]
        await callback.message.edit_text(
            f"🔍 Категория: {category}\nВыберите товар:",
            reply_markup=products_kb(category)
        )
    except Exception as e:
        logger.error(f"Ошибка показа товаров: {e}")
        await callback.message.edit_text("⚠️ Ошибка загрузки товаров")

@dp.callback_query(F.data.startswith("prod_"))
async def show_product(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        product_id = int(callback.data.split("_", 1)[1])
        conn = sqlite3.connect('shop.db')
        cursor = conn.cursor()
        product = cursor.execute(
            "SELECT name, description, price, stock FROM products WHERE id = ?",
            (product_id,)
        ).fetchone()
        if not product or product[3] <= 0:
            await callback.message.edit_text("😔 Товар закончился")
            return
        name, desc, price, stock = product
        await callback.message.edit_text(
            f"🎁 *{name}*\n\n"
            f"📝 {desc}\n"
            f"💵 Цена: {price}₽\n"
            f"📦 Осталось: {stock} шт.\n\n"
            "Нажмите 'Оплатить' для покупки",
            reply_markup=payment_kb(),
            parse_mode="Markdown"
        )
        await state.set_state(PaymentStates.confirm_payment)
        await state.update_data(product_id=product_id)
    except Exception as e:
        logger.error(f"Ошибка показа товара: {e}")
        await callback.message.edit_text("⚠️ Ошибка загрузки товара")
    finally:
        conn.close()

@dp.callback_query(F.data == "confirm_payment", PaymentStates.confirm_payment)
async def process_payment(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    conn = None
    try:
        data = await state.get_data()
        product_id = data['product_id']
        user_id = callback.from_user.id
        conn = sqlite3.connect('shop.db')
        cursor = conn.cursor()
        product = cursor.execute(
            "SELECT name, description, price, stock FROM products WHERE id = ?",
            (product_id,)
        ).fetchone()
        if not product or product[3] <= 0:
            await callback.message.edit_text("😔 Товар закончился")
            return
        name, desc, price, stock = product
        payment_id, payment_url = create_yookassa_payment(price, f"Покупка: {name}", product_id)
        await state.update_data(payment_id=payment_id, user_id=user_id)
        await callback.message.edit_text(
            f"💳 Для оплаты товара *{name}* перейдите по ссылке:\n\n"
            f"[Оплатить {price}₽]({payment_url})\n\n"
            "После оплаты нажмите 'Проверить платеж' ниже.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Проверить платеж", callback_data="check_payment")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_payment")]
            ]),
            parse_mode="Markdown"
        )
        await state.set_state(PaymentStates.awaiting_payment_confirmation)
    except Exception as e:
        logger.error(f"Ошибка создания платежа: {e}")
        await callback.message.edit_text("⚠️ Ошибка при создании платежа")
    finally:
        if conn:
            conn.close()

@dp.callback_query(F.data == "check_payment", PaymentStates.awaiting_payment_confirmation)
async def check_payment(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    conn = None
    try:
        data = await state.get_data()
        payment_id = data['payment_id']
        product_id = data['product_id']
        user_id = data['user_id']
        payment = Payment.find_one(payment_id)
        if payment.status == "succeeded":
            conn = sqlite3.connect('shop.db')
            cursor = conn.cursor()
            product = cursor.execute(
                "SELECT name, promo_code, stock FROM products WHERE id = ?",
                (product_id,)
            ).fetchone()
            if not product or product[2] <= 0:
                await callback.message.edit_text("😔 Товар закончился")
                return
            name, promo_code, stock = product
            cursor.execute(
                "UPDATE products SET stock = stock - 1 WHERE id = ? AND stock > 0",
                (product_id,)
            )
            if cursor.rowcount == 0:
                await callback.message.edit_text("😔 Товар закончился")
                return
            cursor.execute(
                "INSERT INTO purchases (user_id, product_id) VALUES (?, ?)",
                (user_id, product_id)
            )
            purchase_id = cursor.lastrowid
            conn.commit()
            await callback.message.edit_text(
                f"✅ Покупка #{purchase_id} совершена успешно!\n\n"
                f"🎁 Товар: {name}\n"
                f"🔑 Промокод: `{promo_code}`\n\n"
                "Если возникли проблемы - воспользуйтесь командой /support",
                parse_mode="Markdown",
                reply_markup=support_kb()
            )
            await state.clear()
        elif payment.status == "canceled" or payment.status == "failed":
            await callback.message.edit_text(
                "❌ Платеж был отменен или не удался. Попробуйте снова.",
                reply_markup=main_kb()
            )
            await state.clear()
        else:
            await callback.message.edit_text(
                "⏳ Платеж еще не завершен. Нажмите 'Проверить' снова через несколько секунд.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Проверить платеж", callback_data="check_payment")],
                    [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_payment")]
                ])
            )
    except Exception as e:
        logger.error(f"Ошибка проверки платежа: {e}")
        if conn:
            conn.rollback()
        await callback.message.edit_text("⚠️ Ошибка при проверке платежа")
    finally:
        if conn:
            conn.close()

@dp.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        await callback.message.edit_text(
            "❌ Покупка отменена",
            reply_markup=main_kb()
        )
    except Exception as e:
        logger.error(f"Ошибка отмены платежа: {e}")
        await callback.message.edit_text("⚠️ Ошибка при отмене")
    finally:
        await state.clear()

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    await callback.answer()
    try:
        await callback.message.edit_text(
            "Выберите категорию:",
            reply_markup=main_kb()
        )
    except Exception as e:
        logger.error(f"Ошибка возврата: {e}")
        await callback.message.edit_text("⚠️ Ошибка при возврате")


if __name__ == "__main__":
    from aiogram.fsm.strategy import FSMStrategy
    dp.fsm.strategy = FSMStrategy.CHAT

    async def main():
        await dp.start_polling(bot, skip_updates=True)

    import asyncio
    asyncio.run(main())