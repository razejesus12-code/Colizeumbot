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


def env_pair(base: str, default_ru: str, default_uz: str) -> dict[str, str]:
    """Читает {base}_RU/{base}_UZ из переменных окружения. Для обратной совместимости
    также проверяет старое имя {base} без суффикса как значение для русского."""
    ru = os.environ.get(f"{base}_RU", os.environ.get(base, default_ru))
    uz = os.environ.get(f"{base}_UZ", default_uz)
    return {"ru": ru, "uz": uz}


BONUS_TEXT = env_pair(
    "BONUS_TEXT",
    "Спасибо за подписку! 🎁\n\n"
    "Твой бонус: +20% к следующему пополнению баланса.\n"
    "Покажи это сообщение администратору на стойке в течение 7 дней.",
    "Obuna uchun rahmat! 🎁\n\n"
    "Bonusing: keyingi balans to'ldirishga +20%.\n"
    "Ushbu xabarni administratorga peshtaxtada 7 kun ichida ko'rsat.",
)
DAYTIME_BONUS_TEXT = env_pair(
    "DAYTIME_BONUS_TEXT",
    "Спасибо за подписку! ☀️🎁\n\n"
    "Сейчас будний день — держи усиленный бонус: +30% к следующему пополнению баланса,\n"
    "если придёшь сегодня с 10:00 до 17:00.\n"
    "Покажи это сообщение администратору на стойке.",
    "Obuna uchun rahmat! ☀️🎁\n\n"
    "Hozir ish kuni — kuchaytirilgan bonusni ol: keyingi balans to'ldirishga +30%,\n"
    "agar bugun soat 10:00 dan 17:00 gacha kelsang.\n"
    "Ushbu xabarni administratorga peshtaxtada ko'rsat.",
)
REFERRER_BONUS_TEXT = env_pair(
    "REFERRER_BONUS_TEXT",
    "Твой друг присоединился по твоей ссылке! 🙌\n"
    "Бонус тебе: +30% к следующему пополнению баланса.\n"
    "Покажи это сообщение администратору на стойке.",
    "Do'sting sening havolang orqali qo'shildi! 🙌\n"
    "Senga bonus: keyingi balans to'ldirishga +30%.\n"
    "Ushbu xabarni administratorga peshtaxtada ko'rsat.",
)
REFERRED_EXTRA_TEXT = env_pair(
    "REFERRED_EXTRA_TEXT",
    "\n\n🙌 Ты пришёл по приглашению друга — держи ещё +10% сверху к бонусу выше!",
    "\n\n🙌 Sen do'st taklifi bilan keldingiz — yuqoridagi bonusga yana +10% ustama!",
)
REMINDER_TEXT = env_pair(
    "REMINDER_TEXT",
    "Давно не виделись! 👋\n\n"
    "Держи бонус на возвращение: +20% к следующему пополнению баланса.\n"
    "Покажи это сообщение администратору на стойке в течение 5 дней.",
    "Ancha ko'rishmadik! 👋\n\n"
    "Qaytganing uchun bonus: keyingi balans to'ldirishga +20%.\n"
    "Ushbu xabarni administratorga peshtaxtada 5 kun ichida ko'rsat.",
)
REMINDER_DELAY_DAYS = int(os.environ.get("REMINDER_DELAY_DAYS", "3"))

CLUB_ADDRESS = os.environ.get("CLUB_ADDRESS", "уточняется — впишите адрес в переменную CLUB_ADDRESS")
CLUB_PHONE = os.environ.get("CLUB_PHONE", "уточняется — впишите телефон в переменную CLUB_PHONE")
CLUB_HOURS = os.environ.get("CLUB_HOURS", "уточняется — впишите часы работы в переменную CLUB_HOURS")
CLUB_LATITUDE = os.environ.get("CLUB_LATITUDE", "")
CLUB_LONGITUDE = os.environ.get("CLUB_LONGITUDE", "")

