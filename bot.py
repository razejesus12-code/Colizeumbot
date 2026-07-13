import asyncio
import csv
import hashlib
import hmac
import io
import json
import logging
import os
import random
import sqlite3
import string
from datetime import date, datetime, timedelta
from urllib.parse import parse_qsl
from zoneinfo import ZoneInfo

from aiohttp import web
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
    WebAppInfo,
)

# ---------- НАСТРОЙКИ (заполняются из переменных окружения) ----------
BOT_TOKEN = os.environ["BOT_TOKEN"]  # токен от @BotFather
BOT_USERNAME = os.environ.get("BOT_USERNAME", "Colizeum_Tashkent_City_bot")
ADMIN_IDS = {
    int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()
}
# Отдельный владелец — для команд, которые не должны быть доступны даже другим админам
OWNER_ID = int(os.environ.get("OWNER_ID", "0") or "0")

BONUS_AMOUNT_WELCOME = os.environ.get("BONUS_AMOUNT_WELCOME", "35 000")
BONUS_AMOUNT_REFERRER = os.environ.get("BONUS_AMOUNT_REFERRER", "50 000")
# минимальная сумма пополнения, при которой welcome-бонус реально засчитывается —
# защита от фейковых Telegram-аккаунтов, фармящих бонус без реального визита
MIN_WELCOME_AMOUNT = int(os.environ.get("MIN_WELCOME_AMOUNT", "30000"))

