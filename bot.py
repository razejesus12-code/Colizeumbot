import asyncio
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
    "review": "Бонус за отзыв",
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

REVIEW_DELAY_HOURS = int(os.environ.get("REVIEW_DELAY_HOURS", "2"))
REVIEW_LINK_2GIS = os.environ.get("REVIEW_LINK_2GIS", "")
REVIEW_LINK_GOOGLE = os.environ.get("REVIEW_LINK_GOOGLE", "")
REVIEW_PROMPT_TEXT = os.environ.get(
    "REVIEW_PROMPT_TEXT",
    "Спасибо, что заглянул к нам! 🙌\n\n"
    "Если понравилось — оставь короткий отзыв, это правда помогает клубу.\n"
    "После отзыва нажми кнопку ниже и получи бонус 🎁",
)
REVIEW_BONUS_TEXT = os.environ.get(
    "REVIEW_BONUS_TEXT",
    "🙏 Спасибо за отзыв!\nБонус: +10% к следующему пополнению баланса.",
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
        [KeyboardButton(text="💎 Мой статус")],
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
_review_buttons.append([InlineKeyboardButton(text="✅ Я оставил отзыв", callback_data="review_done")])
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
    # на случай, если база создавалась ещё старой версией бота - аккуратно добавляем колонки
    for column, coltype in (
        ("referred_by", "INTEGER"),
        ("reminder_sent", "INTEGER DEFAULT 0"),
        ("visits_confirmed", "INTEGER DEFAULT 0"),
        ("tier", "TEXT DEFAULT ''"),
        ("first_checkin_at", "TEXT"),
        ("review_prompted", "INTEGER DEFAULT 0"),
        ("review_bonus_claimed", "INTEGER DEFAULT 0"),
    ):
        try:
            conn.execute(f"ALTER TABLE subscribers ADD COLUMN {column} {coltype}")
        except sqlite3.OperationalError:
            pass  # колонка уже есть
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


def db_referral_count(telegram_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    n = conn.execute(
        "SELECT COUNT(*) FROM subscribers WHERE referred_by = ?", (telegram_id,)
    ).fetchone()[0]
    conn.close()
    return n


def db_remove_subscriber(telegram_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM subscribers WHERE telegram_id = ?", (telegram_id,))
    conn.commit()
    conn.close()


def db_due_for_reminder(delay_days: int) -> list[int]:
    cutoff = (datetime.now() - timedelta(days=delay_days)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT telegram_id FROM subscribers WHERE reminder_sent = 0 AND joined_at <= ?",
        (cutoff,),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def db_mark_reminder_sent(telegram_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE subscribers SET reminder_sent = 1 WHERE telegram_id = ?", (telegram_id,)
    )
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
    row = conn.execute(
        "SELECT visits_confirmed FROM subscribers WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()
    return row[0] if row and row[0] is not None else 0


def db_get_tier(telegram_id: int) -> str:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT tier FROM subscribers WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()
    return row[0] if row and row[0] else ""


def db_increment_visits(telegram_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE subscribers SET visits_confirmed = visits_confirmed + 1 WHERE telegram_id = ?",
        (telegram_id,),
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


def db_due_for_review(delay_hours: int) -> list[int]:
    cutoff = (datetime.now() - timedelta(hours=delay_hours)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT telegram_id FROM subscribers "
        "WHERE review_prompted = 0 AND first_checkin_at IS NOT NULL AND first_checkin_at <= ?",
        (cutoff,),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def db_mark_review_prompted(telegram_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE subscribers SET review_prompted = 1 WHERE telegram_id = ?", (telegram_id,)
    )
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
    conn.execute(
        "UPDATE subscribers SET review_bonus_claimed = 1 WHERE telegram_id = ?", (telegram_id,)
    )
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


# ---------- СОСТОЯНИЯ ДЛЯ РАССЫЛКИ ----------
class BroadcastState(StatesGroup):
    waiting_text = State()
    waiting_confirm = State()


# ---------- ВСПОМОГАТЕЛЬНОЕ ----------
def get_bonus_text_and_type() -> tuple[str, str]:
    """Днём в будни (10:00-17:00 по Ташкенту) - усиленный бонус, в остальное время - обычный."""
    now = datetime.now(TASHKENT_TZ)
    is_weekday = now.weekday() < 5  # 0=Пн ... 4=Пт
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

    # разбираем реферальную ссылку /start ref123456789
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
        "Привет! Это бот клуба Colizeum. 🎮\n\n"
        "Поделись номером телефона, чтобы получить бонус и не пропускать акции.",
        reply_markup=kb,
    )


@router.message(F.contact)
async def handle_contact(message: Message) -> None:
    user_id = message.from_user.id
    contact: Contact = message.contact
    # защита: чтобы гость не мог отправить чужой контакт
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
            await bot.send_message(
                referrer_id, f"{REFERRER_BONUS_TEXT}\n\n🔑 Код бонуса: {referrer_code}"
            )
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
        [InlineKeyboardButton(text="🎁 Все акции", callback_data="promo_general")],
    ]
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


@router.callback_query(F.data == "promo_general")
async def cb_promo_general(callback: CallbackQuery) -> None:
    await callback.answer()
    await send_image_folder_or_text(callback.message.chat.id, PROMOS_DIR, PROMO_TEXT)


@router.message(F.text == "📍 Клуб")
async def menu_club(message: Message) -> None:
    await message.answer(
        f"📍 Адрес: {CLUB_ADDRESS}\n"
        f"📞 Телефон: {CLUB_PHONE}\n"
        f"🕒 Часы работы: {CLUB_HOURS}"
    )
    if CLUB_LATITUDE and CLUB_LONGITUDE:
        try:
            await message.answer_location(
                latitude=float(CLUB_LATITUDE), longitude=float(CLUB_LONGITUDE)
            )
        except ValueError:
            logging.warning("некорректные CLUB_LATITUDE/CLUB_LONGITUDE")


@router.message(F.text == "🧾 Прайс")
async def menu_price(message: Message) -> None:
    photo_path = os.path.join(os.path.dirname(__file__), "price.jpg")
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
        await message.answer(f"⚠️ Этот код уже был погашен {used_at}.\nТип бонуса: {label}")
        return

    label = BONUS_LABELS.get(row["bonus_type"], row["bonus_type"])
    reply = f"✅ Бонус активирован!\nТип: {label}\nID гостя: {row['telegram_id']}"

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


@router.callback_query(F.data == "review_done")
async def cb_review_done(callback: CallbackQuery) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    if db_has_review_claimed(user_id):
        await callback.message.answer("Бонус за отзыв уже был выдан раньше, спасибо ещё раз! 🙏")
        return
    db_mark_review_claimed(user_id)
    code = db_create_bonus(user_id, "review")
    await callback.message.answer(f"{REVIEW_BONUS_TEXT}\n\n🔑 Код бонуса: {code}")


# ---------- ФОНОВАЯ ЗАДАЧА: НАПОМИНАНИЕ ЧЕРЕЗ N ДНЕЙ ПОСЛЕ ПОДПИСКИ ----------
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
        await asyncio.sleep(3600)  # проверяем раз в час


async def review_loop() -> None:
    while True:
        try:
            for tg_id in db_due_for_review(REVIEW_DELAY_HOURS):
                try:
                    await bot.send_message(tg_id, REVIEW_PROMPT_TEXT, reply_markup=REVIEW_KB)
                except Exception:
                    logging.warning("не удалось отправить запрос отзыва %s", tg_id)
                db_mark_review_prompted(tg_id)
                await asyncio.sleep(0.1)
        except Exception:
            logging.exception("ошибка в review_loop")
        await asyncio.sleep(3600)  # проверяем раз в час


# ---------- ЗАПУСК ----------
async def main() -> None:
    db_init()
    asyncio.create_task(reminder_loop())
    asyncio.create_task(review_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