PROMO_TEXT = env_pair(
    "PROMO_TEXT",
    "Актуальные акции скоро появятся здесь 🎉\nСледи за обновлениями в этом чате.",
    "Dolzarb aksiyalar tez orada shu yerda paydo bo'ladi 🎉\nUshbu chatdagi yangilanishlarni kuzatib bor.",
)
PACKAGES_TEXT = env_pair(
    "PACKAGES_TEXT",
    "🔥 Выгодные пакеты\n\n"
    "☀️ Standard (ROG периферия):\n"
    "🕗 Утро 3 часа (08:00-11:00) — 25 000 UZS\n"
    "🕚 День 3 часа (11:00-15:00) — 35 000 UZS\n\n"
    "🎮 Bootcamp (LOGITECH периферия, 5 игровых мест):\n"
    "🕗 Утренний пакет 3 часа (08:00-11:00) — 35 000 UZS\n"
    "🕚 Дневной пакет 3 часа (11:00-15:00) — 50 000 UZS\n\n"
    "Полный прайс по всем залам — кнопка 🧾 Прайс",
    "🔥 Foydali paketlar\n\n"
    "☀️ Standard (ROG periferiya):\n"
    "🕗 Ertalabki 3 soat (08:00-11:00) — 25 000 UZS\n"
    "🕚 Kunduzgi 3 soat (11:00-15:00) — 35 000 UZS\n\n"
    "🎮 Bootcamp (LOGITECH periferiya, 5 o'yin joyi):\n"
    "🕗 Ertalabki paket 3 soat (08:00-11:00) — 35 000 UZS\n"
    "🕚 Kunduzgi paket 3 soat (11:00-15:00) — 50 000 UZS\n\n"
    "Barcha zallar bo'yicha to'liq narxnoma — 🧾 Narxnoma tugmasi",
)
HOOKAH_TEXT = env_pair(
    "HOOKAH_TEXT",
    "💨 Кальян в нашем клубе\n\n"
    "Будни до 17:00 — 180 000 UZS\n"
    "Будни после 17:00 — 200 000 UZS\n"
    "Выходные — 200 000 UZS",
    "💨 Klubimizda kalyan\n\n"
    "Ish kunlari 17:00 gacha — 180 000 UZS\n"
    "Ish kunlari 17:00 dan keyin — 200 000 UZS\n"
    "Dam olish kunlari — 200 000 UZS",
)

DB_PATH = os.environ.get("DB_PATH", "subscribers.db")
TASHKENT_TZ = ZoneInfo("Asia/Tashkent")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROMOS_DIR = os.path.join(BASE_DIR, "promos")
PACKAGES_DIR = os.path.join(BASE_DIR, "packages")
HOOKAH_DIR = os.path.join(BASE_DIR, "hookah")

# буквы/цифры без похожих друг на друга символов (0/O, 1/I/L), чтобы код было легко читать вслух
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

# ---------- админские подписи бонусов (всегда на русском - ими пользуются только админы) ----------
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
TIER_SILVER_TEXT = env_pair(
    "TIER_SILVER_TEXT",
    "🥈 Поздравляем, ты получил статус Серебряный гость!\n"
    "Бонус: +15% к следующему пополнению баланса.",
    "🥈 Tabriklaymiz, sen Kumush mehmon statusiga erishding!\n"
    "Bonus: keyingi balans to'ldirishga +15%.",
)
TIER_GOLD_TEXT = env_pair(
    "TIER_GOLD_TEXT",
    "🥇 Поздравляем, ты получил статус Золотой гость!\n"
    "Бонус: +25% к следующему пополнению баланса.\n"
    "Плюс приоритет на бронирование любимого места.",
    "🥇 Tabriklaymiz, sen Oltin mehmon statusiga erishding!\n"
    "Bonus: keyingi balans to'ldirishga +25%.\n"
    "Qo'shimcha ravishda sevimli joyingizni band qilishda ustuvorlik.",
)
TIER_LABELS = {"": "Без статуса", "silver": "🥈 Серебряный", "gold": "🥇 Золотой"}  # для админ /vip
GUEST_TIER_LABELS = {
    "ru": {"": "Без статуса", "silver": "🥈 Серебряный", "gold": "🥇 Золотой"},
    "uz": {"": "Statussiz", "silver": "🥈 Kumush", "gold": "🥇 Oltin"},
}

FEEDBACK_DELAY_HOURS = int(os.environ.get("FEEDBACK_DELAY_HOURS", "2"))
FEEDBACK_PROMPT_TEXT = env_pair(
    "FEEDBACK_PROMPT_TEXT",
    "Как прошёл твой визит сегодня? 🎮\n"
    "Будем рады короткой оценке от 1 до 5 — это помогает нам стать лучше.",
    "Bugungi tashrifing qanday o'tdi? 🎮\n"
    "1 dan 5 gacha qisqa baho bersang xursand bo'lamiz — bu bizga yaxshilanishga yordam beradi.",
)

REVIEW_LINK_2GIS = os.environ.get("REVIEW_LINK_2GIS", "")
REVIEW_LINK_GOOGLE = os.environ.get("REVIEW_LINK_GOOGLE", "")
REVIEW_LINK_YANDEX = os.environ.get("REVIEW_LINK_YANDEX", "")
REVIEW_PROMPT_TEXT = env_pair(
    "REVIEW_PROMPT_TEXT",
    "Оставь отзыв — получи баллы на баланс! 🎁\n\n"
    f"📝 Без фото — {REVIEW_POINTS_NO_PHOTO} баллов\n"
    f"📸 С фото (интерьеры клуба или ты в клубе) — {REVIEW_POINTS_PHOTO} баллов\n\n"
    "После того как оставишь отзыв, выбери ниже, какой именно ты оставил:",
    "Sharh qoldir — balansga ball ol! 🎁\n\n"
    f"📝 Rasmsiz — {REVIEW_POINTS_NO_PHOTO} ball\n"
    f"📸 Rasm bilan (klub interyeri yoki sen klubda) — {REVIEW_POINTS_PHOTO} ball\n\n"
    "Sharh qoldirgach, qaysi turini qoldirganingni tanla:",
)

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# временное хранилище "кто по чьей ссылке идёт регистрироваться" и "какой язык выбрал до подписки"
# (живёт только пока бот не перезапущен - этого достаточно для короткого пути /start -> контакт)
PENDING_REFERRALS: dict[int, int] = {}
PENDING_LANGUAGE: dict[int, str] = {}