BONUS_TEXT = os.environ.get(
    "BONUS_TEXT",
    "Спасибо за подписку! 🎁\n\n"
    f"Твой бонус: {BONUS_AMOUNT_WELCOME} сум на баланс (это час в Bootcamp 😉).\n"
    f"Начислим при пополнении баланса от {MIN_WELCOME_AMOUNT} сум — "
    "покажи это сообщение администратору на стойке в течение 7 дней.",
)
REFERRER_BONUS_TEXT = os.environ.get(
    "REFERRER_BONUS_TEXT",
    "Твой друг пришёл по твоей ссылке и уже был в клубе! 🙌\n"
    f"Бонус тебе: {BONUS_AMOUNT_REFERRER} сум на баланс.\n"
    "Покажи это сообщение администратору на стойке.",
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

DB_PATH = os.environ.get("DB_PATH", "/data/subscribers.db")
TASHKENT_TZ = ZoneInfo("Asia/Tashkent")
UTC_TZ = ZoneInfo("UTC")


def tashkent_day_range_to_naive_utc(date_from: date, date_to: date) -> tuple[str, str]:
    """date_from/date_to — календарные даты по Ташкенту, включительно.

    В базе метки времени пишутся как datetime.now().isoformat() — наивные,
    в часовом поясе сервера (на Railway это UTC). Поэтому границы периода
    считаем в Ташкенте и переводим в UTC, чтобы сравнение в SQL было верным.
    """
    start_local = datetime.combine(date_from, datetime.min.time(), tzinfo=TASHKENT_TZ)
    end_local = datetime.combine(date_to, datetime.min.time(), tzinfo=TASHKENT_TZ) + timedelta(days=1)
    start_utc = start_local.astimezone(UTC_TZ).replace(tzinfo=None)
    end_utc = end_local.astimezone(UTC_TZ).replace(tzinfo=None)
    return start_utc.isoformat(), end_utc.isoformat()


def last_full_week_sat_fri() -> tuple[date, date]:
    """Последняя полностью завершившаяся неделя Сб–Пт (по Ташкенту)."""
    today = datetime.now(TASHKENT_TZ).date()
    this_week_saturday = today - timedelta(days=(today.weekday() - 5) % 7)
    prev_saturday = this_week_saturday - timedelta(days=7)
    prev_friday = prev_saturday + timedelta(days=6)
    return prev_saturday, prev_friday


def tashkent_month_range_to_naive_utc(year: int, month: int) -> tuple[str, str]:
    """Границы календарного месяца (по Ташкенту), переведённые в наивный UTC —
    в том же формате, в котором пишутся метки времени в базе."""
    start_local_date = date(year, month, 1)
    end_local_date = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    start_local = datetime.combine(start_local_date, datetime.min.time(), tzinfo=TASHKENT_TZ)
    end_local = datetime.combine(end_local_date, datetime.min.time(), tzinfo=TASHKENT_TZ)
    start_utc = start_local.astimezone(UTC_TZ).replace(tzinfo=None)
    end_utc = end_local.astimezone(UTC_TZ).replace(tzinfo=None)
    return start_utc.isoformat(), end_utc.isoformat()


def previous_month_ym(today: date) -> tuple[int, int]:
    """(год, месяц) для месяца, который только что завершился."""
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROMOS_DIR = os.path.join(BASE_DIR, "promos")
PACKAGES_DIR = os.path.join(BASE_DIR, "packages")
HOOKAH_DIR = os.path.join(BASE_DIR, "hookah")

# буквы/цифры без похожих друг на друга символов (0/O, 1/I/L), чтобы код было легко читать вслух
CODE_ALPHABET = "0123456789"

BONUS_LABELS = {
    "welcome": "Бонус за подписку",
    "daytime": "Усиленный дневной бонус",
    "referrer": "Бонус за приглашённого друга",
    "reminder": "Бонус на возвращение",
    "checkin": "Отметка визита",
    "tier_silver": "Бонус за статус Серебряный",
    "tier_gold": "Бонус за статус Золотой",
    "tier_silver_monthly": "Ежемесячный бонус Серебро (план визитов выполнен)",
    "tier_gold_monthly": "Ежемесячный бонус Золото (план визитов выполнен)",
    "review_no_photo": "Отзыв без фото",
    "review_photo": "Отзыв с фото",
    "lottery_jackpot": "Джекпот в лототроне 🎰",
    "lottery_win": "Выигрыш в лототроне 🎰",
    "winback": "Бонус для постоянника (давно не был)",
}

REVIEW_POINTS_NO_PHOTO = os.environ.get("REVIEW_POINTS_NO_PHOTO", "15 000")
REVIEW_POINTS_PHOTO = os.environ.get("REVIEW_POINTS_PHOTO", "25 000")
LOTTERY_JACKPOT_POINTS = os.environ.get("LOTTERY_JACKPOT_POINTS", "50 000")
LOTTERY_WIN_POINTS = os.environ.get("LOTTERY_WIN_POINTS", "20 000")
WHEEL_MIN_TIER = os.environ.get("WHEEL_MIN_TIER", "silver")  # "silver" или "gold"
# суммарный шанс какого-либо приза (обычного + джекпота), в процентах.
# по умолчанию 70% гостей получают хоть что-то, 5% из них — джекпот.
WHEEL_WIN_PERCENT = float(os.environ.get("WHEEL_WIN_PERCENT", "65"))
WHEEL_JACKPOT_PERCENT = float(os.environ.get("WHEEL_JACKPOT_PERCENT", "5"))

# --- Удержание статуса: чтобы не потерять Серебро/Золото, нужно столько
# визитов в КАЖДОМ календарном месяце (проверяется автоматически 1-го числа) ---
TIER_SILVER_MAINTAIN_VISITS = int(os.environ.get("TIER_SILVER_MAINTAIN_VISITS", "8"))
TIER_GOLD_MAINTAIN_VISITS = int(os.environ.get("TIER_GOLD_MAINTAIN_VISITS", "15"))
# ежемесячный бонус-код при выполнении плана визитов
TIER_SILVER_MONTHLY_BONUS = os.environ.get("TIER_SILVER_MONTHLY_BONUS", "25 000")
TIER_GOLD_MONTHLY_BONUS = os.environ.get("TIER_GOLD_MONTHLY_BONUS", "50 000")
# постоянная скидка в CRM (клуб выставляет вручную — бот только напоминает)
TIER_SILVER_DISCOUNT_PERCENT = os.environ.get("TIER_SILVER_DISCOUNT_PERCENT", "5")
TIER_GOLD_DISCOUNT_PERCENT = os.environ.get("TIER_GOLD_DISCOUNT_PERCENT", "10")

# что администратор должен начислить гостю при погашении кода
# (checkin намеренно не включён - это просто счётчик визита, без начисления)
BONUS_AMOUNTS = {
    "welcome": f"{BONUS_AMOUNT_WELCOME} сум на баланс",
    "referrer": f"{BONUS_AMOUNT_REFERRER} сум на баланс",
    "reminder": f"+{os.environ.get('BONUS_PERCENT_REMINDER', '20')}% к пополнению",
    "tier_silver": f"включить скидку {TIER_SILVER_DISCOUNT_PERCENT}% в CRM (не баланс)",
    "tier_gold": f"включить скидку {TIER_GOLD_DISCOUNT_PERCENT}% в CRM (не баланс)",
    "tier_silver_monthly": f"{TIER_SILVER_MONTHLY_BONUS} сум на баланс",
    "tier_gold_monthly": f"{TIER_GOLD_MONTHLY_BONUS} сум на баланс",
    "winback": f"+{os.environ.get('BONUS_PERCENT_WINBACK', '25')}% к пополнению",
    "review_no_photo": f"{REVIEW_POINTS_NO_PHOTO} баллов на баланс",
    "review_photo": f"{REVIEW_POINTS_PHOTO} баллов на баланс",
    "lottery_jackpot": f"{LOTTERY_JACKPOT_POINTS} баллов на баланс",
    "lottery_win": f"{LOTTERY_WIN_POINTS} баллов на баланс",
}

TIER_SILVER_VISITS = int(os.environ.get("TIER_SILVER_VISITS", "10"))
# минимальная сумма пополнения (сум), при которой чек-ин засчитывается визитом —
# защита от абуза "зашёл на 5 минут, пополнил по минимуму, вышел"
MIN_CHECKIN_AMOUNT = int(os.environ.get("MIN_CHECKIN_AMOUNT", "50000"))
TIER_GOLD_VISITS = int(os.environ.get("TIER_GOLD_VISITS", "25"))

TIER_SILVER_TEXT = os.environ.get(
    "TIER_SILVER_TEXT",
    "🥈 Поздравляем, ты получил статус Серебряный гость!\n\n"
    f"Тебе доступна скидка {TIER_SILVER_DISCOUNT_PERCENT}% в клубе (кроме бара и ночных пакетов) — "
    "спроси на стойке, чтобы её включили.\n\n"
    f"Чтобы удержать статус и скидку, приходи от {TIER_SILVER_MAINTAIN_VISITS} раз в месяц — "
    f"тогда каждый месяц будешь получать ещё и бонус {TIER_SILVER_MONTHLY_BONUS} сум на баланс.",
)
TIER_GOLD_TEXT = os.environ.get(
    "TIER_GOLD_TEXT",
    "🥇 Поздравляем, ты получил статус Золотой гость!\n\n"
    f"Тебе доступна скидка {TIER_GOLD_DISCOUNT_PERCENT}% в клубе (кроме бара и ночных пакетов) — "
    "спроси на стойке, чтобы её включили.\n"
    "Плюс приоритет на бронирование любимого места.\n\n"
    f"Чтобы удержать статус и скидку, приходи от {TIER_GOLD_MAINTAIN_VISITS} раз в месяц — "
    f"тогда каждый месяц будешь получать ещё и бонус {TIER_GOLD_MONTHLY_BONUS} сум на баланс.",
)
TIER_LABELS = {"": "Без статуса", "silver": "🥈 Серебряный", "gold": "🥇 Золотой"}

GAME_NAMES = {
    "valorant": "Valorant",
    "cs2": "CS2",
    "dota": "Dota 2",
    "pubg": "PUBG",
}

# Тема статусов под игру. Уровни те же (silver/gold), просто другие названия —
# логика статусов (визиты, бонусы) не меняется, меняется только как это называется.
GAME_TIER_LABELS = {
    "valorant": {"silver": "💠 Platinum", "gold": "🔴 Immortal"},
    "cs2": {"silver": "🦅 Legendary Eagle", "gold": "🌍 Global Elite"},
    "dota": {"silver": "🌌 Ancient", "gold": "♾️ Immortal"},
    "pubg": {"silver": "💎 Diamond", "gold": "👑 Conqueror"},
}


def db_get_favorite_game(telegram_id: int) -> str:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT favorite_game FROM subscribers WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()
    return row[0] if row and row[0] else ""


def db_set_favorite_game(telegram_id: int, game: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE subscribers SET favorite_game = ? WHERE telegram_id = ?", (game, telegram_id))
    conn.commit()
    conn.close()


def tier_label_for_user(user_id: int, tier: str) -> str:
    if not tier:
        return TIER_LABELS[""]
    game = db_get_favorite_game(user_id)
    if game in GAME_TIER_LABELS:
        return GAME_TIER_LABELS[game][tier]
    return TIER_LABELS.get(tier, tier)

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

WINBACK_DELAY_DAYS = int(os.environ.get("WINBACK_DELAY_DAYS", "30"))
WINBACK_MIN_VISITS = int(os.environ.get("WINBACK_MIN_VISITS", "2"))
WINBACK_TEXT = os.environ.get(
    "WINBACK_TEXT",
    "Давно не виделись! 👋\n\n"
    "Мы соскучились — держи бонус специально для постоянных гостей: "
    "+25% к следующему пополнению баланса.\n"
    "Покажи это сообщение администратору на стойке в течение 7 дней.",
)
WHEEL_NUDGE_TEXT = os.environ.get(
    "WHEEL_NUDGE_TEXT",
    "🎡 Сегодня у тебя есть бесплатный спин колеса фортуны!\n"
    "Не забудь прокрутить — вдруг именно сегодня повезёт 🍀",
)
WHEEL_TRIAL_TEXT = os.environ.get(
    "WHEEL_TRIAL_TEXT",
    "🎁 Специально для тебя открыли Колесо Фортуны — держи один бесплатный спин!\n"
    "Кнопка появилась в меню, попробуй прямо сейчас 👇",
)
BACKUP_INTERVAL_DAYS = int(os.environ.get("BACKUP_INTERVAL_DAYS", "7"))
WEBAPP_URL = os.environ.get("WEBAPP_URL", "").strip()

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# временное хранилище "кто по чьей ссылке идёт регистрироваться"
# (живёт только пока бот не перезапущен - этого достаточно для короткого пути /start -> контакт)
PENDING_REFERRALS: dict[int, int] = {}

WHEEL_BUTTON = KeyboardButton(text="🎡 Колесо Фортуны")
WHEEL_BUTTON_LOCKED = KeyboardButton(text="🔒 Колесо Фортуны")


ADMIN_BUTTON_CODE = "🔑 Ввести код"
ADMIN_BUTTON_FIND = "🔍 Поиск гостя"
ADMIN_BUTTON_RESET_REVIEW = "♻️ Снять блокировку отзыва"
OWNER_BUTTON_CODES_PERIOD = "📅 Коды за период"
OWNER_BUTTON_GUESTS_PERIOD = "📅 Новые гости за период"
OWNER_BUTTON_MORE = "⚙️ Ещё"


def guest_menu_rows(user_id: int) -> list[list[KeyboardButton]]:
    rows = [
        [KeyboardButton(text="🎉 Акции"), KeyboardButton(text="📍 Клуб")],
        [KeyboardButton(text="👥 Пригласить друга"), KeyboardButton(text="🧾 Прайс")],
        [KeyboardButton(text="✅ Я в клубе"), KeyboardButton(text="💎 Мой статус")],
    ]
    tier = db_get_tier(user_id)
    if TIER_RANK.get(tier, 0) >= WHEEL_MIN_TIER_RANK or db_has_trial_spin(user_id):
        rows.append([WHEEL_BUTTON])
    else:
        rows.append([WHEEL_BUTTON_LOCKED])
    return rows


def admin_menu_rows() -> list[list[KeyboardButton]]:
    return [
        [KeyboardButton(text=ADMIN_BUTTON_CODE), KeyboardButton(text=ADMIN_BUTTON_FIND)],
        [KeyboardButton(text=ADMIN_BUTTON_RESET_REVIEW)],
    ]


def owner_menu_rows() -> list[list[KeyboardButton]]:
    return [
        [KeyboardButton(text=OWNER_BUTTON_CODES_PERIOD), KeyboardButton(text=OWNER_BUTTON_GUESTS_PERIOD)],
        [KeyboardButton(text=OWNER_BUTTON_MORE)],
    ]


def main_menu_kb(user_id: int) -> ReplyKeyboardMarkup:
    """Собирает главное меню под конкретного пользователя.

    - Обычный гость: только гостевые функции (Колесо Фортуны — только с нужного статуса).
    - Админ (ADMIN_IDS): только рабочие функции учёта — код, поиск гостя, снятие
      блокировки отзыва. Акции/статусы/колесо им для работы не нужны.
    - Владелец (OWNER_ID): всё сразу — и гостевые, и админские функции в одном меню.
    """
    if is_owner(user_id):
        rows = admin_menu_rows() + owner_menu_rows() + guest_menu_rows(user_id)
    elif is_admin(user_id):
        rows = admin_menu_rows()
    else:
        rows = guest_menu_rows(user_id)
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


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
    # WAL вместо дефолтного rollback-journal — позволяет читать базу, пока кто-то
    # другой пишет (важно при одновременных спинах/чек-инах/рассылке на много гостей).
    # Настройка сохраняется в самом файле базы, достаточно выставить один раз.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            visited_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS guest_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            kind TEXT,
            rating TEXT,
            comment TEXT,
            photo_file_id TEXT,
            created_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_guest_feedback_created ON guest_feedback(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_visits_telegram_id ON visits(telegram_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_subscribers_tier ON subscribers(tier)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_subscribers_winback_sent ON subscribers(winback_sent)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_subscribers_reminder_sent ON subscribers(reminder_sent)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT
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
        ("last_checkin_at", "TEXT"),
        ("winback_sent", "INTEGER DEFAULT 0"),
        ("trial_spin_available", "INTEGER DEFAULT 0"),
        ("referrer_bonus_paid", "INTEGER DEFAULT 0"),
        ("favorite_game", "TEXT DEFAULT ''"),
        ("tier_since", "TEXT"),
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


def db_peek_bonus(code: str) -> dict | None:
    """Смотрит на код бонуса, не помечая его использованным."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM bonuses WHERE code = ?", (code,)).fetchone()
    conn.close()
    return dict(row) if row else None


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


def db_log_visit(telegram_id: int) -> None:
    """Пишет визит с датой — нужно для проверки 'N визитов в месяц' на удержание статуса."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO visits (telegram_id, visited_at) VALUES (?, ?)",
        (telegram_id, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def db_log_feedback(
    telegram_id: int,
    kind: str,
    rating: str | None = None,
    comment: str | None = None,
    photo_file_id: str | None = None,
) -> None:
    """kind: 'review_photo' / 'review_no_photo' (отзыв за бонус) или 'rating' (оценка визита)."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO guest_feedback (telegram_id, kind, rating, comment, photo_file_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (telegram_id, kind, rating, comment, photo_file_id, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def db_list_recent_feedback(limit: int = 15, kinds: tuple[str, ...] | None = None) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    where = ""
    params: list = []
    if kinds:
        where = f"WHERE g.kind IN ({','.join('?' for _ in kinds)})"
        params.extend(kinds)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT g.id, g.telegram_id, g.kind, g.rating, g.comment, g.photo_file_id, g.created_at,
               s.full_name, s.phone
        FROM guest_feedback g
        LEFT JOIN subscribers s ON s.telegram_id = g.telegram_id
        {where}
        ORDER BY g.created_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def db_export_all_feedback(kinds: tuple[str, ...] | None = None) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    where = ""
    params: list = []
    if kinds:
        where = f"WHERE g.kind IN ({','.join('?' for _ in kinds)})"
        params.extend(kinds)
    rows = conn.execute(
        f"""
        SELECT g.telegram_id, g.kind, g.rating, g.comment, g.created_at,
               s.full_name, s.phone
        FROM guest_feedback g
        LEFT JOIN subscribers s ON s.telegram_id = g.telegram_id
        {where}
        ORDER BY g.created_at DESC
        """,
        params,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def db_count_visits_in_range(telegram_id: int, start_iso: str, end_iso: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT COUNT(*) FROM visits WHERE telegram_id = ? AND visited_at >= ? AND visited_at < ?",
        (telegram_id, start_iso, end_iso),
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def db_retention_candidates(start_iso: str, end_iso: str) -> list[dict]:
    """Серебро/Золото + число визитов за проверяемый месяц — одним запросом
    с группировкой, вместо отдельного запроса на каждого гостя."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT s.telegram_id, s.tier, s.tier_since,
               COUNT(v.id) AS visits_in_period
        FROM subscribers s
        LEFT JOIN visits v
            ON v.telegram_id = s.telegram_id AND v.visited_at >= ? AND v.visited_at < ?
        WHERE s.tier IN ('silver', 'gold')
        GROUP BY s.telegram_id
        """,
        (start_iso, end_iso),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def db_set_tier(telegram_id: int, tier: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    if tier in ("silver", "gold"):
        conn.execute(
            "UPDATE subscribers SET tier = ?, tier_since = ? WHERE telegram_id = ?",
            (tier, datetime.now().isoformat(), telegram_id),
        )
    else:
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


def db_wheel_nudge_targets() -> list[int]:
    """Гости с доступом к колесу (см. WHEEL_MIN_TIER), кто ещё не крутил сегодня."""
    eligible_tiers = [t for t, r in TIER_RANK.items() if t and r >= WHEEL_MIN_TIER_RANK]
    if not eligible_tiers:
        return []
    today = datetime.now(TASHKENT_TZ).date().isoformat()
    placeholders = ",".join("?" for _ in eligible_tiers)
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        f"SELECT telegram_id FROM subscribers WHERE tier IN ({placeholders}) "
        "AND (last_spin_date IS NULL OR last_spin_date != ?)",
        (*eligible_tiers, today),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


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


def db_trial_spin_targets() -> list[int]:
    """Гости БЕЗ доступа к колесу (см. WHEEL_MIN_TIER), кому ещё не выдавали пробный спин."""
    eligible_tiers = [t for t, r in TIER_RANK.items() if t and r >= WHEEL_MIN_TIER_RANK]
    conn = sqlite3.connect(DB_PATH)
    if eligible_tiers:
        placeholders = ",".join("?" for _ in eligible_tiers)
        rows = conn.execute(
            f"SELECT telegram_id FROM subscribers "
            f"WHERE tier NOT IN ({placeholders}) AND trial_spin_available = 0",
            eligible_tiers,
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT telegram_id FROM subscribers WHERE trial_spin_available = 0"
        ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def db_grant_trial_spin(telegram_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE subscribers SET trial_spin_available = 1 WHERE telegram_id = ?", (telegram_id,))
    conn.commit()
    conn.close()


def db_has_trial_spin(telegram_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT trial_spin_available FROM subscribers WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()
    return bool(row and row[0])


def db_consume_trial_spin(telegram_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE subscribers SET trial_spin_available = 0 WHERE telegram_id = ?", (telegram_id,))
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


def db_set_last_checkin(telegram_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE subscribers SET last_checkin_at = ?, winback_sent = 0 WHERE telegram_id = ?",
        (datetime.now().isoformat(), telegram_id),
    )
    conn.commit()
    conn.close()


def db_due_for_winback(delay_days: int, min_visits: int) -> list[int]:
    cutoff = (datetime.now() - timedelta(days=delay_days)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT telegram_id FROM subscribers "
        "WHERE winback_sent = 0 AND visits_confirmed >= ? "
        "AND last_checkin_at IS NOT NULL AND last_checkin_at <= ?",
        (min_visits, cutoff),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def db_mark_winback_sent(telegram_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE subscribers SET winback_sent = 1 WHERE telegram_id = ?", (telegram_id,))
    conn.commit()
    conn.close()


def db_segment_ids(segment: str) -> list[int]:
    conn = sqlite3.connect(DB_PATH)
    if segment == "gold":
        rows = conn.execute("SELECT telegram_id FROM subscribers WHERE tier = 'gold'").fetchall()
    elif segment == "silver":
        rows = conn.execute("SELECT telegram_id FROM subscribers WHERE tier = 'silver'").fetchall()
    elif segment == "new":
        cutoff = (datetime.now() - timedelta(days=7)).isoformat()
        rows = conn.execute("SELECT telegram_id FROM subscribers WHERE joined_at >= ?", (cutoff,)).fetchall()
    elif segment == "referred":
        rows = conn.execute("SELECT telegram_id FROM subscribers WHERE referred_by IS NOT NULL").fetchall()
    else:
        rows = conn.execute("SELECT telegram_id FROM subscribers").fetchall()
    conn.close()
    return [r[0] for r in rows]


def db_stats_extended() -> dict:
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0]
    today_cutoff = datetime.now(TASHKENT_TZ).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week_cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    new_today = conn.execute("SELECT COUNT(*) FROM subscribers WHERE joined_at >= ?", (today_cutoff,)).fetchone()[0]
    new_week = conn.execute("SELECT COUNT(*) FROM subscribers WHERE joined_at >= ?", (week_cutoff,)).fetchone()[0]
    gold = conn.execute("SELECT COUNT(*) FROM subscribers WHERE tier = 'gold'").fetchone()[0]
    silver = conn.execute("SELECT COUNT(*) FROM subscribers WHERE tier = 'silver'").fetchone()[0]
    referred = conn.execute("SELECT COUNT(*) FROM subscribers WHERE referred_by IS NOT NULL").fetchone()[0]
    bonuses_redeemed = conn.execute("SELECT COUNT(*) FROM bonuses WHERE used_at IS NOT NULL").fetchone()[0]
    conn.close()
    return {
        "total": total,
        "new_today": new_today,
        "new_week": new_week,
        "gold": gold,
        "silver": silver,
        "no_status": total - gold - silver,
        "referred": referred,
        "bonuses_redeemed": bonuses_redeemed,
    }


def db_get_setting(key: str) -> str | None:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT value FROM bot_settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row[0] if row else None


def db_set_setting(key: str, value: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO bot_settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def db_export_all(date_from_iso: str | None = None, date_to_iso: str | None = None) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    query = (
        "SELECT telegram_id, username, full_name, phone, joined_at, referred_by, "
        "visits_confirmed, tier, review_bonus_claimed FROM subscribers"
    )
    params: list[str] = []
    if date_from_iso and date_to_iso:
        query += " WHERE joined_at >= ? AND joined_at < ?"
        params = [date_from_iso, date_to_iso]
    query += " ORDER BY joined_at"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def db_export_all_bonuses(date_from_iso: str | None = None, date_to_iso: str | None = None) -> list[dict]:
    """Без периода — все коды. С периодом — коды, ПОГАШЕННЫЕ в этот период
    (сравниваем именно с датой погашения, т.к. отчёт нужен для сверки с CRM,
    где запись делается в момент погашения кода, а не создания)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    query = """
        SELECT
            b.code, b.bonus_type, b.created_at, b.used_at, b.used_by_admin,
            s.telegram_id, s.full_name, s.phone
        FROM bonuses b
        LEFT JOIN subscribers s ON s.telegram_id = b.telegram_id
    """
    params: list[str] = []
    if date_from_iso and date_to_iso:
        query += " WHERE b.used_at >= ? AND b.used_at < ?"
        params = [date_from_iso, date_to_iso]
    query += " ORDER BY b.created_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def db_find_by_phone(query: str) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT telegram_id, username, full_name, phone, joined_at, referred_by, "
        "visits_confirmed, tier FROM subscribers "
        "WHERE phone LIKE ? OR CAST(telegram_id AS TEXT) LIKE ? "
        "ORDER BY joined_at DESC",
        (f"%{query}%", f"%{query}%"),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def db_get_subscriber_by_id(telegram_id: int) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT telegram_id, username, full_name, phone, joined_at, referred_by, "
        "visits_confirmed, tier FROM subscribers WHERE telegram_id = ?",
        (telegram_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def resolve_guest(identifier: str) -> tuple[dict | None, list[dict]]:
    """Ищет гостя по точному telegram_id или по (части) номера телефона.

    Возвращает (гость, []) при однозначном совпадении,
    либо (None, список_совпадений) если нашлось 0 или несколько.
    """
    identifier = identifier.strip()
    digits = "".join(ch for ch in identifier if ch.isdigit())
    if digits:
        target = db_get_subscriber_by_id(int(digits))
        if target:
            return target, []
    matches = db_find_by_phone(digits or identifier)
    if len(matches) == 1:
        return matches[0], []
    return None, matches


# ---------- СОСТОЯНИЯ ----------
class BroadcastState(StatesGroup):
    waiting_segment = State()
    waiting_text = State()
    waiting_confirm = State()


BROADCAST_SEGMENT_KB = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="👥 Все подписчики", callback_data="bcseg_all")],
        [InlineKeyboardButton(text="🥇 Только золотые", callback_data="bcseg_gold")],
        [InlineKeyboardButton(text="🥈 Только серебряные", callback_data="bcseg_silver")],
        [InlineKeyboardButton(text="🆕 Новые за неделю", callback_data="bcseg_new")],
        [InlineKeyboardButton(text="🔗 Пришли по рефералке", callback_data="bcseg_referred")],
    ]
)

SEGMENT_LABELS = {
    "all": "Все подписчики",
    "gold": "Золотые",
    "silver": "Серебряные",
    "new": "Новые за неделю",
    "referred": "Пришли по рефералке",
}


class ReviewState(StatesGroup):
    waiting_screenshot = State()


class WipeAllState(StatesGroup):
    waiting_confirm = State()


WIPE_CONFIRM_PHRASE = "УДАЛИТЬ ВСЕХ"


class WinbackNowState(StatesGroup):
    waiting_confirm = State()


class WheelNudgeState(StatesGroup):
    waiting_confirm = State()


class WheelTrialGrantState(StatesGroup):
    waiting_confirm = State()


class AdminFlow(StatesGroup):
    waiting_code = State()
    waiting_find = State()
    waiting_reset_review = State()


class FeedbackDetail(StatesGroup):
    waiting_text = State()


class PeriodExportState(StatesGroup):
    waiting_range = State()


# ---------- ВСПОМОГАТЕЛЬНОЕ ----------
def get_bonus_text_and_type() -> tuple[str, str]:
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
        await message.answer("Ты уже с нами! 🎮 Вот меню:", reply_markup=main_menu_kb(user_id))
        return

    if is_admin(user_id) and not is_owner(user_id):
        await message.answer(
            "Привет! Это рабочий доступ Colizeum Bot 🛠\nВводи коды гостей, ищи гостей, снимай блокировки отзывов.",
            reply_markup=main_menu_kb(user_id),
        )
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

    await message.answer(bonus_text)

    await message.answer(
        "📊 Как работают статусы в Colizeum\n\n"
        f"Каждый визит засчитывается, когда пополняешь баланс от {MIN_CHECKIN_AMOUNT} сум "
        "и показываешь код администратору (кнопка «✅ Я в клубе»).\n\n"
        f"🥈 {TIER_SILVER_VISITS} визитов — статус выше, бонус на баланс, доступ к Колесу Фортуны "
        f"и скидка {TIER_SILVER_DISCOUNT_PERCENT}% в клубе (кроме бара и ночных пакетов)\n"
        f"🥇 {TIER_GOLD_VISITS} визитов — максимальный статус, бонус ещё больше, "
        f"скидка {TIER_GOLD_DISCOUNT_PERCENT}%\n\n"
        f"Чтобы удержать статус и скидку — заходи минимум {TIER_SILVER_MAINTAIN_VISITS} раз "
        f"в месяц на Серебре или {TIER_GOLD_MAINTAIN_VISITS} раз в месяц на Золоте.\n\n"
        "Назвать твои статусы можем в теме твоей любимой игры 🎮"
    )
    await message.answer("В какую игру играешь чаще всего?", reply_markup=game_choice_kb())


def game_choice_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=name, callback_data=f"game:{key}")]
        for key, name in GAME_NAMES.items()
    ]
    rows.append([InlineKeyboardButton(text="Пропустить", callback_data="game:none")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("game:"))
async def cb_choose_game(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    game = callback.data.split(":", 1)[1]
    if game == "none":
        db_set_favorite_game(user_id, "")
        await callback.message.edit_text("Хорошо, оставим стандартные названия статусов 🙂")
    else:
        db_set_favorite_game(user_id, game)
        preview_silver = GAME_TIER_LABELS[game]["silver"]
        preview_gold = GAME_TIER_LABELS[game]["gold"]
        await callback.message.edit_text(
            f"Готово! Теперь твои статусы: {preview_silver} → {preview_gold} 🎮"
        )
    await callback.answer()
    await bot.send_message(user_id, "Вот твоё меню 👇", reply_markup=main_menu_kb(user_id))


@router.message(Command("stop"))
async def cmd_stop(message: Message) -> None:
    db_remove_subscriber(message.from_user.id)
    await message.answer(
        "Ты отписан(а) от рассылки. Если захочешь вернуться — просто нажми /start.",
        reply_markup=ReplyKeyboardRemove(),
    )


# ---------- МЕНЮ ----------


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

    visits = db_get_visits(user_id)
    if visits < 1:
        await message.answer(
            "Приглашать друзей можно после первого визита в клуб 🙂\n"
            "Покажи код из «✅ Я в клубе» администратору — и ссылка откроется."
        )
        return

    link = get_referral_link(user_id)
    count = db_referral_count(user_id)
    await message.answer(
        "Приглашай друзей и получай бонус за каждого! 🙌\n\n"
        f"Твоя ссылка:\n{link}\n\n"
        f"Приглашено друзей: {count}\n\n"
        "Когда друг перейдёт по ссылке и зарегистрируется — он получит свой бонус.\n"
        "Твой бонус придёт, когда друг придёт в клуб первый раз и подтвердит визит."
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
        f"Визит засчитывается при пополнении баланса от {MIN_CHECKIN_AMOUNT} сум.\n"
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
    tier_label = tier_label_for_user(user_id, tier)

    if tier == "gold":
        progress = "Ты уже на максимальном статусе — так держать! 🏆"
    elif tier == "silver":
        left = max(TIER_GOLD_VISITS - visits, 0)
        progress = f"До статуса {tier_label_for_user(user_id, 'gold')} осталось визитов: {left}"
    else:
        left = max(TIER_SILVER_VISITS - visits, 0)
        progress = f"До статуса {tier_label_for_user(user_id, 'silver')} осталось визитов: {left}"

    retention_line = ""
    if tier in ("silver", "gold"):
        today = datetime.now(TASHKENT_TZ).date()
        month_start_iso, _ = tashkent_month_range_to_naive_utc(today.year, today.month)
        now_iso = datetime.now().isoformat()
        visits_this_month = db_count_visits_in_range(user_id, month_start_iso, now_iso)
        required = TIER_GOLD_MAINTAIN_VISITS if tier == "gold" else TIER_SILVER_MAINTAIN_VISITS
        discount = TIER_GOLD_DISCOUNT_PERCENT if tier == "gold" else TIER_SILVER_DISCOUNT_PERCENT
        retention_line = (
            f"\n\n📅 Визитов в этом месяце: {visits_this_month} из {required} — "
            f"нужно, чтобы удержать статус и скидку {discount}%."
        )

    await message.answer(
        f"💎 Твой статус: {tier_label}\n"
        f"Подтверждённых визитов: {visits}\n\n"
        f"{progress}{retention_line}\n\n"
        "Визит засчитывается, когда администратор гасит твой код из кнопки «✅ Я в клубе»."
    )


@router.message(F.text.in_({"🎡 Колесо Фортуны", "🔒 Колесо Фортуны"}))
async def menu_wheel(message: Message) -> None:
    user_id = message.from_user.id
    elig = wheel_eligibility(user_id)
    if not elig["eligible"]:
        left = max(elig["visits_needed"] - elig["visits"], 0)
        required_label = tier_label_for_user(user_id, WHEEL_MIN_TIER)
        await message.answer(
            f"Колесо фортуны открывается со статуса {required_label}.\n"
            f"Визитов: {elig['visits']} из {elig['visits_needed']} — осталось {left} 🙂",
            reply_markup=main_menu_kb(user_id),
        )
        return

    if not WEBAPP_URL:
        await message.answer(
            "Колесо фортуны скоро заработает — администратор ещё настраивает эту функцию 🎡"
        )
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎡 Открыть колесо",
                    web_app=WebAppInfo(url=f"{WEBAPP_URL.rstrip('/')}/wheel"),
                )
            ]
        ]
    )
    await message.answer("Крути колесо раз в день и лови бонус! 🎰", reply_markup=kb)


