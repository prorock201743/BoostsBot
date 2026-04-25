import asyncio
import logging
import os
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.default import DefaultBotProperties
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from urllib.parse import quote

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = "/app/data/users.db"

CHANNELS = [
    {
        "title": os.getenv("CHANNEL_1_TITLE"),
        "url":   os.getenv("CHANNEL_1_URL"),
        "id":    os.getenv("CHANNEL_1_ID"),
    },
    {
        "title": os.getenv("CHANNEL_2_TITLE"),
        "url":   os.getenv("CHANNEL_2_URL"),
        "id":    os.getenv("CHANNEL_2_ID"),
    },
    {
        "title": os.getenv("CHANNEL_3_TITLE"),
        "url":   os.getenv("CHANNEL_3_URL"),
        "id":    os.getenv("CHANNEL_3_ID"),
    },
]

PROMO_CODES = {
    1: "boostMe",
    2: "notBad",
    3: "brilliant2026",
}

WELCOME_TEXT = (
    "👋 <b>Привет! Давай совместим приятное с полезным?</b>\n\n"
    "С тебя — подписка на наши каналы\n"
    "С нас — скидка до 40% на первый заказ 🎁\n\n"
    "Чем на больше каналов подпишешься — тем больше скидка. Жми 👇"
)

logging.basicConfig(level=logging.INFO)
session = AiohttpSession(proxy="socks5://127.0.0.1:10808")
bot = Bot(token=BOT_TOKEN, session=session, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()


def build_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=CHANNELS[0]["title"], url=CHANNELS[0]["url"], icon_custom_emoji_id=os.getenv("EMOJI_CH1"))],
        [InlineKeyboardButton(text=CHANNELS[1]["title"], url=CHANNELS[1]["url"], icon_custom_emoji_id=os.getenv("EMOJI_CH2"))],
        [InlineKeyboardButton(text=CHANNELS[2]["title"], url=CHANNELS[2]["url"], icon_custom_emoji_id=os.getenv("EMOJI_CH3"))],
        [InlineKeyboardButton(text="Проверить подписку", callback_data="check_sub", style='success')],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def count_subscriptions(user_id: int) -> int:
    count = 0
    for ch in CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=ch["id"], user_id=user_id)
            if member.status not in ("left", "kicked", "banned"):
                count += 1
        except Exception:
            pass
    return count


def init_db():
    os.makedirs("/app/data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            joined_at TEXT,
            promo_claimed INTEGER DEFAULT 0,
            promo_code TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_user(user_id: int, username: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO users (user_id, username, joined_at)
        VALUES (?, ?, ?)
    """, (user_id, username, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def mark_promo(user_id: int, promo_code: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        UPDATE users SET promo_claimed = 1, promo_code = ? WHERE user_id = ?
    """, (promo_code, user_id))
    conn.commit()
    conn.close()


def get_users(promo_claimed: bool) -> list:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE promo_claimed = ?", (1 if promo_claimed else 0,))
    users = [row[0] for row in cur.fetchall()]
    conn.close()
    return users


# Храним режим рассылки для каждого админа
broadcast_mode = {}


@dp.message(F.text.in_(["/broadcast_promo", "/broadcast_nopromo"]))
async def ask_broadcast_text(message: types.Message):
    if message.from_user.id != int(os.getenv("ADMIN_ID")):
        return

    broadcast_mode[message.from_user.id] = message.text

    label = "получили промокод" if message.text == "/broadcast_promo" else "не получили промокод"
    await message.answer(
    f"✍️ Напиши текст рассылки для тех, кто <b>{label}</b>:\n\n"
    f"Для отмены напиши /cancel"
)


@dp.message(F.func(lambda m: m.from_user.id in broadcast_mode))
async def do_broadcast(message: types.Message):
    if message.from_user.id != int(os.getenv("ADMIN_ID")):
        return

    if message.text and message.text.startswith("/"):  # ← защита от команд
        broadcast_mode.pop(message.from_user.id)
        await message.answer("❌ Рассылка отменена.")
        return

    mode = broadcast_mode.pop(message.from_user.id)
    promo_claimed = mode == "/broadcast_promo"
    users = get_users(promo_claimed)

    success, failed = 0, 0
    for user_id in users:
        try:
            await bot.send_message(user_id, message.text)
            success += 1
        except Exception:
            failed += 1

    await message.answer(
        f"📬 Рассылка завершена!\n\n"
        f"✅ Отправлено: {success}\n"
        f"❌ Не доставлено: {failed}"
    )


def get_stats() -> dict:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE promo_claimed = 1")
    claimed = cur.fetchone()[0]
    conn.close()
    return {"total": total, "claimed": claimed, "not_claimed": total - claimed}


@dp.message(F.text == "/stats")
async def cmd_stats(message: types.Message):
    if message.from_user.id != int(os.getenv("ADMIN_ID")):
        return

    stats = get_stats()
    await message.answer(
        f"📊 <b>Статистика бота:</b>\n\n"
        f"👥 Всего пользователей: <b>{stats['total']}</b>\n"
        f"🎁 Получили промокод: <b>{stats['claimed']}</b>\n"
        f"😔 Не получили промокод: <b>{stats['not_claimed']}</b>"
    )


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    save_user(message.from_user.id, message.from_user.username)
    await message.answer(WELCOME_TEXT, reply_markup=build_keyboard())


@dp.callback_query(F.data == "check_sub")
async def check_subscription(callback: types.CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id
    subscribed = await count_subscriptions(user_id)

    if subscribed == 0:
        await callback.message.answer(
            "😔 Ты пока не подписан ни на один канал.\n"
            "Подпишись хотя бы на один и нажми кнопку снова!"
        )
        return

    promo = PROMO_CODES[subscribed]
    mark_promo(user_id, promo)
    channel_word = {1: "канал", 2: "канала", 3: "канала"}[subscribed]
    manager = os.getenv("MANAGER_USERNAME")
    promo_text = f"Привет! Хочу взять бусты, мой промокод: {promo}"
    manager_url = f"https://t.me/{manager.lstrip('@')}?text={quote(promo_text)}"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сделать заказ", url=manager_url)]
    ])

    await callback.message.answer(
        f"🎉 Ты подписан на <b>{subscribed} {channel_word}</b>!\n\n"
        f"Твой промокод: <code>{promo}</code>\n\n"
        f"Нажми кнопку ниже и оформи заказ со скидкой 👇",
        reply_markup=keyboard
    )



async def main():
    init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())