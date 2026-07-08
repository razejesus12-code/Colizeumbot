import asyncio
import logging
import os
import sqlite3
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()  # если рядом есть файл .env — подхватит переменные из него (для локального теста)

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Contact,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

# ---------- НАСТРОЙКИ (заполняются из переменных окружения) ----------
BOT_TOKEN = os.environ["BOT_TOKEN"]  # токен от @BotFather
ADMIN_IDS = {
    int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()
}
BONUS_TEXT = os.environ.get(
    "BONUS_TEXT",
    "Спасибо за подписку! 🎁\n\n"
    "Твой бонус: +20% к следующему пополнению баланса.\n"
    "Покажи это сообщение администратору на стойке в течение 7 дней.",
)
DB_PATH = os.environ.get("DB_PATH", "subscribers.db")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)


# ---------- БАЗА ДАННЫХ ----------
def db_init() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subscribers (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            phone TEXT,
            joined_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def db_add_subscriber(telegram_id: int, username: str, full_name: str, phone: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT INTO subscribers (telegram_id, username, full_name, phone, joined_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET phone=excluded.phone
        """,
        (telegram_id, username, full_name, phone, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def db_is_subscriber(telegram_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT 1 FROM subscribers WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()
    return row is not None


def db_all_subscriber_ids() -> list[int]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT telegram_id FROM subscribers").fetchall()
    conn.close()
    return [r[0] for r in rows]


def db_count() -> int:
    conn = sqlite3.connect(DB_PATH)
    n = conn.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0]
    conn.close()
    return n


def db_remove_subscriber(telegram_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM subscribers WHERE telegram_id = ?", (telegram_id,))
    conn.commit()
    conn.close()


# ---------- СОСТОЯНИЯ ДЛЯ РАССЫЛКИ ----------
class BroadcastState(StatesGroup):
    waiting_text = State()
    waiting_confirm = State()


# ---------- ОБРАБОТЧИКИ: ГОСТИ ----------
@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    if db_is_subscriber(message.from_user.id):
        await message.answer(
            "Ты уже с нами! 🎮\nЖди новостей и акций в этом чате."
        )
        return

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить номер телефона", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer(
        "Привет! Это бот клуба Colizeum. 🎮\n\n"
        "Поделись номером телефона, чтобы получить бонус и не пропускать акции.",
        reply_markup=kb,
    )


@router.message(F.contact)
async def handle_contact(message: Message) -> None:
    contact: Contact = message.contact
    # защита: чтобы гость не мог отправить чужой контакт
    if contact.user_id and contact.user_id != message.from_user.id:
        await message.answer("Пожалуйста, отправь именно свой номер телефона 🙂")
        return

    db_add_subscriber(
        telegram_id=message.from_user.id,
        username=message.from_user.username or "",
        full_name=message.from_user.full_name,
        phone=contact.phone_number,
    )
    await message.answer(BONUS_TEXT, reply_markup=ReplyKeyboardRemove())


@router.message(Command("stop"))
async def cmd_stop(message: Message) -> None:
    db_remove_subscriber(message.from_user.id)
    await message.answer("Ты отписан(а) от рассылки. Если захочешь вернуться — просто нажми /start.")


# ---------- ОБРАБОТЧИКИ: АДМИН ----------
def is_admin(telegram_id: int) -> bool:
    return telegram_id in ADMIN_IDS


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    await message.answer(f"Подписчиков в базе: {db_count()}")


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "Отправь текст, который нужно разослать всем подписчикам.\n"
        "Чтобы отменить — напиши /cancel"
    )
    await state.set_state(BroadcastState.waiting_text)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer("Рассылка отменена.")


@router.message(BroadcastState.waiting_text)
async def broadcast_get_text(message: Message, state: FSMContext) -> None:
    await state.update_data(text=message.html_text)
    count = db_count()
    await message.answer(
        f"Получатели: {count} чел.\n\n"
        f"Вот текст сообщения:\n\n{message.text}\n\n"
        f"Отправляем? Напиши ДА для отправки или /cancel для отмены.",
    )
    await state.set_state(BroadcastState.waiting_confirm)


@router.message(BroadcastState.waiting_confirm, F.text.upper() == "ДА")
async def broadcast_confirm(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    text = data["text"]
    await state.clear()

    ids = db_all_subscriber_ids()
    sent, failed = 0, 0
    status_msg = await message.answer(f"Начинаю рассылку на {len(ids)} чел...")

    for tg_id in ids:
        try:
            await bot.send_message(tg_id, text)
            sent += 1
        except Exception:
            failed += 1
            # если бот заблокирован пользователем - удаляем из базы
            db_remove_subscriber(tg_id)
        await asyncio.sleep(0.05)  # не превышать лимиты Telegram

    await status_msg.edit_text(f"Готово ✅\nОтправлено: {sent}\nНе доставлено (удалены из базы): {failed}")


@router.message(BroadcastState.waiting_confirm)
async def broadcast_wrong_answer(message: Message) -> None:
    await message.answer("Напиши ДА для отправки или /cancel для отмены.")


# ---------- ЗАПУСК ----------
async def main() -> None:
    db_init()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