# ---------- ФИКСИРОВАННЫЕ ТЕКСТЫ ИНТЕРФЕЙСА (RU/UZ) ----------
UI = {
    "ru": {
        "start_greeting": (
            "Привет! Это бот клуба Colizeum Tashkent City. 🎮\n\n"
            "Номер телефона нужен только для того, чтобы начислять тебе бонусы "
            "и не пропускать акции клуба — никуда, кроме нашей базы, он не передаётся.\n\n"
            "Поделись номером, чтобы получить бонус:"
        ),
        "share_phone_button": "📱 Отправить номер телефона",
        "already_subscribed": "Ты уже с нами! 🎮 Вот меню:",
        "language_changed": "Готово! Теперь общаемся на русском 🇷🇺",
        "contact_guard": "Пожалуйста, отправь именно свой номер телефона 🙂",
        "stop_message": "Ты отписан(а) от рассылки. Если захочешь вернуться — просто нажми /start.",
        "bonus_code_label": "🔑 Код бонуса:",
        "balance_stub": (
            "Бот пока не подключён к кассовой системе клуба, поэтому точный баланс "
            "не покажет 🙏\nУзнать баланс можно у администратора на стойке."
        ),
        "promo_prompt": "Выбери, что интересно:",
        "club_info": "📍 Адрес: {address}\n📞 Телефон: {phone}\n🕒 Часы работы: {hours}",
        "price_unavailable": "Прайс временно недоступен, уточните у администратора 🙏",
        "price_caption": "Актуальный прайс-лист 🧾",
        "invite_need_subscribe": "Сначала подпишись через /start, потом сможешь приглашать друзей 🙂",
        "invite_text": (
            "Приглашай друзей и получай бонус за каждого! 🙌\n\n"
            "Твоя ссылка:\n{link}\n\n"
            "Приглашено друзей: {count}\n\n"
            "Когда друг перейдёт по ссылке и поделится номером — вы оба получите бонус."
        ),
        "checkin_need_subscribe": "Сначала подпишись через /start 🙂",
        "checkin_text": (
            "Покажи этот код администратору, чтобы засчитать визит 📍\n\n"
            "🔑 Код: {code}\n\n"
            "Так мы отслеживаем твои визиты для статуса постоянного гостя 🏆"
        ),
        "status_need_subscribe": "Сначала подпишись через /start 🙂",
        "status_max": "Ты уже на максимальном статусе — так держать! 🏆",
        "status_progress_gold": "До статуса 🥇 Золотой осталось визитов: {left}",
        "status_progress_silver": "До статуса 🥈 Серебряный осталось визитов: {left}",
        "status_text": (
            "💎 Твой статус: {tier}\n"
            "Подтверждённых визитов: {visits}\n\n"
            "{progress}\n\n"
            "Визит засчитывается, когда администратор гасит твой код из кнопки «✅ Я в клубе»."
        ),
        "lottery_need_subscribe": "Сначала подпишись через /start 🙂",
        "lottery_already": "Ты уже крутил барабан сегодня 🎰\nОдин спин в день — приходи завтра!",
        "lottery_jackpot": "🎉 ДЖЕКПОТ! 777 🎰\nБонус: {amount}\n\n🔑 Код бонуса: {code}",
        "lottery_win": "🎉 Выигрыш! Три одинаковых символа!\nБонус: {amount}\n\n🔑 Код бонуса: {code}",
        "lottery_lose": "Почти! В этот раз не повезло 😅\nПриходи завтра, будет ещё один спин!",
        "review_screenshot_ask": (
            "Пришли, пожалуйста, скриншот своего отзыва (просто фото экрана с отзывом) — "
            "и я сразу выдам код бонуса. Это нужно, чтобы администратор мог сверить отзыв.\n\n"
            "Передумал? Напиши /cancel"
        ),
        "review_already": "Бонус за отзыв уже был выдан раньше, спасибо ещё раз! 🙏",
        "review_thanks": "🙏 Спасибо за отзыв!\nБонус: {amount}\n\n🔑 Код бонуса: {code}",
        "review_wrong": "Пожалуйста, пришли именно скриншот (фото) своего отзыва 🙏\nИли напиши /cancel, чтобы отменить.",
        "review_cancelled": "Отменено.",
        "feedback_thanks_click": "Спасибо за оценку! 🙌",
        "feedback_thanks_final": "Спасибо, что поделился впечатлением! 🙏",
        "choose_language": "Выбери язык общения / Tilni tanlang 🌐",
    },
    "uz": {
        "start_greeting": (
            "Salom! Bu Colizeum Tashkent City klubining boti. 🎮\n\n"
            "Telefon raqami faqat senga bonuslar berish va klub aksiyalarini o'tkazib "
            "yubormasliging uchun kerak — u faqat bizning bazamizda saqlanadi.\n\n"
            "Bonus olish uchun raqamingni ulash:"
        ),
        "share_phone_button": "📱 Telefon raqamni yuborish",
        "already_subscribed": "Sen allaqachon biz bilansan! 🎮 Mana menyu:",
        "language_changed": "Tayyor! Endi o'zbek tilida gaplashamiz 🇺🇿",
        "contact_guard": "Iltimos, aynan o'zingning telefon raqamingni yubor 🙂",
        "stop_message": "Sen tarqatmadan chiqarilding. Agar qaytmoqchi bo'lsang — /start tugmasini bosgin.",
        "bonus_code_label": "🔑 Bonus kodi:",
        "balance_stub": (
            "Bot hozircha klubning kassa tizimiga ulanmagan, shuning uchun aniq balansni "
            "ko'rsata olmaydi 🙏\nBalansni administratordan peshtaxtada bilib olishing mumkin."
        ),
        "promo_prompt": "Nima qiziqtiradi, tanla:",
        "club_info": "📍 Manzil: {address}\n📞 Telefon: {phone}\n🕒 Ish vaqti: {hours}",
        "price_unavailable": "Narxnoma vaqtincha mavjud emas, administratordan so'rang 🙏",
        "price_caption": "Dolzarb narxnoma 🧾",
        "invite_need_subscribe": "Avval /start orqali ro'yxatdan o't, keyin do'stlaringni taklif qila olasan 🙂",
        "invite_text": (
            "Do'stlaringni taklif qil va har biri uchun bonus ol! 🙌\n\n"
            "Sening havolang:\n{link}\n\n"
            "Taklif qilingan do'stlar: {count}\n\n"
            "Do'sting havola orqali o'tib, raqamini ulasa — ikkalangiz ham bonus olasiz."
        ),
        "checkin_need_subscribe": "Avval /start orqali ro'yxatdan o't 🙂",
        "checkin_text": (
            "Tashrifni hisobga olish uchun ushbu kodni administratorga ko'rsat 📍\n\n"
            "🔑 Kod: {code}\n\n"
            "Shu tarzda doimiy mehmon statusi uchun tashriflaringni kuzatamiz 🏆"
        ),
        "status_need_subscribe": "Avval /start orqali ro'yxatdan o't 🙂",
        "status_max": "Sen allaqachon eng yuqori statusdasan — shunday davom et! 🏆",
        "status_progress_gold": "🥇 Oltin statusigacha qolgan tashriflar: {left}",
        "status_progress_silver": "🥈 Kumush statusigacha qolgan tashriflar: {left}",
        "status_text": (
            "💎 Sening statusing: {tier}\n"
            "Tasdiqlangan tashriflar: {visits}\n\n"
            "{progress}\n\n"
            "Tashrif «✅ Men klubdaman» tugmasidagi kodingni administrator tasdiqlaganda hisoblanadi."
        ),
        "lottery_need_subscribe": "Avval /start orqali ro'yxatdan o't 🙂",
        "lottery_already": "Sen bugun g'ildirakni allaqachon aylantirding 🎰\nKuniga bitta urinish — ertaga kel!",
        "lottery_jackpot": "🎉 JEKPOT! 777 🎰\nBonus: {amount}\n\n🔑 Bonus kodi: {code}",
        "lottery_win": "🎉 Yutuq! Uchta bir xil belgi!\nBonus: {amount}\n\n🔑 Bonus kodi: {code}",
        "lottery_lose": "Deyarli! Bu safar omad kulmadi 😅\nErtaga kel, yana bitta urinish bo'ladi!",
        "review_screenshot_ask": (
            "Iltimos, sharhingning skrinshotini yubor (ekran rasmi) — va men darhol bonus "
            "kodini beraman. Bu administrator sharhni tekshira olishi uchun kerak.\n\n"
            "Fikringdan qaytdingmi? /cancel deb yoz"
        ),
        "review_already": "Sharh uchun bonus avvalroq berilgan, yana rahmat! 🙏",
        "review_thanks": "🙏 Sharh uchun rahmat!\nBonus: {amount}\n\n🔑 Bonus kodi: {code}",
        "review_wrong": "Iltimos, aynan sharhingning skrinshotini (rasmini) yubor 🙏\nYoki bekor qilish uchun /cancel deb yoz.",
        "review_cancelled": "Bekor qilindi.",
        "feedback_thanks_click": "Baho uchun rahmat! 🙌",
        "feedback_thanks_final": "Fikringni bildirganing uchun rahmat! 🙏",
        "choose_language": "Выбери язык общения / Tilni tanlang 🌐",
    },
}

