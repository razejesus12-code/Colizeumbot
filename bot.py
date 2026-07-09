import asyncio
import csv
import io
import logging
import os
import random
import sqlite3
import string
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()  # если рядом есть файл .env — подхватит переменные из него (для локального теста)

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    Contact,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

# ---------- НАСТРОЙКИ (заполняются из переменных окружения) ----------
BOT_TOKEN = os.environ["BOT_TOKEN"]  # токен от @BotFather
BOT_USERNAME = os.environ.get("BOT_USERNAME", "Colizeum_Tashkent_City_bot")
ADMIN_IDS = {
    int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()
}

BONUS_TEXT = os.environ.get(
    "BONUS_TEXT",
    "Спасибо за подписку! 🎁\n\n"
    "Твой бонус: +20% к следующему пополнению баланса.\n"
    "Покажи это сообщение администратору на стойке в течение 7 дней.",
)
DAYTIME_BONUS_TEXT = os.environ.get(
    "DAYTIME_BONUS_TEXT",
    "Спасибо за подписку! ☀️🎁\n\n"
    "Сейчас будний день — держи усиленный бонус: +30% к следующему пополнению баланса,\n"
    "если придёшь сегодня с 10:00 до 17:00.\n"
    "Покажи это сообщение администратору на стойке.",
)
REFERRER_BONUS_TEXT = os.environ.get(
    "REFERRER_BONUS_TEXT",
    "Твой друг присоединился по твоей ссылке! 🙌\n"
    "Бонус тебе: +30% к следующему пополнению баланса.\n"
    "Покажи это сообщение администратору на стойке.",
)
REFERRED_EXTRA_TEXT = os.environ.get(
    "REFERRED_EXTRA_TEXT",
    "\n\n🙌 Ты пришёл по приглашению друга — держи ещё +10% сверху к бонусу выше!",
)
REMINDER_TEXT = os.environ.get(
    "REMINDER_TEXT",
    "Давно не виделись! 👋\n\n"
    "Держи бонус на возвращение: +20% к следующему пополнению баланса.\n"
    "Покажи это сообщение администратору на стойке в течение 5 дней.",
)
REMINDER_DELAY_DAYS = int(os.environ.get("REMINDER_DELAY_DAYS", "3"))

CLUB_ADDRESS = os.environ.get("CLUB_ADDRESS", "уточняется — впишите адрес в переменную CLUB_ADDRESS")
CLUB_PHONE = os.environ.get("CLUB_PHONE", "уточняется — впишите телефон в переменную CLUB_PHONE")
CLUB_HOURS = os.environ.get("CLUB_HOURS", "уточняется — впишите часы работы в переменную CLUB_HOURS")
CLUB_LATITUDE = os.environ.get("CLUB_LATITUDE", "")
CLUB_LONGITUDE = os.environ.get("CLUB_LONGITUDE", "")
PROMO_TEXT = os.environ.get(
    "PROMO_TEXT",
    "Актуальные акции скоро появятся здесь 🎉\nСледи за обновлениями в этом чате.",
)
PACKAGES_TEXT = os.environ.get(
    "PACKAGES_TEXT",
    "🔥 Выгодные пакеты\n\n"
    "☀️ Standard (ROG периферия):\n"
    "🕗 Утро 3 часа (08:00-11:00) — 25 000 UZS\n"
    "🕚 День 3 часа (11:00-15:00) — 35 000 UZS\n\n"
    "🎮 Bootcamp (LOGITECH периферия, 5 игровых мест):\n"
    "🕗 Утренний пакет 3 часа (08:00-11:00) — 35 000 UZS\n"
    "🕚 Дневной пакет 3 часа (11:00-15:00) — 50 000 UZS\n\n"
    "Полный прайс по всем залам — кнопка 🧾 Прайс",
)
HOOKAH_TEXT = os.environ.get(
    "HOOKAH_TEXT",
    "💨 Кальян в нашем клубе\n\n"
    "Будни до 17:00 — 180 000 UZS\n"
    "Будни после 17:00 — 200 000 UZS\n"
    "Выходные — 200 000 UZS",
)

DB_PATH = os.environ.get("DB_PATH", "subscribers.db")
TASHKENT_TZ = ZoneInfo("Asia/Tashkent")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROMOS_DIR = os.path.join(BASE_DIR, "promos")
PACKAGES_DIR = os.path.join(BASE_DIR, "packages")
HOOKAH_DIR = os.path.join(BASE_DIR, "hookah")

# буквы/цифры без похожих друг на друга символов (0/O, 1/I/L), чтобы код было легко читать вслух
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

BONUS_LABELS = {
    "welcome": "Бонус за подписку",
    "daytime": "Усиленный дневной бонус",
    "referrer": "Бонус за приглашённого друга",
    "reminder": "Бонус на возвращение",
    "checkin": "Отметка визита",
    "tier_silver": "Бонус за статус Серебряный",
    "tier_gold": "Бонус за статус Золотой",
    "review_no_photo": "Отзыв без фото",
    "review_photo": "Отзыв с фото",
    "lottery_jackpot": "Джекпот в лототроне 🎰",
    "lottery_win": "Выигрыш в лототроне 🎰",
}

