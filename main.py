import asyncio
import sqlite3
import os
import logging
from datetime import datetime
import pandas as pd

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

# .env faylini yuklaymiz
load_dotenv()

# .env ichidan tokenni o'qiymiz
TOKEN = os.getenv("BOT_TOKEN")

# Agar token topilmasa, dasturni to'xtatish
if not TOKEN:
    raise ValueError("XATO: .env fayli ichida 'BOT_TOKEN' topilmadi!")

ADMIN_ID = 8241035253

# Bot va Dispatcher obyektlari
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

logging.basicConfig(level=logging.INFO)


# --- MA'LUMOTLAR BAZASI ---
def init_db():
    conn = sqlite3.connect('my_money.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS expenses 
                      (user_id INTEGER, amount REAL, category TEXT, date TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id INTEGER PRIMARY KEY, full_name TEXT, username TEXT)''')
    conn.commit()
    conn.close()


class ExpenseStates(StatesGroup):
    waiting_for_category = State()
    waiting_for_custom_category = State()


# --- KLAVIATURALAR ---
def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.row(types.KeyboardButton(text='📊 Statistika'), types.KeyboardButton(text='📁 Excel'))
    builder.row(types.KeyboardButton(text='🗑 Noldan boshlash'))
    return builder.as_markup(resize_keyboard=True)


def get_categories_inline():
    builder = InlineKeyboardBuilder()
    categories = ['🍔 Oziq-ovqat', '🍱 Tushlik', '🛍 Shoping', '🚕 Transport', '💡 Kommunal']
    for cat in categories:
        builder.add(types.InlineKeyboardButton(text=cat, callback_data=f"cat_{cat}"))

    builder.add(types.InlineKeyboardButton(text='➕ Boshqa (O’zingiz yozing)', callback_data="other_cat"))
    builder.adjust(2)
    return builder.as_markup()


# --- START ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    init_db()
    user = message.from_user
    conn = sqlite3.connect('my_money.db')
    conn.execute("INSERT OR REPLACE INTO users VALUES (?, ?, ?)", (user.id, user.full_name, user.username))
    conn.commit()
    conn.close()
    await message.answer(f"Assalomu alaykum {user.full_name}!\n<b>Xarajat summasini kiriting:</b>",
                         reply_markup=main_menu())


# --- ASOSIY TUGMALARNI QABUL QILISH ---
@dp.message(F.text == '📊 Statistika')
async def stat_handler(message: types.Message):
    await show_stats(message)


@dp.message(F.text == '📁 Excel')
async def excel_handler(message: types.Message):
    await send_excel(message)


@dp.message(F.text == '🗑 Noldan boshlash')
async def reset_handler(message: types.Message):
    await ask_reset(message)


# --- SUMMANI QABUL QILISH ---
@dp.message(F.text, StateFilter(None))
async def handle_amount(message: types.Message, state: FSMContext):
    clean_num = message.text.replace(" ", "").replace(",", "")
    try:
        amount = float(clean_num)
        await state.update_data(amount=amount)
        await message.answer(
            f"💰 Summa: <b>{amount:,.0f}</b> so'm\nToifani tanlang yoki o'zingiz xohlagan nomni yuboring:",
            reply_markup=get_categories_inline())
        await state.set_state(ExpenseStates.waiting_for_category)
    except ValueError:
        await message.answer("⚠️ Iltimos, xarajat summasini raqamda kiriting.")


# --- TAYYOR TOIFANI TANLASH ---
@dp.callback_query(F.data.startswith("cat_"), ExpenseStates.waiting_for_category)
async def save_cat(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    amount = data.get('amount')
    category = callback.data.split("cat_")[1]

    conn = sqlite3.connect('my_money.db')
    conn.execute("INSERT INTO expenses VALUES (?, ?, ?, ?)",
                 (callback.from_user.id, amount, category, datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit()
    conn.close()

    await callback.message.edit_text(f"✅ Saqlandi!\n💰 <b>{amount:,.0f}</b> so'm\n📂 <b>{category}</b>")
    await state.clear()


# --- "BOSHQA" TUGMASI ---
@dp.callback_query(F.data == "other_cat", ExpenseStates.waiting_for_category)
async def other_cat_prompt(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📝 <b>Xohlagan nomingizni yozib yuboring:</b>")
    await state.set_state(ExpenseStates.waiting_for_custom_category)


# --- HAR QANDAY MATNNI TOIFA SIFATIDA QABUL QILISH ---
@dp.message(ExpenseStates.waiting_for_custom_category)
async def custom_cat_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    amount = data.get('amount')
    category = message.text

    conn = sqlite3.connect('my_money.db')
    conn.execute("INSERT INTO expenses VALUES (?, ?, ?, ?)",
                 (message.from_user.id, amount, category, datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit()
    conn.close()

    await message.answer(f"✅ Saqlandi!\n💰 <b>{amount:,.0f}</b> so'm\n📂 <b>{category}</b>")
    await state.clear()


# --- STATISTIKA ---
async def show_stats(message: types.Message):
    conn = sqlite3.connect('my_money.db')
    res = conn.execute("SELECT category, SUM(amount) FROM expenses WHERE user_id=? GROUP BY category",
                       (message.from_user.id,)).fetchall()
    total_row = conn.execute("SELECT SUM(amount) FROM expenses WHERE user_id=?", (message.from_user.id,)).fetchone()
    total = total_row[0] if total_row[0] else 0
    conn.close()

    if not res:
        return await message.answer("Hali xarajatlar yo'q.")

    txt = "📊 <b>Hisob-kitob:</b>\n\n" + "\n".join([f"• {r[0]}: <code>{r[1]:,.0f}</code> so'm" for r in res])
    txt += f"\n\n💰 <b>Jami:</b> <code>{total:,.0f}</code> so'm"
    await message.answer(txt)


# --- EXCEL ---
async def send_excel(message: types.Message):
    user_id = message.from_user.id
    conn = sqlite3.connect('my_money.db')
    df = pd.read_sql_query(
        f"SELECT date as 'Sana', category as 'Toifa', amount as 'Summa' FROM expenses WHERE user_id={user_id}", conn)
    conn.close()

    if df.empty:
        return await message.answer("Ma'lumot topilmadi.")

    file_path = f"Xisobot_{user_id}.xlsx"
    df.to_excel(file_path, index=False)
    await message.answer_document(types.FSInputFile(file_path))
    if os.path.exists(file_path):
        os.remove(file_path)


# --- RESET ---
async def ask_reset(message: types.Message):
    btn = InlineKeyboardBuilder().add(
        types.InlineKeyboardButton(text="Ha", callback_data="reset_yes"),
        types.InlineKeyboardButton(text="Yo'q", callback_data="reset_no")
    )
    await message.answer("⚠️ Hamma ma'lumotlarni o'chirishni xohlaysizmi?", reply_markup=btn.as_markup())


@dp.callback_query(F.data == "reset_yes")
async def reset_db(callback: types.CallbackQuery):
    conn = sqlite3.connect('my_money.db')
    conn.execute("DELETE FROM expenses WHERE user_id=?", (callback.from_user.id,))
    conn.commit()
    conn.close()
    await callback.message.edit_text("🔄 Ma'lumotlaringiz tozalandi.")


async def main():
    init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot to'xtatildi!")