# ---------- ОБРАБОТЧИКИ: АДМИН ----------
def is_admin(telegram_id: int) -> bool:
    return telegram_id in ADMIN_IDS


def is_owner(telegram_id: int) -> bool:
    return OWNER_ID != 0 and telegram_id == OWNER_ID


@router.message(F.text == ADMIN_BUTTON_CODE)
async def admin_btn_code(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminFlow.waiting_code)
    await message.answer("Пришли код гостя (например 482917):")


_ESCAPE_MENU_TEXTS = {
    ADMIN_BUTTON_CODE, ADMIN_BUTTON_FIND, ADMIN_BUTTON_RESET_REVIEW,
    OWNER_BUTTON_CODES_PERIOD, OWNER_BUTTON_GUESTS_PERIOD, OWNER_BUTTON_MORE,
    "🎉 Акции", "📍 Клуб", "👥 Пригласить друга", "🧾 Прайс",
    "✅ Я в клубе", "💎 Мой статус", WHEEL_BUTTON.text, WHEEL_BUTTON_LOCKED.text,
}


async def try_menu_escape(message: Message, state: FSMContext) -> bool:
    """Если во время ожидания ввода (код/поиск/дата и т.п.) человек передумал
    и нажал другую кнопку меню или отправил команду — не пытаемся скормить
    это как ответ на предыдущий вопрос, а мягко выходим из состояния.
    Возвращает True, если сообщение было "запросом на выход", а не данными.
    """
    text = (message.text or "").strip()
    if not text:
        return False
    if text.startswith("/"):
        await state.clear()
        await message.answer("Хорошо, отменил ожидание — отправь команду ещё раз 🙂")
        return True
    if text in _ESCAPE_MENU_TEXTS:
        await state.clear()
        await message.answer("Окей, отменил предыдущее действие — нажми нужную кнопку ещё раз 🙂")
        return True
    return False