BTN = {
    "balance": {"ru": "💰 Баланс", "uz": "💰 Balans"},
    "promo": {"ru": "🎉 Акции", "uz": "🎉 Aksiyalar"},
    "club": {"ru": "📍 Клуб", "uz": "📍 Klub"},
    "invite": {"ru": "👥 Пригласить друга", "uz": "👥 Do'stni taklif qilish"},
    "price": {"ru": "🧾 Прайс", "uz": "🧾 Narxnoma"},
    "checkin": {"ru": "✅ Я в клубе", "uz": "✅ Men klubdaman"},
    "status": {"ru": "💎 Мой статус", "uz": "💎 Mening statusim"},
    "lottery": {"ru": "🎰 Лототрон", "uz": "🎰 Omad g'ildiragi"},
    "language": {"ru": "🌐 Язык", "uz": "🌐 Til"},
}

PROMO_BTN = {
    "packages": {"ru": "🔥 Выгодные пакеты", "uz": "🔥 Foydali paketlar"},
    "hookah": {"ru": "💨 Кальян", "uz": "💨 Kalyan"},
    "review": {"ru": "⭐ Отзыв за бонус", "uz": "⭐ Sharh uchun bonus"},
    "general": {"ru": "🎁 Все акции", "uz": "🎁 Barcha aksiyalar"},
}