REVIEW_POINTS_NO_PHOTO = os.environ.get("REVIEW_POINTS_NO_PHOTO", "15 000")
REVIEW_POINTS_PHOTO = os.environ.get("REVIEW_POINTS_PHOTO", "25 000")
LOTTERY_JACKPOT_POINTS = os.environ.get("LOTTERY_JACKPOT_POINTS", "30 000")
LOTTERY_WIN_POINTS = os.environ.get("LOTTERY_WIN_POINTS", "10 000")

# что администратор должен начислить гостю при погашении кода
# (checkin намеренно не включён - это просто счётчик визита, без начисления)
BONUS_AMOUNTS = {
    "welcome": f"+{os.environ.get('BONUS_PERCENT_WELCOME', '20')}% к пополнению",
    "daytime": f"+{os.environ.get('BONUS_PERCENT_DAYTIME', '30')}% к пополнению",
    "referrer": f"+{os.environ.get('BONUS_PERCENT_REFERRER', '30')}% к пополнению",
    "reminder": f"+{os.environ.get('BONUS_PERCENT_REMINDER', '20')}% к пополнению",
    "tier_silver": f"+{os.environ.get('BONUS_PERCENT_TIER_SILVER', '15')}% к пополнению",
    "tier_gold": f"+{os.environ.get('BONUS_PERCENT_TIER_GOLD', '25')}% к пополнению",
    "review_no_photo": f"{REVIEW_POINTS_NO_PHOTO} баллов на баланс",
    "review_photo": f"{REVIEW_POINTS_PHOTO} баллов на баланс",
    "lottery_jackpot": f"{LOTTERY_JACKPOT_POINTS} баллов на баланс",
    "lottery_win": f"{LOTTERY_WIN_POINTS} баллов на баланс",
}

TIER_SILVER_VISITS = int(os.environ.get("TIER_SILVER_VISITS", "10"))
TIER_GOLD_VISITS = int(os.environ.get("TIER_GOLD_VISITS", "25"))
TIER_SILVER_TEXT = os.environ.get(
    "TIER_SILVER_TEXT",
    "🥈 Поздравляем, ты получил статус Серебряный гость!\n"
    "Бонус: +15% к следующему пополнению баланса.",
)
TIER_GOLD_TEXT = os.environ.get(
    "TIER_GOLD_TEXT",
    "🥇 Поздравляем, ты получил статус Золотой гость!\n"
    "Бонус: +25% к следующему пополнению баланса.\n"
    "Плюс приоритет на бронирование любимого места.",
)
TIER_LABELS = {"": "Без статуса", "silver": "🥈 Серебряный", "gold": "🥇 Золотой"}

FEEDBACK_DELAY_HOURS = int(os.environ.get("FEEDBACK_DELAY_HOURS", "2"))
FEEDBACK_PROMPT_TEXT = os.environ.get(
    "FEEDBACK_PROMPT_TEXT",
    "Как прошёл твой визит сегодня? 🎮\n"
    "Будем рады короткой оценке от 1 до 5 — это помогает нам стать лучше.",
)

REVIEW_LINK_2GIS = os.environ.get("REVIEW_LINK_2GIS", "")
REVIEW_LINK_GOOGLE = os.environ.get("REVIEW_LINK_GOOGLE", "")
REVIEW_LINK_YANDEX = os.environ.get("REVIEW_LINK_YANDEX", "")
REVIEW_PROMPT_TEXT = os.environ.get(
    "REVIEW_PROMPT_TEXT",
    "Оставь отзыв — получи баллы на баланс! 🎁\n\n"
    f"📝 Без фото — {REVIEW_POINTS_NO_PHOTO} баллов\n"
    f"📸 С фото (интерьеры клуба или ты в клубе) — {REVIEW_POINTS_PHOTO} баллов\n\n"
    "После того как оставишь отзыв, выбери ниже, какой именно ты оставил:",
)

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# временное хранилище "кто по чьей ссылке идёт регистрироваться"
# (живёт только пока бот не перезапущен - этого достаточно для короткого пути /start -> контакт)
PENDING_REFERRALS: dict[int, int] = {}

MAIN_MENU_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💰 Баланс"), KeyboardButton(text="🎉 Акции")],
        [KeyboardButton(text="📍 Клуб"), KeyboardButton(text="👥 Пригласить друга")],
        [KeyboardButton(text="🧾 Прайс"), KeyboardButton(text="✅ Я в клубе")],
        [KeyboardButton(text="💎 Мой статус"), KeyboardButton(text="🎰 Лототрон")],
    ],
    resize_keyboard=True,
)

_review_buttons = []
if REVIEW_LINK_2GIS:
    _review_buttons.append([InlineKeyboardButton(text="📍 Оставить отзыв в 2GIS", url=REVIEW_LINK_2GIS)])
if REVIEW_LINK_GOOGLE:
    _review_buttons.append(
        [InlineKeyboardButton(text="🗺 Оставить отзыв в Google Maps", url=REVIEW_LINK_GOOGLE)]
    )