@router.message(AdminFlow.waiting_code)
async def admin_flow_code(message: Message, state: FSMContext) -> None:
    if await try_menu_escape(message, state):
        return
    await state.clear()
    await do_redeem(message, (message.text or "").strip())


@router.message(F.text == ADMIN_BUTTON_FIND)
async def admin_btn_find(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminFlow.waiting_find)
    await message.answer("Пришли номер телефона или Telegram ID гостя (можно частично):")


@router.message(AdminFlow.waiting_find)
async def admin_flow_find(message: Message, state: FSMContext) -> None:
    if await try_menu_escape(message, state):
        return
    await state.clear()
    await do_find(message, (message.text or "").strip())


@router.message(F.text == ADMIN_BUTTON_RESET_REVIEW)
async def admin_btn_reset_review(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminFlow.waiting_reset_review)
    await message.answer("Пришли Telegram ID гостя, которому снять блокировку отзыва:")


@router.message(AdminFlow.waiting_reset_review)
async def admin_flow_reset_review(message: Message, state: FSMContext) -> None:
    if await try_menu_escape(message, state):
        return
    await state.clear()
    await do_reset_review(message, (message.text or "").strip())


def period_picker_kb(kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📆 Прошлая неделя (Сб–Пт)", callback_data=f"prd:{kind}:lastweek")],
            [InlineKeyboardButton(text="📆 Последние 7 дней", callback_data=f"prd:{kind}:7d")],
            [InlineKeyboardButton(text="✏️ Свой период", callback_data=f"prd:{kind}:custom")],
        ]
    )


async def send_period_export(message: Message, kind: str, date_from: date, date_to: date) -> None:
    start_iso, end_iso = tashkent_day_range_to_naive_utc(date_from, date_to)
    period_label = f"{date_from.strftime('%d.%m.%Y')}–{date_to.strftime('%d.%m.%Y')}"

    if kind == "codes":
        csv_bytes, count = build_bonuses_csv(start_iso, end_iso)
        noun = "погашенных кодов"
        prefix = "colizeum_codes"
    else:
        csv_bytes, count = build_subscribers_csv(start_iso, end_iso)
        noun = "новых гостей"
        prefix = "colizeum_new_guests"

    if count == 0:
        await message.answer(f"За период {period_label} — {noun}: 0. Файл не создаю.")
        return

    filename = f"{prefix}_{date_from.isoformat()}_{date_to.isoformat()}.csv"
    await message.answer_document(
        BufferedInputFile(csv_bytes, filename=filename),
        caption=f"{period_label}: {count} ({noun}).",
    )


@router.message(F.text == OWNER_BUTTON_CODES_PERIOD)
async def owner_btn_codes_period(message: Message) -> None:
    if not is_owner(message.from_user.id):
        return
    await message.answer("За какой период выгрузить погашенные коды?", reply_markup=period_picker_kb("codes"))


@router.message(F.text == OWNER_BUTTON_GUESTS_PERIOD)
async def owner_btn_guests_period(message: Message) -> None:
    if not is_owner(message.from_user.id):
        return
    await message.answer(
        "За какой период выгрузить новых зарегистрированных гостей?", reply_markup=period_picker_kb("guests")
    )


@router.callback_query(F.data.startswith("prd:"))
async def cb_period_pick(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_owner(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return

    _, kind, preset = callback.data.split(":", 2)

    if preset == "custom":
        await state.update_data(period_kind=kind)
        await state.set_state(PeriodExportState.waiting_range)
        await callback.message.edit_text(
            "Пришли период в формате ДД.ММ.ГГГГ-ДД.ММ.ГГГГ\nНапример: 01.07.2026-08.07.2026"
        )
        await callback.answer()
        return

    if preset == "lastweek":
        date_from, date_to = last_full_week_sat_fri()
    else:  # "7d"
        today = datetime.now(TASHKENT_TZ).date()
        date_from, date_to = today - timedelta(days=6), today

    await callback.answer("Собираю файл...")
    await send_period_export(callback.message, kind, date_from, date_to)


@router.message(PeriodExportState.waiting_range)
async def period_export_custom_range(message: Message, state: FSMContext) -> None:
    if await try_menu_escape(message, state):
        return
    data = await state.get_data()
    kind = data.get("period_kind", "codes")
    await state.clear()

    text = (message.text or "").strip().replace(" ", "")
    parts = text.split("-")
    if len(parts) != 2:
        await message.answer("Не понял формат. Пример: 01.07.2026-08.07.2026")
        return
    try:
        date_from = datetime.strptime(parts[0], "%d.%m.%Y").date()
        date_to = datetime.strptime(parts[1], "%d.%m.%Y").date()
    except ValueError:
        await message.answer("Не понял даты. Пример: 01.07.2026-08.07.2026")
        return
    if date_from > date_to:
        date_from, date_to = date_to, date_from

    await send_period_export(message, kind, date_from, date_to)


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    s = db_stats_extended()
    await message.answer(
        "📊 Статистика клуба\n\n"
        f"Всего подписчиков: {s['total']}\n"
        f"Новых сегодня: {s['new_today']}\n"
        f"Новых за неделю: {s['new_week']}\n\n"
        f"🥇 Золотых: {s['gold']}\n"
        f"🥈 Серебряных: {s['silver']}\n"
        f"Без статуса: {s['no_status']}\n\n"
        f"👥 Пришли по рефералке: {s['referred']}\n"
        f"🔑 Бонусов погашено всего: {s['bonuses_redeemed']}"
    )


async def pay_referrer_bonus_if_due(guest_id: int) -> None:
    """Начисляет бонус пригласившему — но только на ПЕРВЫЙ реальный визит приглашённого
    друга (не на регистрацию), и только один раз. Так рефералку нельзя фармить
    фейковыми аккаунтами, которые просто регистрируются и никогда не приходят."""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT referred_by, referrer_bonus_paid FROM subscribers WHERE telegram_id = ?", (guest_id,)
    ).fetchone()
    conn.close()

    if not row or not row[0] or row[1]:
        return  # нет пригласившего, либо уже выплачено раньше

    referrer_id = row[0]
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE subscribers SET referrer_bonus_paid = 1 WHERE telegram_id = ?", (guest_id,)
    )
    conn.commit()
    conn.close()

    try:
        referrer_code = db_create_bonus(referrer_id, "referrer")
        await bot.send_message(
            referrer_id,
            f"{REFERRER_BONUS_TEXT}\n\n🔑 Код бонуса: {referrer_code}",
        )
    except Exception:
        logging.warning("не удалось уведомить пригласившего %s", referrer_id)


async def apply_confirmed_checkin(guest_id: int) -> str:
    """Засчитывает визит гостю (визиты/статус/уведомления).

    Вызывается только после того, как админ подтвердил визит кнопкой
    и сумма пополнения оказалась не меньше MIN_CHECKIN_AMOUNT.
    Возвращает текст-дополнение для итогового сообщения администратору.
    """
    visits = db_increment_visits(guest_id)
    db_log_visit(guest_id)
    db_set_last_checkin(guest_id)
    if visits == 1:
        db_set_first_checkin(guest_id)
        await pay_referrer_bonus_if_due(guest_id)
    current_tier = db_get_tier(guest_id)
    new_tier = None
    if visits >= TIER_GOLD_VISITS and current_tier != "gold":
        new_tier = "gold"
    elif visits >= TIER_SILVER_VISITS and current_tier not in ("silver", "gold"):
        new_tier = "silver"

    extra = f"\nВизитов у гостя: {visits}"

    if new_tier:
        db_set_tier(guest_id, new_tier)
        tier_text = TIER_GOLD_TEXT if new_tier == "gold" else TIER_SILVER_TEXT
        themed_label = tier_label_for_user(guest_id, new_tier)
        if db_get_favorite_game(guest_id):
            tier_text = f"Новый ранг: {themed_label} 🎮\n\n{tier_text}"
        tier_code = db_create_bonus(guest_id, f"tier_{new_tier}")
        try:
            await bot.send_message(
                guest_id,
                f"{tier_text}\n\n🔑 Код бонуса: {tier_code}",
                reply_markup=main_menu_kb(guest_id),
            )
        except Exception:
            logging.warning("не удалось уведомить гостя %s о новом статусе", guest_id)
        extra += f"\n🎉 Гость получил новый статус: {TIER_LABELS.get(new_tier, new_tier)}!"

        conn = sqlite3.connect(DB_PATH)
        phone_row = conn.execute(
            "SELECT phone, full_name FROM subscribers WHERE telegram_id = ?", (guest_id,)
        ).fetchone()
        conn.close()
        phone = phone_row[0] if phone_row else "неизвестен"
        name = phone_row[1] if phone_row else ""
        discount_pct = TIER_GOLD_DISCOUNT_PERCENT if new_tier == "gold" else TIER_SILVER_DISCOUNT_PERCENT
        tier_word = "Золотой" if new_tier == "gold" else "Серебряный"
        emoji = "🥇" if new_tier == "gold" else "🥈"
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"{emoji} Новый {tier_word} гость!\n\n"
                    f"Имя: {name}\nТелефон: {phone}\n\n"
                    f"Не забудьте вручную проставить постоянную скидку {discount_pct}% в CRM клуба "
                    "(бот не имеет доступа к CRM и не может сделать это сам).",
                )
            except Exception:
                logging.warning("не удалось уведомить админа %s", admin_id)

    return extra