REVIEW_LINK_LABELS = {
    "2gis": {"ru": "📍 Оставить отзыв в 2GIS", "uz": "📍 2GIS'da sharh qoldirish"},
    "google": {"ru": "🗺 Оставить отзыв в Google Maps", "uz": "🗺 Google Maps'da sharh qoldirish"},
    "yandex": {"ru": "🟡 Оставить отзыв в Яндекс Картах", "uz": "🟡 Yandex Xaritada sharh qoldirish"},
}
REVIEW_CLAIM_LABELS = {
    "no_photo": {"ru": f"✅ Без фото ({REVIEW_POINTS_NO_PHOTO})", "uz": f"✅ Rasmsiz ({REVIEW_POINTS_NO_PHOTO})"},
    "photo": {"ru": f"✅ С фото ({REVIEW_POINTS_PHOTO})", "uz": f"✅ Rasm bilan ({REVIEW_POINTS_PHOTO})"},
}

LANG_PICK_KB = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"),
            InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang_uz"),
        ]
    ]
)

FEEDBACK_KB = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text=str(i), callback_data=f"feedback_{i}") for i in range(1, 6)]
    ]
)


def get_phone_share_kb(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=UI[lang]["share_phone_button"], request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_main_menu_kb(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN["balance"][lang]), KeyboardButton(text=BTN["promo"][lang])],
            [KeyboardButton(text=BTN["club"][lang]), KeyboardButton(text=BTN["invite"][lang])],
            [KeyboardButton(text=BTN["price"][lang]), KeyboardButton(text=BTN["checkin"][lang])],
            [KeyboardButton(text=BTN["status"][lang]), KeyboardButton(text=BTN["lottery"][lang])],
            [KeyboardButton(text=BTN["language"][lang])],
        ],
        resize_keyboard=True,
    )


def get_promo_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=PROMO_BTN["packages"][lang], callback_data="promo_packages")],
            [InlineKeyboardButton(text=PROMO_BTN["hookah"][lang], callback_data="promo_hookah")],
            [InlineKeyboardButton(text=PROMO_BTN["review"][lang], callback_data="promo_review")],
            [InlineKeyboardButton(text=PROMO_BTN["general"][lang], callback_data="promo_general")],
        ]
    )