if REVIEW_LINK_YANDEX:
    _review_buttons.append(
        [InlineKeyboardButton(text="🟡 Оставить отзыв в Яндекс Картах", url=REVIEW_LINK_YANDEX)]
    )
_review_buttons.append(
    [InlineKeyboardButton(text=f"✅ Без фото ({REVIEW_POINTS_NO_PHOTO})", callback_data="review_done_no_photo")]
)
_review_buttons.append(
    [InlineKeyboardButton(text=f"✅ С фото ({REVIEW_POINTS_PHOTO})", callback_data="review_done_photo")]
)
REVIEW_KB = InlineKeyboardMarkup(inline_keyboard=_review_buttons)


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
            joined_at TEXT,
            referred_by INTEGER,
            reminder_sent INTEGER DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bonuses (
            code TEXT PRIMARY KEY,
            telegram_id INTEGER,
            bonus_type TEXT,
            created_at TEXT,
            used_at TEXT,
            used_by_admin INTEGER
        )
        """
    )
    for column, coltype in (
        ("referred_by", "INTEGER"),
        ("reminder_sent", "INTEGER DEFAULT 0"),
        ("visits_confirmed", "INTEGER DEFAULT 0"),
        ("tier", "TEXT DEFAULT ''"),
        ("first_checkin_at", "TEXT"),
        ("review_prompted", "INTEGER DEFAULT 0"),
        ("review_bonus_claimed", "INTEGER DEFAULT 0"),
        ("last_spin_date", "TEXT"),
    ):
        try:
            conn.execute(f"ALTER TABLE subscribers ADD COLUMN {column} {coltype}")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()


def db_add_subscriber(
    telegram_id: int, username: str, full_name: str, phone: str, referred_by: int | None
) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT INTO subscribers (telegram_id, username, full_name, phone, joined_at, referred_by, reminder_sent)
        VALUES (?, ?, ?, ?, ?, ?, 0)
        ON CONFLICT(telegram_id) DO UPDATE SET phone=excluded.phone
        """,
        (telegram_id, username, full_name, phone, datetime.now().isoformat(), referred_by),
    )
    conn.commit()
    conn.close()