async def do_redeem(message: Message, code: str) -> None:
    code = code.strip().upper()
    if not code:
        await message.answer("Пришли код гостя (например 482917).")
        return

    row = db_peek_bonus(code)

    if row is None:
        await message.answer("❌ Код не найден. Проверьте, правильно ли он введён.")
        return

    if row["used_at"]:
        used_at = row["used_at"][:16].replace("T", " ")
        label = BONUS_LABELS.get(row["bonus_type"], row["bonus_type"])
        amount = BONUS_AMOUNTS.get(row["bonus_type"])
        amount_line = f"\nБонус: {amount}" if amount else ""
        await message.answer(f"⚠️ Этот код уже был погашен {used_at}.\nТип бонуса: {label}{amount_line}")
        return

    if row["bonus_type"] in ("checkin", "welcome"):
        guest = db_get_subscriber_by_id(row["telegram_id"])
        guest_name = guest["full_name"] if guest else "без имени"
        min_amount = MIN_CHECKIN_AMOUNT if row["bonus_type"] == "checkin" else MIN_WELCOME_AMOUNT
        purpose = "визит" if row["bonus_type"] == "checkin" else "бонус за подписку"

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"ckc:{code}"),
                    InlineKeyboardButton(text="❌ Отклонить", callback_data=f"ckr:{code}"),
                ]
            ]
        )
        await message.answer(
            f"👤 Гость: {guest_name}\n"
            f"🆔 {row['telegram_id']}\n\n"
            f"Пополнил от {min_amount} сум? Подтверди {purpose}:",
            reply_markup=kb,
        )
        return

    # обычные бонусы (не чек-ин) — гасим сразу, без доп. подтверждения
    status, redeemed = db_redeem_bonus(code, message.from_user.id)
    if status == "not_found":
        await message.answer("❌ Код не найден. Проверьте, правильно ли он введён.")
        return
    if status == "already_used":
        await message.answer("⚠️ Этот код только что кто-то уже погасил.")
        return

    label = BONUS_LABELS.get(redeemed["bonus_type"], redeemed["bonus_type"])
    amount = BONUS_AMOUNTS.get(redeemed["bonus_type"])
    amount_line = f"\n💰 Начислить: {amount}" if amount else ""
    await message.answer(f"✅ Бонус активирован!\nТип: {label}{amount_line}\nID гостя: {redeemed['telegram_id']}")


@router.message(Command("redeem"))
async def cmd_redeem(message: Message, command: CommandObject) -> None:
    if not is_admin(message.from_user.id):
        return

    code = (command.args or "").strip().upper()
    if not code:
        await message.answer("Использование: /redeem КОД\n(код гость показывает из своего бонусного сообщения)")
        return

    await do_redeem(message, code)