def get_review_kb(lang: str) -> InlineKeyboardMarkup:
    buttons = []
    if REVIEW_LINK_2GIS:
        buttons.append([InlineKeyboardButton(text=REVIEW_LINK_LABELS["2gis"][lang], url=REVIEW_LINK_2GIS)])
    if REVIEW_LINK_GOOGLE:
        buttons.append([InlineKeyboardButton(text=REVIEW_LINK_LABELS["google"][lang], url=REVIEW_LINK_GOOGLE)])
    if REVIEW_LINK_YANDEX:
        buttons.append([InlineKeyboardButton(text=REVIEW_LINK_LABELS["yandex"][lang], url=REVIEW_LINK_YANDEX)])
    buttons.append(
        [InlineKeyboardButton(text=REVIEW_CLAIM_LABELS["no_photo"][lang], callback_data="review_done_no_photo")]
    )
    buttons.append(
        [InlineKeyboardButton(text=REVIEW_CLAIM_LABELS["photo"][lang], callback_data="review_done_photo")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def btn_variants(key: str) -> set[str]:
    return set(BTN[key].values())


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
            reminder_sent INTEGER DEFAULT 0,
            language TEXT DEFAULT 'ru'
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
        ("last_spin_date", "TEXT"),
        ("language", "TEXT DEFAULT 'ru'"),
    ):
        try:
            conn.execute(f"ALTER TABLE subscribers ADD COLUMN {column} {coltype}")
        except sqlite3.OperationalError:
            pass  # колонка уже есть
    conn.commit()
    conn.close()


def db_add_subscriber(
    telegram_id: int,
    username: str,
    full_name: str,
    phone: str,
    referred_by: int | None,
    language: str = "ru",
) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT INTO subscribers (telegram_id, username, full_name, phone, joined_at, referred_by, reminder_sent, language)
        VALUES (?, ?, ?, ?, ?, ?, 0, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET phone=excluded.phone, language=excluded.language
        """,
        (telegram_id, username, full_name, phone, datetime.now().isoformat(), referred_by, language),
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


def db_get_language(telegram_id: int) -> str:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT language FROM subscribers WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()
    return row[0] if row and row[0] else "ru"


def db_set_language(telegram_id: int, lang: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE subscribers SET language = ? WHERE telegram_id = ?", (lang, telegram_id))
    conn.commit()
    conn.close()


def get_user_lang(telegram_id: int) -> str:
    if telegram_id in PENDING_LANGUAGE:
        return PENDING_LANGUAGE[telegram_id]
    return db_get_language(telegram_id)


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


def db_reset_review_claim(telegram_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE subscribers SET review_bonus_claimed = 0 WHERE telegram_id = ?", (telegram_id,)
    )
    conn.commit()
    conn.close()


def db_get_last_spin_date(telegram_id: int) -> str | None:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT last_spin_date FROM subscribers WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()
    return row[0] if row and row[0] else None


def db_set_last_spin_date(telegram_id: int, date_str: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE subscribers SET last_spin_date = ? WHERE telegram_id = ?", (date_str, telegram_id)
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


class ReviewState(StatesGroup):
    waiting_screenshot = State()


# ---------- ВСПОМОГАТЕЛЬНОЕ ----------
def get_bonus_text_and_type(lang: str) -> tuple[str, str]:
    """Днём в будни (10:00-17:00 по Ташкенту) - усиленный бонус, в остальное время - обычный."""
    now = datetime.now(TASHKENT_TZ)
    is_weekday = now.weekday() < 5  # 0=Пн ... 4=Пт
    is_daytime = 10 <= now.hour < 17
    if is_weekday and is_daytime:
        return DAYTIME_BONUS_TEXT[lang], "daytime"
    return BONUS_TEXT[lang], "welcome"


def get_referral_link(telegram_id: int) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=ref{telegram_id}"


# ---------- ОБРАБОТЧИКИ: ВЫБОР ЯЗЫКА ----------
@router.callback_query(F.data.in_({"lang_ru", "lang_uz"}))
async def cb_set_language(callback: CallbackQuery) -> None:
    await callback.answer()
    lang = "ru" if callback.data == "lang_ru" else "uz"
    user_id = callback.from_user.id

    if db_is_subscriber(user_id):
        db_set_language(user_id, lang)
        await callback.message.answer(UI[lang]["language_changed"], reply_markup=get_main_menu_kb(lang))
        return

    PENDING_LANGUAGE[user_id] = lang
    await callback.message.answer(UI[lang]["start_greeting"], reply_markup=get_phone_share_kb(lang))


@router.message(F.text.in_(btn_variants("language")))
async def menu_language(message: Message) -> None:
    await message.answer(UI[get_user_lang(message.from_user.id)]["choose_language"], reply_markup=LANG_PICK_KB)


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
        lang = db_get_language(user_id)
        await message.answer(UI[lang]["already_subscribed"], reply_markup=get_main_menu_kb(lang))
        return

    await message.answer("Выбери язык общения / Tilni tanlang 🌐", reply_markup=LANG_PICK_KB)


@router.message(F.contact)
async def handle_contact(message: Message) -> None:
    user_id = message.from_user.id
    lang = PENDING_LANGUAGE.get(user_id, "ru")
    contact: Contact = message.contact

    # защита: чтобы гость не мог отправить чужой контакт
    if contact.user_id and contact.user_id != user_id:
        await message.answer(UI[lang]["contact_guard"])
        return

    referrer_id = PENDING_REFERRALS.pop(user_id, None)
    PENDING_LANGUAGE.pop(user_id, None)

    db_add_subscriber(
        telegram_id=user_id,
        username=message.from_user.username or "",
        full_name=message.from_user.full_name,
        phone=contact.phone_number,
        referred_by=referrer_id,
        language=lang,
    )

    bonus_text, bonus_type = get_bonus_text_and_type(lang)
    code = db_create_bonus(user_id, bonus_type)
    bonus_text = f"{bonus_text}\n\n{UI[lang]['bonus_code_label']} {code}"

    if referrer_id:
        bonus_text += REFERRED_EXTRA_TEXT[lang]
        try:
            referrer_lang = db_get_language(referrer_id)
            referrer_code = db_create_bonus(referrer_id, "referrer")
            await bot.send_message(
                referrer_id,
                f"{REFERRER_BONUS_TEXT[referrer_lang]}\n\n{UI[referrer_lang]['bonus_code_label']} {referrer_code}",
            )
        except Exception:
            logging.warning("не удалось уведомить пригласившего %s", referrer_id)

    await message.answer(bonus_text, reply_markup=get_main_menu_kb(lang))


@router.message(Command("stop"))
async def cmd_stop(message: Message) -> None:
    user_id = message.from_user.id
    lang = db_get_language(user_id) if db_is_subscriber(user_id) else "ru"
    db_remove_subscriber(user_id)
    await message.answer(UI[lang]["stop_message"], reply_markup=ReplyKeyboardRemove())


# ---------- МЕНЮ ----------
@router.message(F.text.in_(btn_variants("balance")))
async def menu_balance(message: Message) -> None:
    lang = get_user_lang(message.from_user.id)
    await message.answer(UI[lang]["balance_stub"])


@router.message(F.text.in_(btn_variants("promo")))
async def menu_promo(message: Message) -> None:
    lang = get_user_lang(message.from_user.id)
    await message.answer(UI[lang]["promo_prompt"], reply_markup=get_promo_kb(lang))


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
    lang = get_user_lang(callback.from_user.id)
    await send_image_folder_or_text(callback.message.chat.id, PACKAGES_DIR, PACKAGES_TEXT[lang])


@router.callback_query(F.data == "promo_hookah")
async def cb_promo_hookah(callback: CallbackQuery) -> None:
    await callback.answer()
    lang = get_user_lang(callback.from_user.id)
    await send_image_folder_or_text(callback.message.chat.id, HOOKAH_DIR, HOOKAH_TEXT[lang])


@router.callback_query(F.data == "promo_review")
async def cb_promo_review(callback: CallbackQuery) -> None:
    await callback.answer()
    lang = get_user_lang(callback.from_user.id)
    await callback.message.answer(REVIEW_PROMPT_TEXT[lang], reply_markup=get_review_kb(lang))


@router.callback_query(F.data == "promo_general")
async def cb_promo_general(callback: CallbackQuery) -> None:
    await callback.answer()
    lang = get_user_lang(callback.from_user.id)
    await send_image_folder_or_text(callback.message.chat.id, PROMOS_DIR, PROMO_TEXT[lang])


@router.message(F.text.in_(btn_variants("club")))
async def menu_club(message: Message) -> None:
    lang = get_user_lang(message.from_user.id)
    await message.answer(
        UI[lang]["club_info"].format(address=CLUB_ADDRESS, phone=CLUB_PHONE, hours=CLUB_HOURS)
    )
    if CLUB_LATITUDE and CLUB_LONGITUDE:
        try:
            await message.answer_location(
                latitude=float(CLUB_LATITUDE), longitude=float(CLUB_LONGITUDE)
            )
        except ValueError:
            logging.warning("некорректные CLUB_LATITUDE/CLUB_LONGITUDE")


@router.message(F.text.in_(btn_variants("price")))
async def menu_price(message: Message) -> None:
    lang = get_user_lang(message.from_user.id)
    photo_path = os.path.join(BASE_DIR, "price.jpg")
    if not os.path.exists(photo_path):
        await message.answer(UI[lang]["price_unavailable"])
        return
    await message.answer_photo(FSInputFile(photo_path), caption=UI[lang]["price_caption"])


@router.message(F.text.in_(btn_variants("invite")))
@router.message(Command("invite"))
async def menu_invite(message: Message) -> None:
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    if not db_is_subscriber(user_id):
        await message.answer(UI[lang]["invite_need_subscribe"])
        return
    link = get_referral_link(user_id)
    count = db_referral_count(user_id)
    await message.answer(UI[lang]["invite_text"].format(link=link, count=count))


@router.message(F.text.in_(btn_variants("checkin")))
async def menu_checkin(message: Message) -> None:
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    if not db_is_subscriber(user_id):
        await message.answer(UI[lang]["checkin_need_subscribe"])
        return
    code = db_create_bonus(user_id, "checkin")
    await message.answer(UI[lang]["checkin_text"].format(code=code))


@router.message(F.text.in_(btn_variants("status")))
async def menu_status(message: Message) -> None:
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    if not db_is_subscriber(user_id):
        await message.answer(UI[lang]["status_need_subscribe"])
        return

    visits = db_get_visits(user_id)
    tier = db_get_tier(user_id)
    tier_label = GUEST_TIER_LABELS[lang].get(tier, tier)

    if tier == "gold":
        progress = UI[lang]["status_max"]
    elif tier == "silver":
        left = max(TIER_GOLD_VISITS - visits, 0)
        progress = UI[lang]["status_progress_gold"].format(left=left)
    else:
        left = max(TIER_SILVER_VISITS - visits, 0)
        progress = UI[lang]["status_progress_silver"].format(left=left)

    await message.answer(UI[lang]["status_text"].format(tier=tier_label, visits=visits, progress=progress))


@router.message(F.text.in_(btn_variants("lottery")))
async def menu_lottery(message: Message) -> None:
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    if not db_is_subscriber(user_id):
        await message.answer(UI[lang]["lottery_need_subscribe"])
        return

    today = datetime.now(TASHKENT_TZ).date().isoformat()
    if db_get_last_spin_date(user_id) == today:
        await message.answer(UI[lang]["lottery_already"])
        return

    db_set_last_spin_date(user_id, today)
    dice_msg = await message.answer_dice(emoji="🎰")
    value = dice_msg.dice.value
    await asyncio.sleep(4)  # даём анимации доиграть

    if value == 64:
        code = db_create_bonus(user_id, "lottery_jackpot")
        amount = BONUS_AMOUNTS.get("lottery_jackpot")
        await message.answer(UI[lang]["lottery_jackpot"].format(amount=amount, code=code))
    elif value in (1, 22, 43):
        code = db_create_bonus(user_id, "lottery_win")
        amount = BONUS_AMOUNTS.get("lottery_win")
        await message.answer(UI[lang]["lottery_win"].format(amount=amount, code=code))
    else:
        await message.answer(UI[lang]["lottery_lose"])


# ---------- ОБРАБОТЧИКИ: АДМИН (всегда на русском) ----------
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
        await message.answer(
            f"⚠️ Этот код уже был погашен {used_at}.\nТип бонуса: {label}{amount_line}"
        )
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
            guest_lang = db_get_language(guest_id)
            tier_text = (TIER_GOLD_TEXT if new_tier == "gold" else TIER_SILVER_TEXT)[guest_lang]
            tier_code = db_create_bonus(guest_id, f"tier_{new_tier}")
            try:
                await bot.send_message(
                    guest_id, f"{tier_text}\n\n{UI[guest_lang]['bonus_code_label']} {tier_code}"
                )
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


@router.callback_query(F.data.in_({"review_done_no_photo", "review_done_photo"}))
async def cb_review_done(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)

    if db_has_review_claimed(user_id):
        await callback.message.answer(UI[lang]["review_already"])
        return

    bonus_type = "review_photo" if callback.data == "review_done_photo" else "review_no_photo"
    await state.update_data(review_bonus_type=bonus_type)
    await state.set_state(ReviewState.waiting_screenshot)
    await callback.message.answer(UI[lang]["review_screenshot_ask"])


@router.message(ReviewState.waiting_screenshot, F.photo)
async def review_screenshot_received(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    data = await state.get_data()
    bonus_type = data.get("review_bonus_type", "review_no_photo")
    await state.clear()

    if db_has_review_claimed(user_id):
        await message.answer(UI[lang]["review_already"])
        return

    db_mark_review_claimed(user_id)
    code = db_create_bonus(user_id, bonus_type)
    amount = BONUS_AMOUNTS.get(bonus_type, "")
    await message.answer(UI[lang]["review_thanks"].format(amount=amount, code=code))

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
    lang = get_user_lang(message.from_user.id)
    if (message.text or "").strip().lower() == "/cancel":
        await state.clear()
        await message.answer(UI[lang]["review_cancelled"])
        return
    await message.answer(UI[lang]["review_wrong"])


@router.callback_query(F.data.startswith("feedback_"))
async def cb_feedback(callback: CallbackQuery) -> None:
    lang = get_user_lang(callback.from_user.id)
    await callback.answer(UI[lang]["feedback_thanks_click"])
    rating = callback.data.split("_", 1)[1]
    user = callback.from_user

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"📝 Оценка визита: {rating}/5\nГость: {user.full_name} (id {user.id})",
            )
        except Exception:
            logging.warning("не удалось переслать оценку админу %s", admin_id)

    await callback.message.answer(UI[lang]["feedback_thanks_final"])


# ---------- ФОНОВАЯ ЗАДАЧА: НАПОМИНАНИЕ ЧЕРЕЗ N ДНЕЙ ПОСЛЕ ПОДПИСКИ ----------
async def reminder_loop() -> None:
    while True:
        try:
            for tg_id in db_due_for_reminder(REMINDER_DELAY_DAYS):
                try:
                    lang = db_get_language(tg_id)
                    code = db_create_bonus(tg_id, "reminder")
                    await bot.send_message(
                        tg_id, f"{REMINDER_TEXT[lang]}\n\n{UI[lang]['bonus_code_label']} {code}"
                    )
                except Exception:
                    logging.warning("не удалось отправить напоминание %s", tg_id)
                db_mark_reminder_sent(tg_id)
                await asyncio.sleep(0.1)
        except Exception:
            logging.exception("ошибка в reminder_loop")
        await asyncio.sleep(3600)  # проверяем раз в час


async def feedback_loop() -> None:
    while True:
        try:
            for tg_id in db_due_for_feedback(FEEDBACK_DELAY_HOURS):
                try:
                    lang = db_get_language(tg_id)
                    await bot.send_message(tg_id, FEEDBACK_PROMPT_TEXT[lang], reply_markup=FEEDBACK_KB)
                except Exception:
                    logging.warning("не удалось отправить запрос обратной связи %s", tg_id)
                db_mark_feedback_prompted(tg_id)
                await asyncio.sleep(0.1)
        except Exception:
            logging.exception("ошибка в feedback_loop")
        await asyncio.sleep(3600)  # проверяем раз в час


# ---------- ЗАПУСК ----------
async def main() -> None:
    db_init()
    asyncio.create_task(reminder_loop())
    asyncio.create_task(feedback_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