def db_is_subscriber(telegram_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT 1 FROM subscribers WHERE telegram_id = ?", (telegram_id,)).fetchone()
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


def db_referral_count(telegram_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    n = conn.execute("SELECT COUNT(*) FROM subscribers WHERE referred_by = ?", (telegram_id,)).fetchone()[0]
    conn.close()
    return n


def db_remove_subscriber(telegram_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM subscribers WHERE telegram_id = ?", (telegram_id,))
    conn.commit()
    conn.close()


def db_wipe_all_subscribers() -> int:
    """Полностью удаляет ВСЕХ подписчиков и все бонусные коды. Необратимо."""
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0]
    conn.execute("DELETE FROM subscribers")
    conn.execute("DELETE FROM bonuses")
    conn.commit()
    conn.close()
    return count


def db_due_for_reminder(delay_days: int) -> list[int]:
    cutoff = (datetime.now() - timedelta(days=delay_days)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT telegram_id FROM subscribers WHERE reminder_sent = 0 AND joined_at <= ?", (cutoff,)
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def db_mark_reminder_sent(telegram_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE subscribers SET reminder_sent = 1 WHERE telegram_id = ?", (telegram_id,))
    conn.commit()
    conn.close()


def db_create_bonus(telegram_id: int, bonus_type: str) -> str:
    conn = sqlite3.connect(DB_PATH)
    while True:
        code = "".join(random.choices(CODE_ALPHABET, k=6))
        exists = conn.execute("SELECT 1 FROM bonuses WHERE code = ?", (code,)).fetchone()
        if not exists:
            break
    conn.execute(
        "INSERT INTO bonuses (code, telegram_id, bonus_type, created_at) VALUES (?, ?, ?, ?)",
        (code, telegram_id, bonus_type, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()
    return code


def db_redeem_bonus(code: str, admin_id: int) -> tuple[str, dict | None]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM bonuses WHERE code = ?", (code,)).fetchone()

    if row is None:
        conn.close()
        return "not_found", None

    if row["used_at"]:
        result = dict(row)
        conn.close()
        return "already_used", result

    conn.execute(
        "UPDATE bonuses SET used_at = ?, used_by_admin = ? WHERE code = ?",
        (datetime.now().isoformat(), admin_id, code),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM bonuses WHERE code = ?", (code,)).fetchone()
    conn.close()
    return "ok", dict(updated)


def db_get_visits(telegram_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT visits_confirmed FROM subscribers WHERE telegram_id = ?", (telegram_id,)).fetchone()
    conn.close()
    return row[0] if row and row[0] is not None else 0


def db_get_tier(telegram_id: int) -> str:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT tier FROM subscribers WHERE telegram_id = ?", (telegram_id,)).fetchone()
    conn.close()
    return row[0] if row and row[0] else ""


def db_increment_visits(telegram_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE subscribers SET visits_confirmed = visits_confirmed + 1 WHERE telegram_id = ?", (telegram_id,)
    )
    conn.commit()
    new_count = conn.execute(
        "SELECT visits_confirmed FROM subscribers WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()[0]
    conn.close()
    return new_count


def db_set_tier(telegram_id: int, tier: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE subscribers SET tier = ? WHERE telegram_id = ?", (tier, telegram_id))
    conn.commit()
    conn.close()


def db_set_first_checkin(telegram_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE subscribers SET first_checkin_at = ? WHERE telegram_id = ? AND first_checkin_at IS NULL",
        (datetime.now().isoformat(), telegram_id),
    )
    conn.commit()
    conn.close()


def db_due_for_feedback(delay_hours: int) -> list[int]:
    cutoff = (datetime.now() - timedelta(hours=delay_hours)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT telegram_id FROM subscribers "
        "WHERE review_prompted = 0 AND first_checkin_at IS NOT NULL AND first_checkin_at <= ?",
        (cutoff,),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def db_mark_feedback_prompted(telegram_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE subscribers SET review_prompted = 1 WHERE telegram_id = ?", (telegram_id,))
    conn.commit()
    conn.close()


def db_has_review_claimed(telegram_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT review_bonus_claimed FROM subscribers WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()
    return bool(row and row[0])


def db_mark_review_claimed(telegram_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE subscribers SET review_bonus_claimed = 1 WHERE telegram_id = ?", (telegram_id,))
    conn.commit()
    conn.close()


def db_reset_review_claim(telegram_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE subscribers SET review_bonus_claimed = 0 WHERE telegram_id = ?", (telegram_id,))
    conn.commit()
    conn.close()


def db_get_last_spin_date(telegram_id: int) -> str | None:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT last_spin_date FROM subscribers WHERE telegram_id = ?", (telegram_id,)).fetchone()
    conn.close()
    return row[0] if row and row[0] else None


def db_set_last_spin_date(telegram_id: int, date_str: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE subscribers SET last_spin_date = ? WHERE telegram_id = ?", (date_str, telegram_id))
    conn.commit()
    conn.close()


def db_list_by_tier(tier: str) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT telegram_id, phone, full_name, visits_confirmed FROM subscribers WHERE tier = ? ORDER BY visits_confirmed DESC",
        (tier,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def db_export_all() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT telegram_id, username, full_name, phone, joined_at, referred_by, "
        "visits_confirmed, tier, review_bonus_claimed FROM subscribers ORDER BY joined_at"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------- СОСТОЯНИЯ ----------
class BroadcastState(StatesGroup):
    waiting_text = State()
    waiting_confirm = State()


class ReviewState(StatesGroup):
    waiting_screenshot = State()


class WipeAllState(StatesGroup):
    waiting_confirm = State()


WIPE_CONFIRM_PHRASE = "УДАЛИТЬ ВСЕХ"


# ---------- ВСПОМОГАТЕЛЬНОЕ ----------
def get_bonus_text_and_type() -> tuple[str, str]:
    now = datetime.now(TASHKENT_TZ)
    is_weekday = now.weekday() < 5
    is_daytime = 10 <= now.hour < 17
    if is_weekday and is_daytime:
        return DAYTIME_BONUS_TEXT, "daytime"
    return BONUS_TEXT, "welcome"


def get_referral_link(telegram_id: int) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=ref{telegram_id}"


# ---------- ОБРАБОТЧИКИ: ГОСТИ ----------
@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject) -> None:
    user_id = message.from_user.id

    if command.args and command.args.startswith("ref"):
        try:
            referrer_id = int(command.args[3:])
            if referrer_id != user_id and db_is_subscriber(referrer_id):
                PENDING_REFERRALS[user_id] = referrer_id
        except ValueError:
            pass

    if db_is_subscriber(user_id):
        await message.answer("Ты уже с нами! 🎮 Вот меню:", reply_markup=MAIN_MENU_KB)
        return

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить номер телефона", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer(
        "Привет! Это бот клуба Colizeum Tashkent City. 🎮\n\n"
        "Номер телефона нужен только для того, чтобы начислять тебе бонусы "
        "и не пропускать акции клуба — никуда, кроме нашей базы, он не передаётся.\n\n"
        "Поделись номером, чтобы получить бонус:",
        reply_markup=kb,
    )


@router.message(F.contact)
async def handle_contact(message: Message) -> None:
    user_id = message.from_user.id
    contact: Contact = message.contact
    if contact.user_id and contact.user_id != user_id:
        await message.answer("Пожалуйста, отправь именно свой номер телефона 🙂")
        return

    referrer_id = PENDING_REFERRALS.pop(user_id, None)

    db_add_subscriber(
        telegram_id=user_id,
        username=message.from_user.username or "",
        full_name=message.from_user.full_name,
        phone=contact.phone_number,
        referred_by=referrer_id,
    )

    bonus_text, bonus_type = get_bonus_text_and_type()
    code = db_create_bonus(user_id, bonus_type)
    bonus_text = f"{bonus_text}\n\n🔑 Код бонуса: {code}"

    if referrer_id:
        bonus_text += REFERRED_EXTRA_TEXT
        try:
            referrer_code = db_create_bonus(referrer_id, "referrer")
            await bot.send_message(referrer_id, f"{REFERRER_BONUS_TEXT}\n\n🔑 Код бонуса: {referrer_code}")
        except Exception:
            logging.warning("не удалось уведомить пригласившего %s", referrer_id)

    await message.answer(bonus_text, reply_markup=MAIN_MENU_KB)


@router.message(Command("stop"))
async def cmd_stop(message: Message) -> None:
    db_remove_subscriber(message.from_user.id)
    await message.answer(
        "Ты отписан(а) от рассылки. Если захочешь вернуться — просто нажми /start.",
        reply_markup=ReplyKeyboardRemove(),
    )


# ---------- МЕНЮ ----------
@router.message(F.text == "💰 Баланс")
async def menu_balance(message: Message) -> None:
    await message.answer(
        "Бот пока не подключён к кассовой системе клуба, поэтому точный баланс "
        "не покажет 🙏\nУзнать баланс можно у администратора на стойке."
    )


PROMO_SUBMENU_KB = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="🔥 Выгодные пакеты", callback_data="promo_packages")],
        [InlineKeyboardButton(text="💨 Кальян", callback_data="promo_hookah")],
        [InlineKeyboardButton(text="⭐ Отзыв за бонус", callback_data="promo_review")],
        [InlineKeyboardButton(text="🎁 Все акции", callback_data="promo_general")],
    ]
)

FEEDBACK_KB = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text=str(i), callback_data=f"feedback_{i}") for i in range(1, 6)]]
)


@router.message(F.text == "🎉 Акции")
async def menu_promo(message: Message) -> None:
    await message.answer("Выбери, что интересно:", reply_markup=PROMO_SUBMENU_KB)


async def send_image_folder_or_text(chat_id: int, folder: str, caption_text: str) -> None:
    images = []
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith((".jpg", ".jpeg", ".png")):
                images.append(os.path.join(folder, name))

    if not images:
        await bot.send_message(chat_id, caption_text)
        return

    if len(images) == 1:
        await bot.send_photo(chat_id, FSInputFile(images[0]), caption=caption_text)
        return

    media = [
        InputMediaPhoto(media=FSInputFile(path), caption=caption_text if i == 0 else None)
        for i, path in enumerate(images)
    ]
    await bot.send_media_group(chat_id, media)


@router.callback_query(F.data == "promo_packages")
async def cb_promo_packages(callback: CallbackQuery) -> None:
    await callback.answer()
    await send_image_folder_or_text(callback.message.chat.id, PACKAGES_DIR, PACKAGES_TEXT)


@router.callback_query(F.data == "promo_hookah")
async def cb_promo_hookah(callback: CallbackQuery) -> None:
    await callback.answer()
    await send_image_folder_or_text(callback.message.chat.id, HOOKAH_DIR, HOOKAH_TEXT)


@router.callback_query(F.data == "promo_review")
async def cb_promo_review(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(REVIEW_PROMPT_TEXT, reply_markup=REVIEW_KB)


@router.callback_query(F.data == "promo_general")
async def cb_promo_general(callback: CallbackQuery) -> None:
    await callback.answer()
    await send_image_folder_or_text(callback.message.chat.id, PROMOS_DIR, PROMO_TEXT)


@router.message(F.text == "📍 Клуб")
async def menu_club(message: Message) -> None:
    await message.answer(
        f"📍 Адрес: {CLUB_ADDRESS}\n📞 Телефон: {CLUB_PHONE}\n🕒 Часы работы: {CLUB_HOURS}"
    )
    if CLUB_LATITUDE and CLUB_LONGITUDE:
        try:
            await message.answer_location(latitude=float(CLUB_LATITUDE), longitude=float(CLUB_LONGITUDE))
        except ValueError:
            logging.warning("некорректные CLUB_LATITUDE/CLUB_LONGITUDE")


@router.message(F.text == "🧾 Прайс")
async def menu_price(message: Message) -> None:
    photo_path = os.path.join(BASE_DIR, "price.jpg")
    if not os.path.exists(photo_path):
        await message.answer("Прайс временно недоступен, уточните у администратора 🙏")
        return
    await message.answer_photo(FSInputFile(photo_path), caption="Актуальный прайс-лист 🧾")


@router.message(F.text == "👥 Пригласить друга")
@router.message(Command("invite"))
async def menu_invite(message: Message) -> None:
    user_id = message.from_user.id
    if not db_is_subscriber(user_id):
        await message.answer("Сначала подпишись через /start, потом сможешь приглашать друзей 🙂")
        return
    link = get_referral_link(user_id)
    count = db_referral_count(user_id)
    await message.answer(
        "Приглашай друзей и получай бонус за каждого! 🙌\n\n"
        f"Твоя ссылка:\n{link}\n\n"
        f"Приглашено друзей: {count}\n\n"
        "Когда друг перейдёт по ссылке и поделится номером — вы оба получите бонус."
    )


@router.message(F.text == "✅ Я в клубе")
async def menu_checkin(message: Message) -> None:
    user_id = message.from_user.id
    if not db_is_subscriber(user_id):
        await message.answer("Сначала подпишись через /start 🙂")
        return
    code = db_create_bonus(user_id, "checkin")
    await message.answer(
        "Покажи этот код администратору, чтобы засчитать визит 📍\n\n"
        f"🔑 Код: {code}\n\n"
        "Так мы отслеживаем твои визиты для статуса постоянного гостя 🏆"
    )


@router.message(F.text == "💎 Мой статус")
async def menu_status(message: Message) -> None:
    user_id = message.from_user.id
    if not db_is_subscriber(user_id):
        await message.answer("Сначала подпишись через /start 🙂")
        return

    visits = db_get_visits(user_id)
    tier = db_get_tier(user_id)
    tier_label = TIER_LABELS.get(tier, tier)

    if tier == "gold":
        progress = "Ты уже на максимальном статусе — так держать! 🏆"
    elif tier == "silver":
        left = max(TIER_GOLD_VISITS - visits, 0)
        progress = f"До статуса 🥇 Золотой осталось визитов: {left}"
    else:
        left = max(TIER_SILVER_VISITS - visits, 0)
        progress = f"До статуса 🥈 Серебряный осталось визитов: {left}"

    await message.answer(
        f"💎 Твой статус: {tier_label}\n"
        f"Подтверждённых визитов: {visits}\n\n"
        f"{progress}\n\n"
        "Визит засчитывается, когда администратор гасит твой код из кнопки «✅ Я в клубе»."
    )


@router.message(F.text == "🎰 Лототрон")
async def menu_lottery(message: Message) -> None:
    user_id = message.from_user.id
    if not db_is_subscriber(user_id):
        await message.answer("Сначала подпишись через /start 🙂")
        return

    today = datetime.now(TASHKENT_TZ).date().isoformat()
    if db_get_last_spin_date(user_id) == today:
        await message.answer("Ты уже крутил барабан сегодня 🎰\nОдин спин в день — приходи завтра!")
        return

    db_set_last_spin_date(user_id, today)
    dice_msg = await message.answer_dice(emoji="🎰")
    value = dice_msg.dice.value
    await asyncio.sleep(4)

    if value == 64:
        code = db_create_bonus(user_id, "lottery_jackpot")
        amount = BONUS_AMOUNTS.get("lottery_jackpot")
        await message.answer(f"🎉 ДЖЕКПОТ! 777 🎰\nБонус: {amount}\n\n🔑 Код бонуса: {code}")
    elif value in (1, 22, 43):
        code = db_create_bonus(user_id, "lottery_win")
        amount = BONUS_AMOUNTS.get("lottery_win")
        await message.answer(f"🎉 Выигрыш! Три одинаковых символа!\nБонус: {amount}\n\n🔑 Код бонуса: {code}")
    else:
        await message.answer("Почти! В этот раз не повезло 😅\nПриходи завтра, будет ещё один спин!")


# ---------- ОБРАБОТЧИКИ: АДМИН ----------
def is_admin(telegram_id: int) -> bool:
    return telegram_id in ADMIN_IDS


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    await message.answer(f"Подписчиков в базе: {db_count()}")


@router.message(Command("redeem"))
async def cmd_redeem(message: Message, command: CommandObject) -> None:
    if not is_admin(message.from_user.id):
        return

    code = (command.args or "").strip().upper()
    if not code:
        await message.answer("Использование: /redeem КОД\n(код гость показывает из своего бонусного сообщения)")
        return

    status, row = db_redeem_bonus(code, message.from_user.id)

    if status == "not_found":
        await message.answer("❌ Код не найден. Проверьте, правильно ли он введён.")
        return

    if status == "already_used":
        used_at = row["used_at"][:16].replace("T", " ")
        label = BONUS_LABELS.get(row["bonus_type"], row["bonus_type"])
        amount = BONUS_AMOUNTS.get(row["bonus_type"])
        amount_line = f"\nБонус: {amount}" if amount else ""
        await message.answer(f"⚠️ Этот код уже был погашен {used_at}.\nТип бонуса: {label}{amount_line}")
        return

    label = BONUS_LABELS.get(row["bonus_type"], row["bonus_type"])

    if row["bonus_type"] == "checkin":
        reply = f"✅ Визит подтверждён (без денежного бонуса)\nID гостя: {row['telegram_id']}"
    else:
        amount = BONUS_AMOUNTS.get(row["bonus_type"])
        amount_line = f"\n💰 Начислить: {amount}" if amount else ""
        reply = f"✅ Бонус активирован!\nТип: {label}{amount_line}\nID гостя: {row['telegram_id']}"

    if row["bonus_type"] == "checkin":
        guest_id = row["telegram_id"]
        visits = db_increment_visits(guest_id)
        if visits == 1:
            db_set_first_checkin(guest_id)
        current_tier = db_get_tier(guest_id)
        new_tier = None
        if visits >= TIER_GOLD_VISITS and current_tier != "gold":
            new_tier = "gold"
        elif visits >= TIER_SILVER_VISITS and current_tier not in ("silver", "gold"):
            new_tier = "silver"

        reply += f"\nВизитов у гостя: {visits}"

        if new_tier:
            db_set_tier(guest_id, new_tier)
            tier_text = TIER_GOLD_TEXT if new_tier == "gold" else TIER_SILVER_TEXT
            tier_code = db_create_bonus(guest_id, f"tier_{new_tier}")
            try:
                await bot.send_message(guest_id, f"{tier_text}\n\n🔑 Код бонуса: {tier_code}")
            except Exception:
                logging.warning("не удалось уведомить гостя %s о новом статусе", guest_id)
            reply += f"\n🎉 Гость получил новый статус: {TIER_LABELS.get(new_tier, new_tier)}!"

            if new_tier == "gold":
                conn = sqlite3.connect(DB_PATH)
                phone_row = conn.execute(
                    "SELECT phone, full_name FROM subscribers WHERE telegram_id = ?", (guest_id,)
                ).fetchone()
                conn.close()
                phone = phone_row[0] if phone_row else "неизвестен"
                name = phone_row[1] if phone_row else ""
                for admin_id in ADMIN_IDS:
                    try:
                        await bot.send_message(
                            admin_id,
                            "🥇 Новый Золотой гость!\n\n"
                            f"Имя: {name}\nТелефон: {phone}\n\n"
                            "Не забудьте вручную проставить постоянную скидку 10% в CRM клуба "
                            "(бот не имеет доступа к CRM и не может сделать это сам).",
                        )
                    except Exception:
                        logging.warning("не удалось уведомить админа %s", admin_id)

    await message.answer(reply)


@router.message(Command("export"))
async def cmd_export(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return

    rows = db_export_all()
    if not rows:
        await message.answer("В базе пока нет подписчиков.")
        return

    tier_map = {"": "Без статуса", "silver": "Серебряный", "gold": "Золотой"}

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["Telegram ID", "Имя", "Телефон", "Юзернейм", "Дата регистрации", "Визитов", "Статус", "Отзыв оставлен", "Приглашён (ID)"]
    )
    for r in rows:
        writer.writerow(
            [
                r["telegram_id"],
                r["full_name"] or "",
                r["phone"] or "",
                r["username"] or "",
                (r["joined_at"] or "")[:16].replace("T", " "),
                r["visits_confirmed"] or 0,
                tier_map.get(r["tier"] or "", r["tier"]),
                "Да" if r["review_bonus_claimed"] else "Нет",
                r["referred_by"] or "",
            ]
        )

    csv_bytes = buffer.getvalue().encode("utf-8-sig")  # BOM, чтобы Excel правильно показал кириллицу
    filename = f"colizeum_subscribers_{datetime.now(TASHKENT_TZ).date().isoformat()}.csv"
    await message.answer_document(
        BufferedInputFile(csv_bytes, filename=filename),
        caption=f"Выгрузка подписчиков: {len(rows)} чел.",
    )


@router.message(Command("vip"))
async def cmd_vip(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    gold = db_list_by_tier("gold")
    if not gold:
        await message.answer("Пока нет гостей с золотым статусом.")
        return
    lines = ["🥇 Золотые гости (для проставления скидки 10% в CRM):\n"]
    for g in gold:
        name = g["full_name"] or "без имени"
        lines.append(f"• {name} — {g['phone']} ({g['visits_confirmed']} визитов)")
    await message.answer("\n".join(lines))


@router.message(Command("reset_review"))
async def cmd_reset_review(message: Message, command: CommandObject) -> None:
    if not is_admin(message.from_user.id):
        return
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await message.answer(
            "Использование: /reset_review TELEGRAM_ID\n"
            "(снимает отметку «бонус за отзыв уже получен» у гостя, чтобы он мог попробовать снова)"
        )
        return
    telegram_id = int(arg)
    db_reset_review_claim(telegram_id)
    await message.answer(f"Готово ✅ Гость {telegram_id} снова может получить бонус за отзыв.")


@router.message(Command("delete_all_users"))
async def cmd_delete_all_users(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    count = db_count()
    await message.answer(
        f"⚠️ ВНИМАНИЕ! Это удалит ВСЕХ подписчиков ({count} чел.) и все их бонусы "
        "БЕЗВОЗВРАТНО. Отменить это будет нельзя.\n\n"
        f"Чтобы подтвердить, напиши точно эту фразу:\n{WIPE_CONFIRM_PHRASE}\n\n"
        "Чтобы отменить — напиши /cancel"
    )
    await state.set_state(WipeAllState.waiting_confirm)


@router.message(WipeAllState.waiting_confirm, Command("cancel"))
async def cmd_wipe_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Удаление отменено, база не тронута.")


@router.message(WipeAllState.waiting_confirm, F.text == WIPE_CONFIRM_PHRASE)
async def cmd_wipe_confirm(message: Message, state: FSMContext) -> None:
    await state.clear()
    removed = db_wipe_all_subscribers()
    await message.answer(f"✅ Готово. Удалено подписчиков: {removed}. База очищена полностью.")


@router.message(WipeAllState.waiting_confirm)
async def cmd_wipe_wrong(message: Message) -> None:
    await message.answer(
        f"Фраза не совпадает. Чтобы удалить всех, напиши точно:\n{WIPE_CONFIRM_PHRASE}\n"
        "Или /cancel, чтобы отменить."
    )


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "Отправь текст, который нужно разослать всем подписчикам.\nЧтобы отменить — напиши /cancel"
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
            db_remove_subscriber(tg_id)
        await asyncio.sleep(0.05)

    await status_msg.edit_text(f"Готово ✅\nОтправлено: {sent}\nНе доставлено (удалены из базы): {failed}")


@router.message(BroadcastState.waiting_confirm)
async def broadcast_wrong_answer(message: Message) -> None:
    await message.answer("Напиши ДА для отправки или /cancel для отмены.")


@router.callback_query(F.data.in_({"review_done_no_photo", "review_done_photo"}))
async def cb_review_done(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    if db_has_review_claimed(user_id):
        await callback.message.answer("Бонус за отзыв уже был выдан раньше, спасибо ещё раз! 🙏")
        return

    bonus_type = "review_photo" if callback.data == "review_done_photo" else "review_no_photo"
    await state.update_data(review_bonus_type=bonus_type)
    await state.set_state(ReviewState.waiting_screenshot)
    await callback.message.answer(
        "Пришли, пожалуйста, скриншот своего отзыва (просто фото экрана с отзывом) — "
        "и я сразу выдам код бонуса. Это нужно, чтобы администратор мог сверить отзыв.\n\n"
        "Передумал? Напиши /cancel"
    )


@router.message(ReviewState.waiting_screenshot, F.photo)
async def review_screenshot_received(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    bonus_type = data.get("review_bonus_type", "review_no_photo")
    await state.clear()

    user_id = message.from_user.id
    if db_has_review_claimed(user_id):
        await message.answer("Бонус за отзыв уже был выдан раньше, спасибо ещё раз! 🙏")
        return

    db_mark_review_claimed(user_id)
    code = db_create_bonus(user_id, bonus_type)
    amount = BONUS_AMOUNTS.get(bonus_type, "")
    await message.answer(f"🙏 Спасибо за отзыв!\nБонус: {amount}\n\n🔑 Код бонуса: {code}")

    label = BONUS_LABELS.get(bonus_type, bonus_type)
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_photo(
                admin_id,
                message.photo[-1].file_id,
                caption=(
                    f"📸 Скриншот отзыва от {message.from_user.full_name} (id {user_id})\n"
                    f"Тип: {label}\nКод: {code}"
                ),
            )
        except Exception:
            logging.warning("не удалось переслать скриншот отзыва админу %s", admin_id)


@router.message(ReviewState.waiting_screenshot)
async def review_screenshot_wrong(message: Message, state: FSMContext) -> None:
    if (message.text or "").strip().lower() == "/cancel":
        await state.clear()
        await message.answer("Отменено.")
        return
    await message.answer(
        "Пожалуйста, пришли именно скриншот (фото) своего отзыва 🙏\nИли напиши /cancel, чтобы отменить."
    )


@router.callback_query(F.data.startswith("feedback_"))
async def cb_feedback(callback: CallbackQuery) -> None:
    await callback.answer("Спасибо за оценку! 🙌")
    rating = callback.data.split("_", 1)[1]
    user = callback.from_user

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id, f"📝 Оценка визита: {rating}/5\nГость: {user.full_name} (id {user.id})"
            )
        except Exception:
            logging.warning("не удалось переслать оценку админу %s", admin_id)

    await callback.message.answer("Спасибо, что поделился впечатлением! 🙏")


# ---------- ФОНОВЫЕ ЗАДАЧИ ----------
async def reminder_loop() -> None:
    while True:
        try:
            for tg_id in db_due_for_reminder(REMINDER_DELAY_DAYS):
                try:
                    code = db_create_bonus(tg_id, "reminder")
                    await bot.send_message(tg_id, f"{REMINDER_TEXT}\n\n🔑 Код бонуса: {code}")
                except Exception:
                    logging.warning("не удалось отправить напоминание %s", tg_id)
                db_mark_reminder_sent(tg_id)
                await asyncio.sleep(0.1)
        except Exception:
            logging.exception("ошибка в reminder_loop")
        await asyncio.sleep(3600)


async def feedback_loop() -> None:
    while True:
        try:
            for tg_id in db_due_for_feedback(FEEDBACK_DELAY_HOURS):
                try:
                    await bot.send_message(tg_id, FEEDBACK_PROMPT_TEXT, reply_markup=FEEDBACK_KB)
                except Exception:
                    logging.warning("не удалось отправить запрос обратной связи %s", tg_id)
                db_mark_feedback_prompted(tg_id)
                await asyncio.sleep(0.1)
        except Exception:
            logging.exception("ошибка в feedback_loop")
        await asyncio.sleep(3600)


# ---------- ЗАПУСК ----------
async def main() -> None:
    db_init()
    asyncio.create_task(reminder_loop())
    asyncio.create_task(feedback_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