@router.callback_query(F.data.startswith("ckc:"))
async def cb_checkin_confirm(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return

    code = callback.data.split(":", 1)[1] if ":" in callback.data else ""
    status, row = db_redeem_bonus(code, callback.from_user.id)

    if status == "not_found":
        await callback.message.edit_text("❌ Код не найден (возможно, уже удалён).")
        await callback.answer()
        return
    if status == "already_used":
        await callback.message.edit_text("⚠️ Этот код уже был погашен ранее — повторно засчитать нельзя.")
        await callback.answer()
        return

    guest_id = row["telegram_id"]
    guest = db_get_subscriber_by_id(guest_id)
    guest_name = guest["full_name"] if guest else "без имени"

    if row["bonus_type"] == "checkin":
        extra = await apply_confirmed_checkin(guest_id)
        text = f"✅ Визит подтверждён\n👤 {guest_name}\n🆔 {guest_id}{extra}"
    else:
        amount = BONUS_AMOUNTS.get(row["bonus_type"], "")
        text = f"✅ Бонус подтверждён\n👤 {guest_name}\n🆔 {guest_id}\n💰 Начислить: {amount}"

    await callback.message.edit_text(text)
    await callback.answer("Готово")


@router.callback_query(F.data.startswith("ckr:"))
async def cb_checkin_reject(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    code = callback.data.split(":", 1)[1] if ":" in callback.data else ""
    await callback.message.edit_text(
        f"❌ Отклонено — код {code} не погашен, гость может показать его ещё раз."
    )
    await callback.answer()


async def do_find(message: Message, query: str) -> None:
    query = query.strip()
    if not query:
        await message.answer("Пришли номер телефона или Telegram ID гостя (можно частично).")
        return

    # уберём пробелы/скобки/дефисы, чтобы поиск был терпимее к формату ввода
    query_clean = "".join(ch for ch in query if ch.isdigit())
    matches = db_find_by_phone(query_clean or query)

    if not matches:
        await message.answer("Никого не нашёл по этому номеру/ID.")
        return

    tier_map = {"": "Без статуса", "silver": "🥈 Серебряный", "gold": "🥇 Золотой"}
    lines = [f"Найдено: {len(matches)}\n"]
    for g in matches:
        name = g["full_name"] or "без имени"
        username = f"@{g['username']}" if g["username"] else "—"
        joined = (g["joined_at"] or "")[:10]
        tier_label = tier_map.get(g["tier"] or "", g["tier"])
        refs = db_referral_count(g["telegram_id"])
        lines.append(
            f"👤 {name} ({username})\n"
            f"📞 {g['phone']}\n"
            f"🆔 {g['telegram_id']}\n"
            f"📅 Регистрация: {joined}\n"
            f"💎 Статус: {tier_label}, визитов: {g['visits_confirmed'] or 0}\n"
            f"👥 Приглашено друзей: {refs}\n"
        )
    await message.answer("\n".join(lines))


@router.message(Command("find"))
async def cmd_find(message: Message, command: CommandObject) -> None:
    if not is_admin(message.from_user.id):
        return

    query = (command.args or "").strip()
    if not query:
        await message.answer("Использование: /find НОМЕР_ИЛИ_ID\n(можно вводить часть номера, без +998 тоже сработает)")
        return

    await do_find(message, query)


TIER_ALIASES = {
    "none": "", "нет": "", "снять": "", "без": "",
    "silver": "silver", "серебро": "silver", "серебряный": "silver",
    "gold": "gold", "золото": "gold", "золотой": "gold",
}


@router.message(Command("setstatus"))
async def cmd_setstatus(message: Message, command: CommandObject) -> None:
    # доступно только владельцу — сознательно не is_admin(), чтобы даже другие
    # админы не могли вручную накручивать себе/друзьям статус
    if not is_owner(message.from_user.id):
        return

    args = (command.args or "").strip().split()
    if len(args) < 2:
        await message.answer(
            "Использование: /setstatus НОМЕР_ИЛИ_ID СТАТУС\n"
            "Статус: silver / gold / none\n\n"
            "Примеры:\n"
            "/setstatus 998901234567 gold\n"
            "/setstatus 123456789 none"
        )
        return

    tier_raw = args[-1].lower()
    if tier_raw not in TIER_ALIASES:
        await message.answer("Статус должен быть один из: silver, gold, none.")
        return
    new_tier = TIER_ALIASES[tier_raw]

    identifier = " ".join(args[:-1]).strip()
    identifier_digits = "".join(ch for ch in identifier if ch.isdigit())

    target = None
    matches: list[dict] = []

    if identifier_digits:
        target = db_get_subscriber_by_id(int(identifier_digits))

    if not target:
        matches = db_find_by_phone(identifier_digits or identifier)
        if len(matches) == 1:
            target = matches[0]

    if not target:
        if len(matches) > 1:
            lines = [f"Нашёл {len(matches)} совпадений, уточни номер:\n"]
            for g in matches[:10]:
                lines.append(f"🆔 {g['telegram_id']} — {g['full_name'] or 'без имени'} — 📞 {g['phone']}")
            await message.answer("\n".join(lines))
        else:
            await message.answer("Не нашёл гостя ни по ID, ни по номеру телефона.")
        return

    old_tier = target["tier"] or ""
    old_label = TIER_LABELS.get(old_tier, "Без статуса")
    new_label = TIER_LABELS.get(new_tier, "Без статуса")

    if old_tier == new_tier:
        await message.answer(f"У гостя уже стоит статус: {new_label}. Ничего не поменял.")
        return

    db_set_tier(target["telegram_id"], new_tier)
    name = target["full_name"] or "без имени"
    crm_note = ""
    if new_tier == "gold":
        crm_note = f"\n\n⚠️ Не забудь включить скидку {TIER_GOLD_DISCOUNT_PERCENT}% в CRM."
    elif new_tier == "silver":
        crm_note = f"\n\n⚠️ Не забудь включить скидку {TIER_SILVER_DISCOUNT_PERCENT}% в CRM."
    elif old_tier in ("silver", "gold") and not new_tier:
        crm_note = "\n\n⚠️ Не забудь снять скидку в CRM."
    await message.answer(
        f"✅ Статус изменён вручную\n"
        f"👤 {name}\n"
        f"🆔 {target['telegram_id']}\n"
        f"📞 {target['phone']}\n"
        f"{old_label} → {new_label}{crm_note}"
    )

    try:
        guest_facing_label = tier_label_for_user(target["telegram_id"], new_tier) if new_tier else new_label
        await bot.send_message(
            target["telegram_id"],
            f"Твой статус в Colizeum обновлён: {guest_facing_label} 🎮",
            reply_markup=main_menu_kb(target["telegram_id"]),
        )
    except Exception:
        logging.warning(
            "не удалось уведомить гостя %s о ручном изменении статуса", target["telegram_id"]
        )


def _no_match_reply(matches: list[dict]) -> str:
    if not matches:
        return "Не нашёл гостя ни по ID, ни по номеру телефона."
    lines = [f"Нашёл {len(matches)} совпадений, уточни номер:\n"]
    for g in matches[:10]:
        lines.append(f"🆔 {g['telegram_id']} — {g['full_name'] or 'без имени'} — 📞 {g['phone']}")
    return "\n".join(lines)


@router.message(Command("test_feedback"))
async def cmd_test_feedback(message: Message, command: CommandObject) -> None:
    # тестовая отправка одному гостю — не трогает db_due_for_feedback,
    # автоматический цикл этому же гостю позже сработает как обычно
    if not is_owner(message.from_user.id):
        return
    identifier = (command.args or "").strip()
    if not identifier:
        await message.answer("Использование: /test_feedback НОМЕР_ИЛИ_ID")
        return
    target, matches = resolve_guest(identifier)
    if not target:
        await message.answer(_no_match_reply(matches))
        return
    try:
        await bot.send_message(target["telegram_id"], FEEDBACK_PROMPT_TEXT, reply_markup=FEEDBACK_KB)
        await message.answer(f"✅ Тестовый запрос обратной связи отправлен: {target['full_name'] or target['telegram_id']}")
    except Exception:
        await message.answer("❌ Не получилось отправить — возможно, гость ещё не запускал бота или заблокировал его.")


@router.message(Command("test_reminder"))
async def cmd_test_reminder(message: Message, command: CommandObject) -> None:
    if not is_owner(message.from_user.id):
        return
    identifier = (command.args or "").strip()
    if not identifier:
        await message.answer("Использование: /test_reminder НОМЕР_ИЛИ_ID")
        return
    target, matches = resolve_guest(identifier)
    if not target:
        await message.answer(_no_match_reply(matches))
        return
    try:
        code = db_create_bonus(target["telegram_id"], "reminder")
        await bot.send_message(target["telegram_id"], f"{REMINDER_TEXT}\n\n🔑 Код бонуса: {code}")
        await message.answer(f"✅ Тестовое напоминание отправлено: {target['full_name'] or target['telegram_id']}\n🔑 Код (реальный, погашаемый): {code}")
    except Exception:
        await message.answer("❌ Не получилось отправить — возможно, гость ещё не запускал бота или заблокировал его.")


@router.message(Command("test_winback"))
async def cmd_test_winback(message: Message, command: CommandObject) -> None:
    if not is_owner(message.from_user.id):
        return
    identifier = (command.args or "").strip()
    if not identifier:
        await message.answer("Использование: /test_winback НОМЕР_ИЛИ_ID")
        return
    target, matches = resolve_guest(identifier)
    if not target:
        await message.answer(_no_match_reply(matches))
        return
    try:
        code = db_create_bonus(target["telegram_id"], "winback")
        await bot.send_message(target["telegram_id"], f"{WINBACK_TEXT}\n\n🔑 Код бонуса: {code}")
        await message.answer(f"✅ Тестовый win-back отправлен: {target['full_name'] or target['telegram_id']}\n🔑 Код (реальный, погашаемый): {code}")
    except Exception:
        await message.answer("❌ Не получилось отправить — возможно, гость ещё не запускал бота или заблокировал его.")


@router.message(Command("winback_preview"))
async def cmd_winback_preview(message: Message, user_id: int | None = None) -> None:
    # ничего не отправляет — просто показывает, кому прямо сейчас
    # ушло бы win-back-сообщение, если запустить рассылку
    user_id = user_id if user_id is not None else message.from_user.id
    if not is_owner(user_id):
        return
    ids = db_due_for_winback(WINBACK_DELAY_DAYS, WINBACK_MIN_VISITS)
    if not ids:
        await message.answer("Сейчас никто не подходит под условия win-back (никого не пропустили).")
        return
    lines = [f"Под win-back сейчас подходит: {len(ids)} чел.\n"]
    for tg_id in ids[:15]:
        g = db_get_subscriber_by_id(tg_id)
        if g:
            lines.append(f"🆔 {g['telegram_id']} — {g['full_name'] or 'без имени'} — 📞 {g['phone']}")
    if len(ids) > 15:
        lines.append(f"...и ещё {len(ids) - 15}")
    lines.append("\nЧтобы реально разослать всем этим гостям — /run_winback_now")
    await message.answer("\n".join(lines))


@router.message(Command("run_winback_now"))
async def cmd_run_winback_now(message: Message, state: FSMContext, user_id: int | None = None) -> None:
    # реальная массовая рассылка win-back прямо сейчас (не ждём авто-цикл раз в 6 часов),
    # тем же гостям, что видно в /winback_preview — требует подтверждения, необратимо
    user_id = user_id if user_id is not None else message.from_user.id
    if not is_owner(user_id):
        return
    ids = db_due_for_winback(WINBACK_DELAY_DAYS, WINBACK_MIN_VISITS)
    if not ids:
        await message.answer("Сейчас никто не подходит под условия win-back — рассылать некому.")
        return
    await state.update_data(winback_ids=ids)
    await message.answer(
        f"⚠️ Сейчас уйдёт реальная рассылка {len(ids)} гостям (не тест).\n"
        "Чтобы подтвердить, напиши ДА\n"
        "Чтобы отменить — /cancel"
    )
    await state.set_state(WinbackNowState.waiting_confirm)


@router.message(WinbackNowState.waiting_confirm, Command("cancel"))
async def cmd_run_winback_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено, никому ничего не ушло.")


@router.message(WinbackNowState.waiting_confirm, F.text.upper() == "ДА")
async def cmd_run_winback_confirm(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    ids = data.get("winback_ids", [])
    await state.clear()

    sent = 0
    for tg_id in ids:
        try:
            code = db_create_bonus(tg_id, "winback")
            await bot.send_message(tg_id, f"{WINBACK_TEXT}\n\n🔑 Код бонуса: {code}")
            sent += 1
        except Exception:
            logging.warning("не удалось отправить win-back %s", tg_id)
        db_mark_winback_sent(tg_id)
        await asyncio.sleep(0.1)

    await message.answer(f"✅ Готово. Win-back отправлен: {sent} из {len(ids)}.")


@router.message(Command("wheel_nudge"))
async def cmd_wheel_nudge(message: Message, state: FSMContext, user_id: int | None = None) -> None:
    # напоминание "у тебя есть спин сегодня" — только тем, кому колесо доступно
    # (см. WHEEL_MIN_TIER) и кто ещё не крутил сегодня. Требует подтверждения.
    user_id = user_id if user_id is not None else message.from_user.id
    if not is_owner(user_id):
        return
    ids = db_wheel_nudge_targets()
    if not ids:
        await message.answer("Сейчас некому слать — либо все уже крутили сегодня, либо нет гостей с доступом к колесу.")
        return
    await state.update_data(wheel_nudge_ids=ids)
    await message.answer(
        f"⚠️ Сейчас уйдёт напоминание о спине {len(ids)} гостям (Серебро/Золото, кто ещё не крутил сегодня).\n"
        "Чтобы подтвердить, напиши ДА\n"
        "Чтобы отменить — /cancel"
    )
    await state.set_state(WheelNudgeState.waiting_confirm)


@router.message(WheelNudgeState.waiting_confirm, Command("cancel"))
async def cmd_wheel_nudge_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено, никому ничего не ушло.")


@router.message(WheelNudgeState.waiting_confirm, F.text.upper() == "ДА")
async def cmd_wheel_nudge_confirm(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    ids = data.get("wheel_nudge_ids", [])
    await state.clear()

    sent = 0
    for tg_id in ids:
        try:
            await bot.send_message(tg_id, WHEEL_NUDGE_TEXT)
            sent += 1
        except Exception:
            logging.warning("не удалось отправить напоминание о колесе %s", tg_id)
        await asyncio.sleep(0.1)

    await message.answer(f"✅ Готово. Напоминание отправлено: {sent} из {len(ids)}.")


@router.message(Command("wheel_trial_grant"))
async def cmd_wheel_trial_grant(message: Message, state: FSMContext, user_id: int | None = None) -> None:
    # даёт ОДИН пробный спин всем гостям без доступа к колесу (ниже WHEEL_MIN_TIER),
    # у кого ещё нет неиспользованного пробного спина. После одного вращения
    # (см. handle_wheel_spin) спин автоматически сгорает, и колесо снова закрывается.
    user_id = user_id if user_id is not None else message.from_user.id
    if not is_owner(user_id):
        return
    ids = db_trial_spin_targets()
    if not ids:
        await message.answer("Сейчас некому выдавать — у всех либо уже есть доступ, либо уже есть пробный спин.")
        return
    await state.update_data(wheel_trial_ids=ids)
    await message.answer(
        f"⚠️ Сейчас {len(ids)} гостям без статуса откроется колесо на ОДИН спин, и придёт уведомление.\n"
        "Чтобы подтвердить, напиши ДА\n"
        "Чтобы отменить — /cancel"
    )
    await state.set_state(WheelTrialGrantState.waiting_confirm)


@router.message(WheelTrialGrantState.waiting_confirm, Command("cancel"))
async def cmd_wheel_trial_grant_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено, никому ничего не выдал.")


@router.message(WheelTrialGrantState.waiting_confirm, F.text.upper() == "ДА")
async def cmd_wheel_trial_grant_confirm(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    ids = data.get("wheel_trial_ids", [])
    await state.clear()

    sent = 0
    for tg_id in ids:
        db_grant_trial_spin(tg_id)
        try:
            await bot.send_message(tg_id, WHEEL_TRIAL_TEXT, reply_markup=main_menu_kb(tg_id))
            sent += 1
        except Exception:
            logging.warning("не удалось уведомить о пробном спине %s", tg_id)
        await asyncio.sleep(0.1)

    await message.answer(f"✅ Готово. Пробный спин выдан и разослан: {sent} из {len(ids)}.")


def owner_more_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👀 Win-back: превью", callback_data="ownermenu:winback_preview")],
            [InlineKeyboardButton(text="📢 Win-back: разослать всем", callback_data="ownermenu:winback_run")],
            [InlineKeyboardButton(text="🎡 Напомнить про спин", callback_data="ownermenu:wheel_nudge")],
            [InlineKeyboardButton(text="🎁 Пробный спин всем без статуса", callback_data="ownermenu:wheel_trial")],
        ]
    )


@router.message(F.text == OWNER_BUTTON_MORE)
async def owner_btn_more(message: Message) -> None:
    if not is_owner(message.from_user.id):
        return
    await message.answer("Что сделать?", reply_markup=owner_more_menu_kb())


@router.callback_query(F.data.startswith("ownermenu:"))
async def cb_owner_more(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_owner(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return

    action = callback.data.split(":", 1)[1]
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    if action == "winback_preview":
        await cmd_winback_preview(callback.message, user_id=callback.from_user.id)
    elif action == "winback_run":
        await cmd_run_winback_now(callback.message, state, user_id=callback.from_user.id)
    elif action == "wheel_nudge":
        await cmd_wheel_nudge(callback.message, state, user_id=callback.from_user.id)
    elif action == "wheel_trial":
        await cmd_wheel_trial_grant(callback.message, state, user_id=callback.from_user.id)


@router.message(Command("export"))
async def cmd_export(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return

    csv_bytes, count = build_subscribers_csv()
    if count == 0:
        await message.answer("В базе пока нет подписчиков.")
        return

    filename = f"colizeum_subscribers_{datetime.now(TASHKENT_TZ).date().isoformat()}.csv"
    await message.answer_document(
        BufferedInputFile(csv_bytes, filename=filename),
        caption=f"Выгрузка подписчиков: {count} чел.",
    )


@router.message(Command("export_codes"))
async def cmd_export_codes(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return

    csv_bytes, count = build_bonuses_csv()
    if count == 0:
        await message.answer("Кодов пока нет.")
        return

    filename = f"colizeum_codes_{datetime.now(TASHKENT_TZ).date().isoformat()}.csv"
    await message.answer_document(
        BufferedInputFile(csv_bytes, filename=filename),
        caption=f"Выгрузка кодов бонусов: {count} шт. — для сверки с CRM.",
    )


_FEEDBACK_KIND_LABEL = {
    "review_photo": "⭐ Отзыв (с фото)",
    "review_no_photo": "⭐ Отзыв (без фото)",
    "rating": "📝 Оценка визита",
}
RATING_KINDS = ("rating",)
MAPS_REVIEW_KINDS = ("review_photo", "review_no_photo")


def _format_feedback_lines(rows: list[dict]) -> str:
    lines = [f"Последние {len(rows)}:\n"]
    for r in rows:
        kind_label = _FEEDBACK_KIND_LABEL.get(r["kind"], r["kind"])
        name = r["full_name"] or "без имени"
        when = (r["created_at"] or "")[:16].replace("T", " ")
        line = f"{kind_label} — {name} ({r['phone'] or r['telegram_id']}) — {when}"
        if r["rating"]:
            line += f"\nОценка: {r['rating']}/5"
        if r["comment"]:
            line += f"\n«{r['comment']}»"
        if r["photo_file_id"]:
            line += "\n📸 есть скриншот"
        lines.append(line)
    return "\n\n".join(lines)


@router.message(Command("reviews"))
async def cmd_reviews(message: Message, command: CommandObject) -> None:
    """Только оценки визита 1-5 (с комментариями, если гость их оставил)."""
    if not is_admin(message.from_user.id):
        return

    limit = 15
    arg = (command.args or "").strip()
    if arg.isdigit():
        limit = min(int(arg), 50)

    rows = db_list_recent_feedback(limit, kinds=RATING_KINDS)
    if not rows:
        await message.answer("Оценок визитов пока нет.")
        return

    await message.answer(_format_feedback_lines(rows))


@router.message(Command("reviews_maps"))
async def cmd_reviews_maps(message: Message, command: CommandObject) -> None:
    """Только отзывы на картах (2GIS/Google/Яндекс) за бонус."""
    if not is_admin(message.from_user.id):
        return

    limit = 15
    arg = (command.args or "").strip()
    if arg.isdigit():
        limit = min(int(arg), 50)

    rows = db_list_recent_feedback(limit, kinds=MAPS_REVIEW_KINDS)
    if not rows:
        await message.answer("Отзывов на картах пока нет.")
        return

    await message.answer(_format_feedback_lines(rows))


def build_feedback_csv(kinds: tuple[str, ...] | None = None) -> tuple[bytes, int]:
    rows = db_export_all_feedback(kinds)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Тип", "Оценка", "Комментарий", "Имя гостя", "Телефон", "Telegram ID", "Дата"])
    for r in rows:
        writer.writerow(
            [
                _FEEDBACK_KIND_LABEL.get(r["kind"], r["kind"]),
                r["rating"] or "",
                r["comment"] or "",
                r["full_name"] or "",
                r["phone"] or "",
                r["telegram_id"] or "",
                (r["created_at"] or "")[:16].replace("T", " "),
            ]
        )
    return buffer.getvalue().encode("utf-8-sig"), len(rows)


@router.message(Command("export_reviews"))
async def cmd_export_reviews(message: Message) -> None:
    """Выгрузка только оценок визита."""
    if not is_admin(message.from_user.id):
        return

    csv_bytes, count = build_feedback_csv(kinds=RATING_KINDS)
    if count == 0:
        await message.answer("Оценок визитов пока нет.")
        return

    filename = f"colizeum_ratings_{datetime.now(TASHKENT_TZ).date().isoformat()}.csv"
    await message.answer_document(
        BufferedInputFile(csv_bytes, filename=filename),
        caption=f"Выгрузка оценок визита: {count} шт.",
    )


@router.message(Command("export_reviews_maps"))
async def cmd_export_reviews_maps(message: Message) -> None:
    """Выгрузка только отзывов на картах."""
    if not is_admin(message.from_user.id):
        return

    csv_bytes, count = build_feedback_csv(kinds=MAPS_REVIEW_KINDS)
    if count == 0:
        await message.answer("Отзывов на картах пока нет.")
        return

    filename = f"colizeum_reviews_maps_{datetime.now(TASHKENT_TZ).date().isoformat()}.csv"
    await message.answer_document(
        BufferedInputFile(csv_bytes, filename=filename),
        caption=f"Выгрузка отзывов на картах: {count} шт.",
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


def db_set_phone(telegram_id: int, phone: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE subscribers SET phone = ? WHERE telegram_id = ?", (phone, telegram_id))
    conn.commit()
    conn.close()


async def do_reset_review(message: Message, arg: str) -> None:
    arg = arg.strip()
    if not arg.isdigit():
        await message.answer("Это должен быть числовой Telegram ID гостя.")
        return
    telegram_id = int(arg)
    db_reset_review_claim(telegram_id)
    await message.answer(f"Готово ✅ Гость {telegram_id} снова может получить бонус за отзыв.")


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
    await do_reset_review(message, arg)


@router.message(Command("setphone"))
async def cmd_setphone(message: Message, command: CommandObject) -> None:
    if not is_admin(message.from_user.id):
        return
    parts = (command.args or "").strip().split()
    if len(parts) != 2 or not parts[0].isdigit():
        await message.answer(
            "Использование: /setphone TELEGRAM_ID НОВЫЙ_НОМЕР\n"
            "(поправить номер, если гость при регистрации отправил не свой — "
            "например рабочий, а не тот, что привязан к его Telegram)"
        )
        return
    telegram_id = int(parts[0])
    new_phone = parts[1]
    guest = db_get_subscriber_by_id(telegram_id)
    if not guest:
        await message.answer("Гость с таким ID не найден в базе.")
        return
    old_phone = guest["phone"]
    db_set_phone(telegram_id, new_phone)
    await message.answer(f"✅ Номер обновлён.\n🆔 {telegram_id}\n📞 {old_phone} → {new_phone}")


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
    await message.answer("Кому отправляем рассылку?", reply_markup=BROADCAST_SEGMENT_KB)
    await state.set_state(BroadcastState.waiting_segment)


@router.callback_query(BroadcastState.waiting_segment, F.data.startswith("bcseg_"))
async def broadcast_pick_segment(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await callback.answer()
    segment = callback.data.removeprefix("bcseg_")
    ids = db_segment_ids(segment)
    await state.update_data(segment=segment)
    await callback.message.answer(
        f"Сегмент: {SEGMENT_LABELS.get(segment, segment)} ({len(ids)} чел.)\n\n"
        "Отправь текст, который нужно разослать.\nЧтобы отменить — напиши /cancel"
    )
    await state.set_state(BroadcastState.waiting_text)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer("Отменено.")


@router.message(BroadcastState.waiting_text)
async def broadcast_get_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    segment = data.get("segment", "all")
    ids = db_segment_ids(segment)
    await state.update_data(text=message.html_text)
    await message.answer(
        f"Получатели: {SEGMENT_LABELS.get(segment, segment)} ({len(ids)} чел.)\n\n"
        f"Вот текст сообщения:\n\n{message.text}\n\n"
        f"Отправляем? Напиши ДА для отправки или /cancel для отмены.",
    )
    await state.set_state(BroadcastState.waiting_confirm)


@router.message(BroadcastState.waiting_confirm, F.text.upper() == "ДА")
async def broadcast_confirm(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    text = data["text"]
    segment = data.get("segment", "all")
    await state.clear()

    ids = db_segment_ids(segment)
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
    db_log_feedback(user_id, bonus_type, photo_file_id=message.photo[-1].file_id)
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


@router.callback_query(F.data.in_({f"feedback_{i}" for i in range(1, 6)}))
async def cb_feedback(callback: CallbackQuery, state: FSMContext) -> None:
    rating = callback.data.split("_", 1)[1]
    user = callback.from_user

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    if rating == "5":
        await callback.answer("Спасибо за оценку! 🙌")
        db_log_feedback(user.id, "rating", rating=rating)
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id, f"📝 Оценка визита: {rating}/5\nГость: {user.full_name} (id {user.id})"
                )
            except Exception:
                logging.warning("не удалось переслать оценку админу %s", admin_id)
        await callback.message.answer("Спасибо, что поделился впечатлением! 🙏")
        return

    # низкая оценка (1-4) — сразу спрашиваем, что пошло не так
    await callback.answer()
    await state.update_data(feedback_rating=rating)
    await state.set_state(FeedbackDetail.waiting_text)
    await callback.message.answer(
        f"Жаль это слышать 😔 Оценка {rating}/5 — расскажи, пожалуйста, что пошло не так? "
        "Это поможет нам исправиться.\n\n"
        "Если не хочешь писать — просто нажми «Пропустить».",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Пропустить", callback_data="feedback_skip")]]
        ),
    )


@router.callback_query(F.data == "feedback_skip")
async def cb_feedback_skip(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    rating = data.get("feedback_rating", "?")
    await state.clear()
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    user = callback.from_user
    db_log_feedback(user.id, "rating", rating=rating)
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id, f"📝 Оценка визита: {rating}/5 (без комментария)\nГость: {user.full_name} (id {user.id})"
            )
        except Exception:
            logging.warning("не удалось переслать оценку админу %s", admin_id)
    await callback.message.answer("Понял, спасибо за оценку 🙏")


@router.message(FeedbackDetail.waiting_text)
async def feedback_detail_text(message: Message, state: FSMContext) -> None:
    if await try_menu_escape(message, state):
        return
    data = await state.get_data()
    rating = data.get("feedback_rating", "?")
    await state.clear()

    user = message.from_user
    comment = (message.text or "").strip()
    db_log_feedback(user.id, "rating", rating=rating, comment=comment)
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"📝 Оценка визита: {rating}/5\n"
                f"Гость: {user.full_name} (id {user.id})\n\n"
                f"Что пошло не так:\n«{comment}»",
            )
        except Exception:
            logging.warning("не удалось переслать оценку админу %s", admin_id)

    await message.answer("Спасибо, что рассказал — обязательно разберёмся 🙏")


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


# ---------- MINI APP: КОЛЕСО ФОРТУНЫ ----------
def verify_webapp_init_data(init_data: str) -> dict | None:
    """Проверяет подпись данных, присланных Telegram Mini App, чтобы никто не мог
    подделать чужой telegram_id и накрутить бонусы. Возвращает данные гостя или None."""
    if not init_data:
        return None
    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None

    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    user_json = parsed.get("user")
    if not user_json:
        return None
    try:
        return json.loads(user_json)
    except json.JSONDecodeError:
        return None


# 8 секторов колеса (порядок важен - должен совпадать с версткой в webapp/index.html)
# только 1 обычный приз и 1 джекпот из 8 - редко, но крупно
WHEEL_SEGMENTS = [
    {"index": 0, "type": "lose"},
    {"index": 1, "type": "lose"},
    {"index": 2, "type": "win"},
    {"index": 3, "type": "lose"},
    {"index": 4, "type": "lose"},
    {"index": 5, "type": "lose"},
    {"index": 6, "type": "lose"},
    {"index": 7, "type": "jackpot"},
]


def pick_wheel_segment() -> dict:
    """Выбирает сектор колеса с учётом WHEEL_WIN_PERCENT/WHEEL_JACKPOT_PERCENT,
    а не поровну между 8 секторами. Визуальная раскладка колеса не меняется —
    просто "пустые" сектора в сумме получают меньший вес."""
    lose = [s for s in WHEEL_SEGMENTS if s["type"] == "lose"]
    win = [s for s in WHEEL_SEGMENTS if s["type"] == "win"]
    jackpot = [s for s in WHEEL_SEGMENTS if s["type"] == "jackpot"]

    jackpot_pct = max(0.0, min(100.0, WHEEL_JACKPOT_PERCENT))
    win_pct = max(0.0, min(100.0 - jackpot_pct, WHEEL_WIN_PERCENT))
    lose_pct = max(0.0, 100.0 - win_pct - jackpot_pct)

    weights = []
    for s in WHEEL_SEGMENTS:
        if s["type"] == "lose" and lose:
            weights.append(lose_pct / len(lose))
        elif s["type"] == "win" and win:
            weights.append(win_pct / len(win))
        elif s["type"] == "jackpot" and jackpot:
            weights.append(jackpot_pct / len(jackpot))
        else:
            weights.append(0.0)

    return random.choices(WHEEL_SEGMENTS, weights=weights, k=1)[0]

TIER_RANK = {"": 0, "silver": 1, "gold": 2}
WHEEL_MIN_TIER_RANK = TIER_RANK.get(WHEEL_MIN_TIER, 1)


def wheel_eligibility(user_id: int) -> dict:
    tier = db_get_tier(user_id)
    visits = db_get_visits(user_id)
    by_tier = TIER_RANK.get(tier, 0) >= WHEEL_MIN_TIER_RANK
    trial = (not by_tier) and db_has_trial_spin(user_id)
    return {
        "tier": tier,
        "visits": visits,
        "visits_needed": TIER_SILVER_VISITS if WHEEL_MIN_TIER_RANK <= 1 else TIER_GOLD_VISITS,
        "eligible": by_tier or trial,
        "via_trial": trial,
    }


async def handle_wheel_page(request: web.Request) -> web.Response:
    html_path = os.path.join(BASE_DIR, "webapp", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    html = html.replace("{{WIN_POINTS}}", LOTTERY_WIN_POINTS).replace("{{JACKPOT_POINTS}}", LOTTERY_JACKPOT_POINTS)
    return web.Response(text=html, content_type="text/html")


async def handle_wheel_status(request: web.Request) -> web.Response:
    init_data = request.query.get("initData", "")
    user = verify_webapp_init_data(init_data)
    if not user:
        return web.json_response({"error": "invalid_auth"}, status=401)

    user_id = user["id"]
    if not db_is_subscriber(user_id):
        return web.json_response({"subscribed": False})

    elig = wheel_eligibility(user_id)
    today = datetime.now(TASHKENT_TZ).date().isoformat()
    can_spin = elig["eligible"] and db_get_last_spin_date(user_id) != today

    return web.json_response({
        "subscribed": True,
        "can_spin": can_spin,
        "tier_label": tier_label_for_user(user_id, elig["tier"]),
        "required_tier_label": tier_label_for_user(user_id, WHEEL_MIN_TIER),
        **elig,
    })


async def handle_wheel_spin(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "bad_request"}, status=400)

    user = verify_webapp_init_data(body.get("initData", ""))
    if not user:
        return web.json_response({"error": "invalid_auth"}, status=401)

    user_id = user["id"]
    if not db_is_subscriber(user_id):
        return web.json_response({"error": "not_subscribed"}, status=403)

    elig = wheel_eligibility(user_id)
    if not elig["eligible"]:
        return web.json_response({"error": "not_eligible"}, status=403)

    today = datetime.now(TASHKENT_TZ).date().isoformat()
    if db_get_last_spin_date(user_id) == today:
        return web.json_response({"error": "already_spun"}, status=409)

    db_set_last_spin_date(user_id, today)
    if elig["via_trial"]:
        db_consume_trial_spin(user_id)
    chosen = pick_wheel_segment()
    result = {"segment_index": chosen["index"], "prize_type": chosen["type"]}

    if chosen["type"] in ("win", "jackpot"):
        bonus_type = "lottery_jackpot" if chosen["type"] == "jackpot" else "lottery_win"
        code = db_create_bonus(user_id, bonus_type)
        amount = BONUS_AMOUNTS.get(bonus_type)
        result["amount"] = amount
        result["code"] = code
        try:
            prize_emoji = "🎉" if chosen["type"] == "jackpot" else "🎊"
            await bot.send_message(
                user_id,
                f"{prize_emoji} Колесо Фортуны: выигрыш!\n"
                f"Приз: {amount}\n\n"
                f"🔑 Код: {code}\n\n"
                "Покажи это сообщение администратору на стойке.",
            )
        except Exception:
            logging.warning("не удалось отправить код выигрыша в чат %s", user_id)

    return web.json_response(result)


async def start_webapp_server() -> None:
    app = web.Application()
    app.router.add_get("/wheel", handle_wheel_page)
    app.router.add_get("/wheel/status", handle_wheel_status)
    app.router.add_post("/wheel/spin", handle_wheel_spin)

    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info("Веб-сервер колеса фортуны запущен на порту %s", port)


async def winback_loop() -> None:
    while True:
        try:
            for tg_id in db_due_for_winback(WINBACK_DELAY_DAYS, WINBACK_MIN_VISITS):
                try:
                    code = db_create_bonus(tg_id, "winback")
                    await bot.send_message(tg_id, f"{WINBACK_TEXT}\n\n🔑 Код бонуса: {code}")
                except Exception:
                    logging.warning("не удалось отправить win-back %s", tg_id)
                db_mark_winback_sent(tg_id)
                await asyncio.sleep(0.1)
        except Exception:
            logging.exception("ошибка в winback_loop")
        await asyncio.sleep(3600 * 6)  # проверяем раз в 6 часов


async def retention_loop() -> None:
    """1-го числа каждого месяца проверяет, выполнили ли Серебро/Золото план
    визитов за только что закончившийся месяц, и продлевает или понижает статус."""
    while True:
        try:
            await run_monthly_retention_check()
        except Exception:
            logging.exception("ошибка в retention_loop")
        await asyncio.sleep(3600 * 12)  # смотрим дважды в сутки, само действие — раз в месяц


async def run_monthly_retention_check() -> None:
    today = datetime.now(TASHKENT_TZ).date()
    if today.day != 1:
        return  # действие только 1-го числа

    ym_key = today.strftime("%Y-%m")
    if db_get_setting("last_retention_run") == ym_key:
        return  # уже отработали в этом месяце

    py, pm = previous_month_ym(today)
    start_iso, end_iso = tashkent_month_range_to_naive_utc(py, pm)
    grace_cutoff = start_iso  # если статус получен позже начала прошлого месяца — это ещё грейс-период

    for guest in db_retention_candidates(start_iso, end_iso):
        guest_id = guest["telegram_id"]
        tier = guest["tier"]
        tier_since = guest["tier_since"]

        if not tier_since or tier_since >= grace_cutoff:
            continue  # статус получен недавно — в этом месяце ещё не спрашиваем план визитов

        visits = guest["visits_in_period"]
        required = TIER_GOLD_MAINTAIN_VISITS if tier == "gold" else TIER_SILVER_MAINTAIN_VISITS

        if visits >= required:
            await _retention_extend(guest_id, tier, visits, required)
        else:
            await _retention_downgrade(guest_id, tier, visits, required)

    db_set_setting("last_retention_run", ym_key)


async def _retention_extend(guest_id: int, tier: str, visits: int, required: int) -> None:
    bonus_type = f"tier_{tier}_monthly"
    amount = TIER_GOLD_MONTHLY_BONUS if tier == "gold" else TIER_SILVER_MONTHLY_BONUS
    discount = TIER_GOLD_DISCOUNT_PERCENT if tier == "gold" else TIER_SILVER_DISCOUNT_PERCENT
    try:
        code = db_create_bonus(guest_id, bonus_type)
        themed_label = tier_label_for_user(guest_id, tier)
        await bot.send_message(
            guest_id,
            f"🎉 План визитов за прошлый месяц выполнен ({visits}/{required})!\n"
            f"Статус {themed_label} продлён, скидка {discount}% остаётся в силе.\n\n"
            f"Бонус: {amount} сум на баланс.\n🔑 Код: {code}",
        )
    except Exception:
        logging.warning("не удалось уведомить гостя %s о продлении статуса", guest_id)


async def _retention_downgrade(guest_id: int, tier: str, visits: int, required: int) -> None:
    new_tier = "silver" if tier == "gold" else ""
    db_set_tier(guest_id, new_tier)
    old_label = TIER_LABELS.get(tier, tier)
    new_label = TIER_LABELS.get(new_tier, "без статуса")

    try:
        await bot.send_message(
            guest_id,
            f"⚠️ План визитов за прошлый месяц не выполнен ({visits} из {required}).\n"
            f"Статус понижен: {old_label} → {new_label}.\n"
            "Возвращайся чаще, чтобы вернуть привилегии 🙂",
            reply_markup=main_menu_kb(guest_id),
        )
    except Exception:
        logging.warning("не удалось уведомить гостя %s о понижении статуса", guest_id)

    for admin_id in ADMIN_IDS:
        try:
            if new_tier == "silver":
                note = (
                    f"понизьте скидку в CRM с {TIER_GOLD_DISCOUNT_PERCENT}% до "
                    f"{TIER_SILVER_DISCOUNT_PERCENT}%"
                )
            else:
                note = "снимите скидку в CRM полностью"
            await bot.send_message(
                admin_id,
                f"📉 Статус понижен: {old_label} → {new_label}\n"
                f"🆔 {guest_id}\n"
                f"Визитов за прошлый месяц: {visits} (нужно было {required})\n\n"
                f"⚠️ Не забудьте {note}.",
            )
        except Exception:
            logging.warning("не удалось уведомить админа %s о понижении статуса", admin_id)


def build_subscribers_csv(date_from_iso: str | None = None, date_to_iso: str | None = None) -> tuple[bytes, int]:
    rows = db_export_all(date_from_iso, date_to_iso)
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
    return buffer.getvalue().encode("utf-8-sig"), len(rows)


def build_bonuses_csv(date_from_iso: str | None = None, date_to_iso: str | None = None) -> tuple[bytes, int]:
    rows = db_export_all_bonuses(date_from_iso, date_to_iso)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "Код", "Тип бонуса", "Размер", "Статус",
            "Имя гостя", "Телефон", "Telegram ID",
            "Создан", "Погашен", "Кем погашен (admin ID)",
        ]
    )
    for r in rows:
        label = BONUS_LABELS.get(r["bonus_type"], r["bonus_type"])
        amount = BONUS_AMOUNTS.get(r["bonus_type"], "")
        writer.writerow(
            [
                r["code"],
                label,
                amount,
                "Использован" if r["used_at"] else "Не использован",
                r["full_name"] or "",
                r["phone"] or "",
                r["telegram_id"] or "",
                (r["created_at"] or "")[:16].replace("T", " "),
                (r["used_at"] or "")[:16].replace("T", " ") if r["used_at"] else "",
                r["used_by_admin"] or "",
            ]
        )
    return buffer.getvalue().encode("utf-8-sig"), len(rows)


async def backup_loop() -> None:
    while True:
        try:
            last = db_get_setting("last_backup_at")
            now = datetime.now(TASHKENT_TZ)
            due = True
            if last:
                try:
                    last_dt = datetime.fromisoformat(last)
                    due = (now - last_dt).days >= BACKUP_INTERVAL_DAYS
                except ValueError:
                    due = True

            if due:
                csv_bytes, count = build_subscribers_csv()
                filename = f"colizeum_backup_{now.date().isoformat()}.csv"
                for admin_id in ADMIN_IDS:
                    try:
                        await bot.send_document(
                            admin_id,
                            BufferedInputFile(csv_bytes, filename=filename),
                            caption=f"📦 Еженедельный бэкап базы: {count} подписчиков",
                        )
                    except Exception:
                        logging.warning("не удалось отправить бэкап админу %s", admin_id)
                db_set_setting("last_backup_at", now.isoformat())
        except Exception:
            logging.exception("ошибка в backup_loop")
        await asyncio.sleep(3600 * 6)  # проверяем раз в 6 часов


# ---------- ЗАПУСК ----------
async def main() -> None:
    db_init()
    asyncio.create_task(reminder_loop())
    asyncio.create_task(feedback_loop())
    asyncio.create_task(winback_loop())
    asyncio.create_task(retention_loop())
    asyncio.create_task(backup_loop())
    await start_webapp_server()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
