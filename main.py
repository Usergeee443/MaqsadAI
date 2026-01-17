#!/usr/bin/env python3
"""
Balans AI Bot - Moliyaviy yordamchi
Faqat moliyaviy funksiyalar
"""

import asyncio
from typing import Optional, Union
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, Contact, WebAppInfo, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from config import (
    BOT_TOKEN,
    TARIFFS,
    CATEGORIES,
    TARIFF_PRICES,
    DISCOUNT_RATES,
    PAYMENT_METHODS,
    TELEGRAM_PAYMENT_PROVIDER_TOKEN,
    STARS_ENABLED,
    STARS_SOM_PER_STAR,
    SPEECH_MODELS,
    ACTIVE_SPEECH_MODELS,
    FREE_TRIAL_ENABLED,
    PLUS_PACKAGES,
    PAYMENT_PLUS_WEBAPP_URL,
    PAYMENT_PRO_WEBAPP_URL,
)
from database import db
from financial_module import FinancialModule
from reports_module import ReportsModule
from ai_chat import AIChat, AIChatFree
from warehouse_module import WarehouseModule
from business_module import BusinessModule, BusinessStates, create_business_module

# Bot va dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Modullar
financial_module = FinancialModule()
reports_module = ReportsModule()
ai_chat = AIChat(db=db)
ai_chat_free = AIChatFree(db=db)
warehouse_module = WarehouseModule(db=db, ai_chat=ai_chat)
business_module = create_business_module(db=db, ai_chat=ai_chat)

# Admin panelga ruxsat berilgan ID
ADMIN_USER_ID = 6429299277


# Sana formatlash (uzbekcha oy)
def _format_date_uz(dt_obj) -> str:
    try:
        if not dt_obj:
            return '—'
        months = {
            1: "Yanvar", 2: "Fevral", 3: "Mart", 4: "Aprel", 5: "May", 6: "Iyun",
            7: "Iyul", 8: "Avgust", 9: "Sentyabr", 10: "Oktyabr", 11: "Noyabr", 12: "Dekabr"
        }
        return f"{dt_obj.day}-{months.get(dt_obj.month, dt_obj.strftime('%B'))}, {dt_obj.year}"
    except Exception:
        if not dt_obj:
            return '—'
        return dt_obj.strftime('%d.%m.%Y')

PREMIUM_TARIFFS = {
    'PLUS', 'PRO', 'FAMILY', 'FAMILY_PLUS', 'FAMILY_PRO',
    'BUSINESS', 'BUSINESS_PLUS', 'BUSINESS_MAX'
}

# To'lov jarayonida ikki marta invoice yuborilishini bloklash uchun oddiy in-memory holat
from time import time as _now
PENDING_PLUS_PAYMENTS = {}      # user_id -> ts
PENDING_BUSINESS_PAYMENTS = {}  # user_id -> ts
LAST_INVOICE_MESSAGE_ID = {}    # user_id -> message_id (oxirgi yuborilgan invoice)
LAST_PAYMENT_INFO_MESSAGE_ID = {}  # user_id -> message_id (tanlangan to'lov usuli ko'rsatilgan xabar)
LAST_GREETING_MESSAGE_ID = {}      # user_id -> message_id ("Tanishganimdan Xursandman" xabari)
START_DEDUP_CACHE = {}             # user_id -> {"msg_id": int, "ts": float}

# Pending util (180s ichida faqat bitta invoice)
PENDING_TTL_SECONDS = 180

def _pending_is_active(storage: dict, user_id: int) -> bool:
    ts = storage.get(user_id)
    if not ts:
        return False
    if _now() - ts > PENDING_TTL_SECONDS:
        try:
            storage.pop(user_id, None)
        except Exception:
            pass
        return False
    return True

def _pending_add(storage: dict, user_id: int) -> None:
    storage[user_id] = _now()

def _pending_clear(storage: dict, user_id: int) -> None:
    try:
        storage.pop(user_id, None)
    except Exception:
        pass

# Admin blokini UserStates'dan keyinga ko'chirildi (quyida joylashgan)

# Tarif muddatini tekshirish va avtomatik Freega o‘tkazish
async def ensure_tariff_valid(user_id: int) -> None:
    try:
        user_data = await db.get_user_data(user_id)
        if not user_data:
            return
        current = user_data.get('tariff') or 'NONE'
        expires = user_data.get('tariff_expires_at')
        # Agar tariff_expires_at NULL bo'lsa, tarifni doimiy deb hisoblaymiz (masalan, BUSINESS)
        if current not in ('NONE', 'FREE') and expires is not None:
            # Agar muddat tugagan bo'lsa, tarifni deaktiv qilamiz
            from datetime import datetime as _dt
            if isinstance(expires, str):
                # MySQL connector qaytargan formatlarga ehtiyot chorasi
                try:
                    from dateutil import parser as _parser  # optional
                    expires_dt = _parser.parse(expires)
                except Exception:
                    expires_dt = _dt.fromisoformat(expires)
            else:
                expires_dt = expires
            if expires_dt and expires_dt < _dt.now():
                await db.execute_query(
                    "UPDATE users SET tariff = 'NONE', tariff_expires_at = NULL WHERE user_id = %s",
                    (user_id,)
                )
                # Aktiv obunalarni va Plus paketlarini ham deaktiv qilamiz
                try:
                    await db.execute_query(
                        "UPDATE user_subscriptions SET is_active = FALSE WHERE user_id = %s",
                        (user_id,)
                    )
                    await db.execute_query(
                        "UPDATE plus_package_purchases SET status = 'completed' WHERE user_id = %s AND expires_at IS NOT NULL AND expires_at <= NOW()",
                        (user_id,)
                    )
                except Exception as deactivate_err:
                    logging.error(f"Tarifni o'chirishda qo'shimcha xato: {deactivate_err}")
                # Foydalanuvchini xabardor qilish
                try:
                    await bot.send_message(
                        user_id,
                        "⏰ 3 kunlik bepul sinov muddati tugadi.\n\n"
                        "Tarifdan foydalanishni davom ettirish uchun mos tarifni tanlab to'lovni amalga oshiring."
                    )
                except Exception as notify_err:
                    logging.debug(f"Expire notification yuborilmadi: {notify_err}")
    except Exception as _e:
        logging.error(f"ensure_tariff_valid error: {_e}")

async def is_paid_active(user_id: int) -> bool:
    """Foydalanuvchi pullik tarifda va muddati tugamaganmi?"""
    try:
        user_data = await db.get_user_data(user_id)
        if not user_data:
            return False
        current = user_data.get('tariff') or 'NONE'
        if current in ('NONE', 'FREE'):
            return False
        expires = user_data.get('tariff_expires_at')
        if not expires:
            # Hech muddat yo'q — baribir pullik sifatida hisoblaymiz
            return True
        from datetime import datetime as _dt
        expires_dt = expires if not isinstance(expires, str) else _dt.fromisoformat(expires)
        return expires_dt > _dt.now()
    except Exception as _e:
        logging.error(f"is_paid_active error: {_e}")
        return False

# Tarif helperlari
def get_tariff_overview_text() -> str:
    return (
        "Balans AI sizga mos keladigan turli xil tariflarni taklif etadi. "
        "Shaxsiy byudjetingizni nazorat qilmoqchimisiz, oilaviy xarajatlarni boshqarmoqchimisiz yoki "
        "biznesingizni avtomatlashtirmoqchimisiz — bu yerda albatta sizga mos yechim bor.\n\n"
        "Quyidagi tariflardan birini tanlang 👇\n"
    )

def build_tariff_detail_keyboard(tariff_code: str, back_callback: str) -> InlineKeyboardMarkup:
    async def keyboard_for_user(user_id: int) -> InlineKeyboardMarkup:
        current = await get_user_tariff(user_id)
        if current == tariff_code and current not in ('NONE', 'FREE'):
            # Aktiv tarif: faqat orqaga tugmasi
            return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back_callback)]])
        
        # 3 kunlik sinov holatini tekshirish
        if tariff_code in FREE_TRIAL_ENABLED and FREE_TRIAL_ENABLED[tariff_code]:
            # Sinov yoqilgan - sinov tugmasi
            return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back_callback), InlineKeyboardButton(text="🆓 3 kun bepul sinov", callback_data=f"trial_tariff_{tariff_code}")]])
        else:
            # Sinov o'chirilgan - aktivlashtirish tugmasi
            return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back_callback), InlineKeyboardButton(text="🚀 Aktivlashtirish", callback_data=f"activate_{tariff_code}")]])

    # Fallback sync qurilishi (agar user_id konteksti yo'q bo'lsa)
    if tariff_code in FREE_TRIAL_ENABLED and FREE_TRIAL_ENABLED[tariff_code]:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back_callback), InlineKeyboardButton(text="🆓 3 kun bepul sinov", callback_data=f"trial_tariff_{tariff_code}")]])
    else:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back_callback), InlineKeyboardButton(text="🚀 Aktivlashtirish", callback_data=f"activate_{tariff_code}")]])

def build_main_tariff_keyboard() -> InlineKeyboardMarkup:
    # Compact keyboard - qatorlar orasidagi joy kamaytirildi
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Plus paketlar", callback_data="tariff_PLUS"), InlineKeyboardButton(text="Pro", callback_data="tariff_PRO")],
        [InlineKeyboardButton(text="Biznes tariflari", callback_data="tariff_BUSINESS_MENU"), InlineKeyboardButton(text="Oila tariflari", callback_data="tariff_FAMILY_MENU")]
    ])

def get_family_tariff_keyboard() -> InlineKeyboardMarkup:
    # Compact keyboard - qatorlar orasidagi joy kamaytirildi
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Oila", callback_data="tariff_FAMILY"), InlineKeyboardButton(text="Oila Plus", callback_data="tariff_FAMILY_PLUS")],
        [InlineKeyboardButton(text="Oila Max", callback_data="tariff_FAMILY_MAX")]
    ])

def get_business_tariff_keyboard() -> InlineKeyboardMarkup:
    # Compact keyboard - qatorlar orasidagi joy kamaytirildi
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Biznes", callback_data="tariff_BUSINESS"), InlineKeyboardButton(text="Biznes Plus", callback_data="tariff_BUSINESS_PLUS_INFO")],
        [InlineKeyboardButton(text="Biznes Max", callback_data="tariff_BUSINESS_MAX_INFO")],
        [InlineKeyboardButton(text="🧪 Test rejimida aktiv qilish", callback_data="test_activate_BUSINESS")]
    ])

def get_family_overview_text() -> str:
    return (
        "👨‍👩‍👧‍👦 **Oila tariflari**\n\n"
        "Oilaviy byudjetni boshqarish — endi yanada qulay. Balans AI ota-onalarga bolalar xarajatlarini"
        " nazorat qilish, barcha daromad va chiqimlarni yagona tizimda jamlash imkonini beradi."
        " Oilaviy shaffoflik va moliyaviy intizom sizning qo‘lingizda.\n\n"
        "📌 Quyidagi tariflardan birini tanlang:\n"
        "• Family — kichik va o‘rtacha oila uchun\n"
        "• Family Plus — ko‘proq a’zoli katta oilalar uchun\n"
        "• Family Max — cheksiz imkoniyatlar va to‘liq nazorat"
    )

def get_business_overview_text() -> str:
    return (
        "🏢 **Biznes tariflari**\n\n"
        "Kichikdan yirikgacha bo‘lgan biznesingizni samarali boshqaring. Balans AI xodimlarni kuzatish,"
        " filiallarni qo‘shish, daromad va xarajatlarni avtomatlashtirish hamda chuqur AI tahlillari bilan"
        " biznesingizni yangi bosqichga olib chiqadi.\n\n"
        "📌 Hozircha faqat ‘Business’ (oddiy) tarifini faollashtirish mumkin. Qolganlari tez orada."
    )

def get_tariff_detail_text(tariff_code: str) -> str:
    if tariff_code == "FREE":
        return (
            "🆓 **Bepul tarif**\n\n"
            "Bu tarif 100% bepul. Hech qanday to'lov talab qilinmaydi.\n\n"
            "Funksiyalar:\n"
            "• Shaxsiy byudjetni kiritish va kuzatish\n"
            "• Kirim/chiqimlarni qo'lda kiritish\n"
            "• Minimal interfeys, reklamasiz\n\n"
            "Kim uchun: yangi foydalanuvchilar va test qiluvchilar"
        )
    if tariff_code == "PLUS":
        return (
            "✨ **Plus — 29 990 so'm/oy**\n\n"
            "Funksiyalar:\n"
            "✔️ AI yordamida ovozli va matnli kiritish\n"
            "✔️ Tezkor moliyaviy tahlillar\n"
            "✔️ Shaxsiy byudjetni kuzatish\n"
        )
    if tariff_code == "PRO":
        return (
            "💎 **Pro — 49 990 so'm/oy**\n\n"
            "Funksiyalar:\n"
            "✔️ Cheksiz tranzaksiyalar\n"
            "✔️ Premium AI tahlillari\n"
            "✔️ Kengaytirilgan hisobotlar\n"
        )
    if tariff_code == "FAMILY":
        return (
            "👨‍👩‍👧‍👦 **Family — 99 990 so'm/oy**\n\n"
            "Funksiyalar:\n"
            "✔️ Oila bo'lib foydalanish (ota-ona + bolalar)\n"
            "✔️ Ota-onalar bolalarning xarajatlarini ko'ra oladi\n"
            "✔️ Oila byudjetini yagona joyda boshqarish"
        )
    if tariff_code == "FAMILY_PLUS":
        return (
            "👪 **Family Plus — 179 990 so'm/oy**\n\n"
            "Funksiyalar:\n"
            "✔️ Family'dagi barcha imkoniyatlar\n"
            "✔️ Ko'proq a'zolarni qo'shish\n"
            "✔️ Katta oilalar uchun kengaytirilgan imkoniyatlar"
        )
    if tariff_code == "FAMILY_MAX":
        return (
            "🏡 **Family Max — 249 990 so'm/oy**\n\n"
            "Funksiyalar:\n"
            "✔️ Family Plus'dagi barcha imkoniyatlar\n"
            "✔️ Cheksiz oila a'zolarini qo'shish\n"
            "✔️ Mukammal AI yordamchi"
        )
    if tariff_code == "BUSINESS":
        return (
            "🏢 **Business — 99 990 so'm/oy**\n\n"
            "Funksiyalar:\n"
            "✔️ Ombor boshqaruvi (Mini CRM)\n"
            "✔️ Tovarlar, kirim/chiqim, AI tahlil\n"
            "✔️ Xodimlar boshqaruvi\n"
            "✔️ Moliyaviy boshqaruvni avtomatlashtirish\n\n"
            "🧪 **Test rejimi:** Hozircha bepul sinab ko'ring!"
        )
    if tariff_code == "BUSINESS_PLUS":
        return (
            "🏬 **Business Plus — 249 990 so'm/oy**\n\n"
            "Funksiyalar:\n"
            "✔️ Filiallarni qo'shish imkoniyati\n"
            "✔️ Juda ko'p xodim qo'shish\n"
            "✔️ Kengaytirilgan boshqaruv funksiyalari"
        )
    if tariff_code == "BUSINESS_MAX":
        return (
            "🏦 **Business Max — 499 990 so'm/oy**\n\n"
            "Funksiyalar:\n"
            "✔️ Business Plus'dagi barcha imkoniyatlar\n"
            "✔️ Cheksiz xodim va filial\n"
            "✔️ To'liq AI tahlil va prognozlar"
        )
    return f"❌ Tarif '{tariff_code}' topilmadi"

# Foydalanuvchi holatlari
class UserStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_name = State()
    waiting_for_source = State()
    waiting_for_tariff = State()
    waiting_for_amount = State()
    waiting_for_category = State()
    waiting_for_debt_type = State() # Qarz turi uchun
    waiting_for_debt_person = State() # Qarz olgan odam ismi uchun
    waiting_for_debt_due_date = State() # Qarz qaytarish sanasi uchun
    
    # Onboarding final step uchun yangi state'lar
    waiting_for_income_type = State()
    waiting_for_income_frequency = State()
    waiting_for_income_amount = State()
    waiting_for_income_date = State()
    waiting_for_income_weekday = State()
    waiting_for_income_month = State()
    waiting_for_income_day = State()
    
    # Tranzaksiya tasdiqlash uchun state'lar
    waiting_for_transaction_confirmation = State()
    
    # Xodim qo'shish uchun state
    waiting_for_employee_id = State()
    
    # Tarif sotib olish uchun state'lar
    waiting_for_subscription_duration = State()
    waiting_for_payment_method = State()

    # Admin
    admin_broadcast_audience = State()
    admin_broadcast_text = State()
    
    # Onboarding: boshlang'ich balans va qarzlar
    waiting_for_initial_cash = State()
    waiting_for_initial_card = State()
    onboarding_waiting_for_debt_action = State()
    onboarding_debt_waiting_for_person = State()
    onboarding_debt_waiting_for_amount = State()
    
    # Yangi onboarding: 3 qadamli jarayon
    onboarding_welcome = State()
    onboarding_balance = State()
    onboarding_debts_lent = State()
    onboarding_debts_borrowed = State()
    onboarding_complete = State()
    onboarding_debt_waiting_for_due_date = State()
    
    # Tur tanlash uchun state
    waiting_for_account_type = State()
    
    # Warehouse (Ombor) states
    waiting_for_product_info = State()
    waiting_for_warehouse_movement = State()
    
    # Qarz tahrirlash state'lar
    waiting_for_debt_edit_name = State()
    waiting_for_debt_edit_date = State()
    
    # Tranzaksiya tahrirlash state'lar
    waiting_for_trans_edit_amount = State()
    waiting_for_trans_edit_description = State()

# Onboarding holatlari (sinovchilar uchun)
class OnboardingState(StatesGroup):
    waiting_for_income = State()
    waiting_for_balance = State()
    waiting_for_debts = State()

# Bepul tarif menyusi (Plus bilan bir xil - faqat Hisobotlar va Profil)
def get_free_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Hisobotlar"), KeyboardButton(text="👤 Profil")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

# Premium tarif menyusi
def get_premium_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Hisobotlar"), KeyboardButton(text="👤 Profil")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

# Business menyusi - YANGI TZ bo'yicha faqat 3 ta tugma + AI Chat
def get_business_menu():
    """Business tarif uchun asosiy menyu - AI orqali boshqarish"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Hisobotlar"), KeyboardButton(text="📦 Ombor")],
            [KeyboardButton(text="🤖 AI Chat"), KeyboardButton(text="👤 Profil")],
            [KeyboardButton(text="💳 Qarzlar")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

def get_ai_chat_stop_menu():
    """AI Chat rejimida to'xtatish tugmasi"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛑 AI Chatni to'xtatish")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

# Xodim menyusi
def get_employee_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Hisobotlar")],
            [KeyboardButton(text="👤 Profil")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

def get_cancel_keyboard():
    """Bekor qilish tugmasi"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    return keyboard

# Onboarding: qarzlarni boshqarish menyusi
def get_onboarding_debt_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Qarzni qo'shish")],
            [KeyboardButton(text="✅ Tayyor")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

def get_transaction_confirmation_keyboard(buttons_data: dict):
    """Tranzaksiya tasdiqlash tugmalari"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    # Asosiy tugmalar
    main_buttons = [
        InlineKeyboardButton(text="✅ Hammasini qabul qilish", callback_data="confirm_all_transactions"),
        InlineKeyboardButton(text="❌ Hammasini bekor qilish", callback_data="cancel_all_transactions")
    ]
    keyboard.inline_keyboard.append(main_buttons)
    
    # Har bir tranzaksiya uchun alohida tugmalar
    transactions = buttons_data.get('transactions', [])
    if transactions:
        # Har bir tranzaksiya uchun 2 ta tugma
        for i, item in enumerate(transactions, 1):
            trans_buttons = [
                InlineKeyboardButton(text=f"✅ {i}", callback_data=f"confirm_transaction_{i}"),
                InlineKeyboardButton(text=f"❌ {i}", callback_data=f"cancel_transaction_{i}")
            ]
            keyboard.inline_keyboard.append(trans_buttons)
    
    return keyboard

# Profil menyusi
def get_profile_menu(user_tariff='PLUS'):
    """Profil menyusini qaytaradi - Batafsil, Sozlamalar va Yordam"""
    buttons = []
    
    # Free tarif uchun Kuchaytirish tugmasi
    if user_tariff in ('NONE', None, 'FREE'):
        buttons.append([
            InlineKeyboardButton(text="🚀 Kuchaytirish", web_app=WebAppInfo(url="https://balansai-app.onrender.com/tariffs"))
        ])
    
    buttons.append([
        InlineKeyboardButton(text="📋 Batafsil", web_app=WebAppInfo(url="https://balansai-app.onrender.com/profile")),
        InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data="settings")
    ])
    buttons.append([
        InlineKeyboardButton(text="📖 Yordam", callback_data="help_menu")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_plus_purchase_keyboard():
    """Plus tarifni sotib olish uchun tugma"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Plus tarifni sotib olish", web_app=WebAppInfo(url=PAYMENT_PLUS_WEBAPP_URL))]
        ]
    )


def format_plus_usage_display(summary: dict) -> str:
    """Plus paket qoldiqlari matnini formatlash"""
    if not summary:
        return "0/0 | 0/0"
    text_limit = summary.get('text_limit', 0)
    text_used = summary.get('text_used', 0)
    voice_limit = summary.get('voice_limit', 0)
    voice_used = summary.get('voice_used', 0)
    return f"{text_used}/{text_limit} | {voice_used}/{voice_limit}"

def resolve_plus_package_code(package_code: Optional[str] = None, amount: Optional[Union[int, float, str]] = None) -> Optional[str]:
    """Mini-ilova yoki Telegram to'lovlaridan paket kodini aniqlash"""
    if package_code and package_code in PLUS_PACKAGES:
        return package_code
    
    if amount is None:
        return None
    
    try:
        amount_int = int(float(str(amount)))
    except (ValueError, TypeError):
        return None
    
    for code, pkg in PLUS_PACKAGES.items():
        price = int(pkg.get('price', 0))
        candidates = {price, price * 100, price * 1000}
        if amount_int in candidates:
            return code
    return None

# ==== ADMIN BLOK ==== (UserStates'dan keyin)
@dp.message(Command("admin"))
async def admin_command(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_USER_ID:
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Statistika", callback_data="admin_stats")],
            [InlineKeyboardButton(text="📨 Xabar yuborish", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="🎤 Speech Model Boshqarish", callback_data="admin_speech_models")],
            [InlineKeyboardButton(text="🆓 3 kunlik Sinov Boshqarish", callback_data="admin_free_trial")]
        ]
    )
    try:
        await message.answer_photo(
            photo=FSInputFile('Profil.png'),
            caption="Admin panel",
            reply_markup=kb
        )
    except Exception:
        await message.answer("Admin panel", reply_markup=kb)

@dp.callback_query(lambda c: c.data == "admin_stats")
async def admin_stats_callback(callback_query: CallbackQuery):
    if callback_query.from_user.id != ADMIN_USER_ID:
        await callback_query.answer()
        return
    row_users = await db.execute_one("SELECT COUNT(*) FROM users")
    total_users = row_users[0] if row_users else 0
    per_tariff_rows = await db.execute_query("SELECT tariff, COUNT(*) cnt FROM users GROUP BY tariff")
    per_tariff_map = {r[0]: r[1] for r in per_tariff_rows} if per_tariff_rows else {}
    row_paid = await db.execute_one("SELECT COALESCE(SUM(total_amount),0) FROM payments WHERE status='paid'")
    total_paid = row_paid[0] if row_paid else 0
    row_tx = await db.execute_one("SELECT COUNT(*) FROM transactions")
    total_tx = row_tx[0] if row_tx else 0
    
    # Foydalanuvchilar bizni qayerdan eshitganini olish
    source_rows = await db.execute_query("SELECT source, COUNT(*) cnt FROM users WHERE source IS NOT NULL GROUP BY source")
    source_map = {r[0]: r[1] for r in source_rows} if source_rows else {}
    
    # Open AI API balansi
    openai_balance = "N/A"
    try:
        from config import OPENAI_API_KEY
        if OPENAI_API_KEY:
            import requests
            headers = {
                'Authorization': f'Bearer {OPENAI_API_KEY}',
                'Content-Type': 'application/json'
            }
            # OpenAI'ning billing API'sini chaqirish
            try:
                # Billing usage API (to'g'ri endpoint)
                response = requests.get('https://api.openai.com/v1/usage?date=2024-01-01', headers=headers)
                if response.status_code == 200:
                    usage_data = response.json()
                    total_usage = usage_data.get('total_usage', 0)
                    openai_balance = f"${total_usage/100:.2f} ishlatilgan"
                elif response.status_code == 401:
                    openai_balance = "API key noto'g'ri"
                elif response.status_code == 403:
                    openai_balance = "Ruxsat yo'q"
                else:
                    # Billing balance API'ni sinab ko'ramiz
                    try:
                        balance_response = requests.get('https://api.openai.com/v1/dashboard/billing/credit_grants', headers=headers)
                        if balance_response.status_code == 200:
                            balance_data = balance_response.json()
                            total_granted = balance_data.get('total_granted', 0)
                            total_used = balance_data.get('total_used', 0)
                            remaining = total_granted - total_used
                            openai_balance = f"${remaining:.2f} qoldi (${total_used:.2f} ishlatilgan)"
                        else:
                            openai_balance = f"API xatoligi: {balance_response.status_code}"
                    except Exception:
                        openai_balance = f"Xatolik: {response.status_code}"
            except Exception as e:
                openai_balance = f"API xatoligi: {str(e)[:50]}"
        else:
            openai_balance = "API key yo'q"
    except Exception as e:
        openai_balance = f"Xatolik: {str(e)[:30]}"
    
    text = (
        "👨‍💻 Admin statistika\n\n"
        f"Jami foydalanuvchilar: {total_users:,}\n"
        "Tariflar bo'yicha:\n" + "\n".join([f"• {TARIFFS.get(k,k)}: {v:,}" for k,v in per_tariff_map.items()]) + "\n\n"
        "Bizni qayerdan eshitgan:\n" + "\n".join([f"• {k}: {v:,}" for k,v in source_map.items()]) + "\n\n"
        f"Jami to'langan pullar: { (total_paid or 0)/100:,.0f} so'm\n"
        f"Jami tranzaksiyalar: {total_tx:,} ta\n\n"
        f"🤖 Open AI API balansi: {openai_balance}"
    )
    try:
        await callback_query.message.edit_caption(caption=text, parse_mode='Markdown')
    except Exception:
        await callback_query.message.edit_text(text, parse_mode='Markdown')
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "admin_broadcast")
async def admin_broadcast_callback(callback_query: CallbackQuery, state: FSMContext):
    if callback_query.from_user.id != ADMIN_USER_ID:
        await callback_query.answer()
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Hammaga", callback_data="admin_bc_all")],
            [InlineKeyboardButton(text="Tarif bo'yicha", callback_data="admin_bc_by_tariff")]
        ]
    )
    try:
        await callback_query.message.edit_caption(caption="Kimga yuboramiz?", reply_markup=kb)
    except Exception:
        await callback_query.message.edit_text("Kimga yuboramiz?", reply_markup=kb)
    await state.set_state(UserStates.admin_broadcast_audience)
    await callback_query.answer()

@dp.callback_query(lambda c: c.data in {"admin_bc_all","admin_bc_by_tariff"}, UserStates.admin_broadcast_audience)
async def admin_broadcast_audience_selected(callback_query: CallbackQuery, state: FSMContext):
    if callback_query.from_user.id != ADMIN_USER_ID:
        await callback_query.answer()
        return
    choice = callback_query.data
    await state.update_data(bc_choice=choice)
    if choice == "admin_bc_by_tariff":
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=TARIFFS[t], callback_data=f"admin_bc_tariff_{t}")] for t in TARIFFS.keys()])
        try:
            await callback_query.message.edit_caption(caption="Qaysi tarif?", reply_markup=kb)
        except Exception:
            await callback_query.message.edit_text("Qaysi tarif?", reply_markup=kb)
    else:
        try:
            await callback_query.message.edit_caption(caption="Matnni yuboring:")
        except Exception:
            await callback_query.message.edit_text("Matnni yuboring:")
        await state.set_state(UserStates.admin_broadcast_text)
    await callback_query.answer()

@dp.callback_query(lambda c: c.data.startswith("admin_bc_tariff_"), UserStates.admin_broadcast_audience)
async def admin_broadcast_choose_tariff(callback_query: CallbackQuery, state: FSMContext):
    if callback_query.from_user.id != ADMIN_USER_ID:
        await callback_query.answer()
        return
    tariff = callback_query.data.split("_")[-1]
    await state.update_data(bc_tariff=tariff)
    try:
        await callback_query.message.edit_caption(caption=f"Tanlandi: {TARIFFS.get(tariff, tariff)}\nMatnni yuboring:")
    except Exception:
        await callback_query.message.edit_text(f"Tanlandi: {TARIFFS.get(tariff, tariff)}\nMatnni yuboring:")
    await state.set_state(UserStates.admin_broadcast_text)
    await callback_query.answer()

@dp.message(UserStates.admin_broadcast_text)
async def admin_broadcast_text_handler(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_USER_ID:
        return
    data = await state.get_data()
    choice = data.get('bc_choice')
    tariff = data.get('bc_tariff')
    text = message.text
    if choice == 'admin_bc_all':
        rows = await db.fetch_all("SELECT user_id FROM users")
    else:
        rows = await db.fetch_all("SELECT user_id FROM users WHERE tariff=%s", (tariff,))
    user_ids = [r['user_id'] if isinstance(r, dict) else r[0] for r in rows]
    sent = 0
    for uid in user_ids:
        try:
            await bot.send_message(chat_id=uid, text=text)
            sent += 1
        except Exception:
            pass
    await message.answer(f"Yuborildi: {sent} ta foydalanuvchiga")
    await state.clear()

# Speech Model boshqarish
@dp.callback_query(lambda c: c.data == "admin_speech_models")
async def admin_speech_models_callback(callback_query: CallbackQuery):
    if callback_query.from_user.id != ADMIN_USER_ID:
        await callback_query.answer()
        return
    
    # Hozirgi holatni ko'rsatish
    google_active = ACTIVE_SPEECH_MODELS.get('GOOGLE', False)
    elevenlabs_active = ACTIVE_SPEECH_MODELS.get('ELEVENLABS', False)
    
    # Faqat bitta tanlangan bo'lishi kerak
    if google_active and elevenlabs_active:
        # Agar ikkalasi ham yo'q bo'lsa, birinchisini o'chiramiz
        ACTIVE_SPEECH_MODELS['GOOGLE'] = False
        google_active = False
    elif not google_active and not elevenlabs_active:
        # Agar ikkalasi ham o'chirilgan bo'lsa, birinchisini yoqamiz
        ACTIVE_SPEECH_MODELS['ELEVENLABS'] = True
        elevenlabs_active = True
    
    google_status = "✅ Yoqilgan" if google_active else "❌ O'chirilgan"
    elevenlabs_status = "✅ Yoqilgan" if elevenlabs_active else "❌ O'chirilgan"
    
    text = f"""🎤 **Speech Model Boshqarish**

**Hozirgi holat:**
• ElevenLabs Speech-to-Text: {elevenlabs_status}
• Google Cloud Speech-to-Text: {google_status}

**MUHIM:** Faqat 1 ta model tanlab ishlatishingiz mumkin!

**Boshqarish:**
Quyidagi tugmalardan foydalaning:"""
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"ElevenLabs: {elevenlabs_status}", callback_data="admin_toggle_elevenlabs")],
            [InlineKeyboardButton(text=f"Google: {google_status}", callback_data="admin_toggle_google")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin_back")]
        ]
    )
    
    try:
        await callback_query.message.edit_caption(caption=text, reply_markup=kb, parse_mode='Markdown')
    except Exception:
        # Agar xabar bir xil bo'lsa, hech narsa qilmaymiz
        pass
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "admin_toggle_google")
async def admin_toggle_google_callback(callback_query: CallbackQuery):
    if callback_query.from_user.id != ADMIN_USER_ID:
        await callback_query.answer()
        return
    
    # Faqat bitta model tanlab ishlatish uchun
    if ACTIVE_SPEECH_MODELS['GOOGLE']:
        # Agar yo'q bo'lsa, ochiramiz
        ACTIVE_SPEECH_MODELS['GOOGLE'] = False
    else:
        # Agar ochiq bo'lsa, yoqamiz va boshqasini ochiramiz
        ACTIVE_SPEECH_MODELS['GOOGLE'] = True
        ACTIVE_SPEECH_MODELS['ELEVENLABS'] = False
    
    # Bazaga saqlash
    await db.execute_query(
        "UPDATE config SET value = %s WHERE key_name = 'active_speech_google'",
        (str(ACTIVE_SPEECH_MODELS['GOOGLE']).lower(),)
    )
    await db.execute_query(
        "UPDATE config SET value = %s WHERE key_name = 'active_speech_elevenlabs'",
        (str(ACTIVE_SPEECH_MODELS['ELEVENLABS']).lower(),)
    )
    await admin_speech_models_callback(callback_query)

@dp.callback_query(lambda c: c.data == "admin_toggle_elevenlabs")
async def admin_toggle_elevenlabs_callback(callback_query: CallbackQuery):
    if callback_query.from_user.id != ADMIN_USER_ID:
        await callback_query.answer()
        return
    
    # Faqat bitta model tanlab ishlatish uchun
    if ACTIVE_SPEECH_MODELS['ELEVENLABS']:
        # Agar yo'q bo'lsa, ochiramiz
        ACTIVE_SPEECH_MODELS['ELEVENLABS'] = False
    else:
        # Agar ochiq bo'lsa, yoqamiz va boshqasini ochiramiz
        ACTIVE_SPEECH_MODELS['ELEVENLABS'] = True
        ACTIVE_SPEECH_MODELS['GOOGLE'] = False
    
    # Bazaga saqlash
    await db.execute_query(
        "UPDATE config SET value = %s WHERE key_name = 'active_speech_elevenlabs'",
        (str(ACTIVE_SPEECH_MODELS['ELEVENLABS']).lower(),)
    )
    await db.execute_query(
        "UPDATE config SET value = %s WHERE key_name = 'active_speech_google'",
        (str(ACTIVE_SPEECH_MODELS['GOOGLE']).lower(),)
    )
    await admin_speech_models_callback(callback_query)


@dp.callback_query(lambda c: c.data == "admin_back")
async def admin_back_callback(callback_query: CallbackQuery):
    if callback_query.from_user.id != ADMIN_USER_ID:
        await callback_query.answer()
        return
    
    # Admin panelga qaytish
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Statistika", callback_data="admin_stats")],
            [InlineKeyboardButton(text="📨 Xabar yuborish", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="🎤 Speech Model Boshqarish", callback_data="admin_speech_models")],
            [InlineKeyboardButton(text="🆓 3 kunlik Sinov Boshqarish", callback_data="admin_free_trial")]
        ]
    )
    
    await callback_query.message.edit_caption(caption="Admin panel", reply_markup=kb)
    await callback_query.answer()

# Bepul sinov boshqarish (3 kunlik)
@dp.callback_query(lambda c: c.data == "admin_free_trial")
async def admin_free_trial_callback(callback_query: CallbackQuery):
    if callback_query.from_user.id != ADMIN_USER_ID:
        await callback_query.answer()
        return
    
    # Hozirgi holatni ko'rsatish
    text = "🆓 **3 kunlik sinov boshqarish**\n\n**Hozirgi holat:**\n"
    
    for tariff, enabled in FREE_TRIAL_ENABLED.items():
        status = "✅ Yoqilgan" if enabled else "❌ O'chirilgan"
        tariff_name = TARIFFS.get(tariff, tariff)
        text += f"• {tariff_name}: {status}\n"
    
    text += "\n**Boshqarish:**\nQuyidagi tugmalardan foydalaning:"
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Ikkalasini ham yoqish", callback_data="admin_enable_all_trials")],
            [InlineKeyboardButton(text="❌ Ikkalasini ham o'chirish", callback_data="admin_disable_all_trials")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin_back")]
        ]
    )
    
    # Har bir tarif uchun alohida tugma
    tariff_buttons = []
    for tariff, enabled in FREE_TRIAL_ENABLED.items():
        tariff_name = TARIFFS.get(tariff, tariff)
        status = "✅" if enabled else "❌"
        tariff_buttons.append([InlineKeyboardButton(
            text=f"{status} {tariff_name}", 
            callback_data=f"admin_toggle_trial_{tariff}"
        )])
    
    kb.inline_keyboard.extend(tariff_buttons)
    kb.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin_back")])
    
    try:
        await callback_query.message.edit_caption(caption=text, reply_markup=kb, parse_mode='Markdown')
    except Exception:
        # Agar xabar bir xil bo'lsa, hech narsa qilmaymiz
        pass
    await callback_query.answer()

# 3 kunlik sinov toggle
@dp.callback_query(lambda c: c.data.startswith("admin_toggle_trial_"))
async def admin_toggle_trial_callback(callback_query: CallbackQuery):
    if callback_query.from_user.id != ADMIN_USER_ID:
        await callback_query.answer()
        return
    
    tariff = callback_query.data.split("_")[-1]
    if tariff in FREE_TRIAL_ENABLED:
        FREE_TRIAL_ENABLED[tariff] = not FREE_TRIAL_ENABLED[tariff]
        # Bazaga saqlash
        await db.execute_query(
            "UPDATE config SET value = %s WHERE key_name = %s",
            (str(FREE_TRIAL_ENABLED[tariff]).lower(), f"free_trial_{tariff.lower()}")
        )
    
    await admin_free_trial_callback(callback_query)

# Barcha sinovlarni yoqish
@dp.callback_query(lambda c: c.data == "admin_enable_all_trials")
async def admin_enable_all_trials_callback(callback_query: CallbackQuery):
    if callback_query.from_user.id != ADMIN_USER_ID:
        await callback_query.answer()
        return
    
    for tariff in FREE_TRIAL_ENABLED:
        FREE_TRIAL_ENABLED[tariff] = True
        # Bazaga saqlash
        await db.execute_query(
            "UPDATE config SET value = 'true' WHERE key_name = %s",
            (f"free_trial_{tariff.lower()}",)
        )
    
    await admin_free_trial_callback(callback_query)

# Barcha sinovlarni o'chirish
@dp.callback_query(lambda c: c.data == "admin_disable_all_trials")
async def admin_disable_all_trials_callback(callback_query: CallbackQuery):
    if callback_query.from_user.id != ADMIN_USER_ID:
        await callback_query.answer()
        return
    
    for tariff in FREE_TRIAL_ENABLED:
        FREE_TRIAL_ENABLED[tariff] = False
        # Bazaga saqlash
        await db.execute_query(
            "UPDATE config SET value = 'false' WHERE key_name = %s",
            (f"free_trial_{tariff.lower()}",)
        )
    
    await admin_free_trial_callback(callback_query)

# Xodim profili menyusi
def get_employee_profile_menu():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Batafsil", web_app=WebAppInfo(url="https://balansai-app.onrender.com/profile"))],
            [InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data="settings")],
            [InlineKeyboardButton(text="🚪 Jamoadan chiqish", callback_data="leave_team")]
        ]
    )
    return keyboard

# Sozlamalar menyusi
async def get_settings_menu(user_tariff='NONE', user_id=None):
    """Sozlamalar menyusini qaytaradi"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Til: O'zbek 🇺🇿", callback_data="settings_language")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_profile")]
        ]
    )
    return keyboard

def get_settings_menu_old():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_profile")]
        ]
    )
    return keyboard

# Tarif menyusi
def get_tariff_menu():
    return build_main_tariff_keyboard()

# Manba tanlash menyusi
def get_source_menu():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
                [
                InlineKeyboardButton(text="Telegramda", callback_data="source_telegram"),
                InlineKeyboardButton(text="Instagramda", callback_data="source_instagram")
            ],
            [
                InlineKeyboardButton(text="YouTubeda", callback_data="source_youtube"),
                InlineKeyboardButton(text="Tanishimdan", callback_data="source_friend")
            ]
        ]
    )
    return keyboard

# Kategoriya tanlash menyusi (kirim)
def get_income_category_menu():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💼 Ish haqi", callback_data="cat_ish_haqi")],
            [InlineKeyboardButton(text="💼 Biznes", callback_data="cat_biznes")],
            [InlineKeyboardButton(text="📈 Investitsiya", callback_data="cat_investitsiya")],
            [InlineKeyboardButton(text="📝 Boshqa", callback_data="cat_boshqa")],
            [InlineKeyboardButton(text="⏭️ O'tkazib yuborish", callback_data="cat_skip")]
        ]
    )
    return keyboard

# Kategoriya tanlash menyusi (chiqim)
def get_expense_category_menu():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🍽️ Ovqat", callback_data="cat_ovqat")],
            [InlineKeyboardButton(text="🚗 Transport", callback_data="cat_transport")],
            [InlineKeyboardButton(text="👕 Kiyim", callback_data="cat_kiyim")],
            [InlineKeyboardButton(text="🏠 Uy", callback_data="cat_uy")],
            [InlineKeyboardButton(text="🏥 Sog'liq", callback_data="cat_soglik")],
            [InlineKeyboardButton(text="📚 Ta'lim", callback_data="cat_talim")],
            [InlineKeyboardButton(text="🎮 O'yin-kulgi", callback_data="cat_oyin")],
            [InlineKeyboardButton(text="📝 Boshqa", callback_data="cat_boshqa")],
            [InlineKeyboardButton(text="⏭️ O'tkazib yuborish", callback_data="cat_skip")]
        ]
    )
    return keyboard

# Qarz turini tanlash menyusi
def get_debt_type_menu():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💰 Qarz oldim", callback_data="debt_type_borrowed")],
            [InlineKeyboardButton(text="💸 Qarz berdim", callback_data="debt_type_lent")]
        ]
    )
    return keyboard

# Kategoriya tanlash menyusi (qarz)
def get_debt_category_menu():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Do'st", callback_data="cat_dost")],
            [InlineKeyboardButton(text="👨‍👩‍👧‍👦 Oilaviy", callback_data="cat_oilaviy")],
            [InlineKeyboardButton(text="🏦 Bank", callback_data="cat_bank")],
            [InlineKeyboardButton(text="💼 Biznes", callback_data="cat_biznes")],
            [InlineKeyboardButton(text="📝 Boshqa", callback_data="cat_boshqa")],
            [InlineKeyboardButton(text="⏭️ O'tkazib yuborish", callback_data="cat_skip")]
        ]
    )
    return keyboard

async def get_user_tariff(user_id: int) -> str:
    """Foydalanuvchi tarifini olish (yangi ko'p tarif tizimi)"""
    try:
        tariff = await db.get_active_tariff(user_id)
        if tariff in (None, ''):
            return 'FREE'
        return tariff
    except Exception:
        return "FREE"

async def get_user_all_subscriptions(user_id: int):
    """Foydalanuvchining barcha tariflarini olish"""
    try:
        return await db.get_user_subscriptions(user_id)
    except:
        return []

def calculate_subscription_price(tariff: str, months: int) -> dict:
    """Obuna narxini hisoblash (chegirma bilan)"""
    base_price = TARIFF_PRICES.get(tariff, 0)
    if base_price == 0:
        return {"error": "Tarif topilmadi"}
    
    total_months = months
    discount_rate = DISCOUNT_RATES.get(months, 0)
    
    # Jami narx (chegirmasiz)
    total_price = base_price * total_months
    
    # Chegirma miqdori
    discount_amount = int(total_price * discount_rate / 100)
    
    # Yakuniy narx
    final_price = total_price - discount_amount
    
    return {
        "base_price": base_price,
        "total_months": total_months,
        "discount_rate": discount_rate,
        "discount_amount": discount_amount,
        "total_price": total_price,
        "final_price": final_price
    }

def get_subscription_duration_keyboard() -> InlineKeyboardMarkup:
    """Obuna muddati tanlash tugmalari"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1 oy", callback_data="duration_1"),
            InlineKeyboardButton(text="2 oy (5% chegirma)", callback_data="duration_2")
        ],
        [
            InlineKeyboardButton(text="3 oy (10% chegirma)", callback_data="duration_3"),
            InlineKeyboardButton(text="6 oy (15% chegirma)", callback_data="duration_6")
        ],
        [InlineKeyboardButton(text="12 oy (25% chegirma)", callback_data="duration_12")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_tariff_selection")]
    ])
    return keyboard

def get_payment_method_keyboard() -> InlineKeyboardMarkup:
    """To'lov usuli tanlash tugmalari"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        # Mini ilova orqali to'lov
        [InlineKeyboardButton(text="📱 Mini ilova orqali to'lash", web_app=WebAppInfo(url="https://balansai.onrender.com/payment"))],
        # Telegram to'lov usullari
        [InlineKeyboardButton(text="💳 Telegram (Click)", callback_data="select_payment_telegram_click")],
        # Boshqa to'lov usullari
        [
            InlineKeyboardButton(text="🔵 Click", callback_data="select_payment_click"),
            InlineKeyboardButton(text="🟢 Payme", callback_data="select_payment_payme")
        ],
        [
            InlineKeyboardButton(text="🟡 Uzum Pay", callback_data="select_payment_uzum_pay"),
        ],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_duration_selection")]
    ])
    return keyboard

async def get_user_name(user_id: int) -> str:
    """Foydalanuvchi ismini olish (first_name dan)"""
    try:
        query = "SELECT first_name FROM users WHERE user_id = %s"
        result = await db.execute_one(query, (user_id,))
        return result.get('first_name') if result and result.get('first_name') else "Xojayin"
    except:
        return "Xojayin"

# Start komandasi
@dp.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext):
    """Start komandasi"""
    user_id = message.from_user.id
    # Dedup/throttle: 2 soniya ichida bir xil foydalanuvchidan kelgan /start ni e'tiborsiz qoldiramiz
    try:
        from time import time as _now
        cache = START_DEDUP_CACHE.get(user_id)
        if cache:
            last_ts = cache.get("ts", 0)
            last_msg = cache.get("msg_id")
            if (message.message_id == last_msg) or (_now() - last_ts < 2.0):
                return
        START_DEDUP_CACHE[user_id] = {"msg_id": message.message_id, "ts": _now()}
    except Exception:
        pass
    username = message.from_user.username
    first_name = message.from_user.first_name or "Xojayin"
    # /start xabarini o'chirmaymiz - foydalanuvchi ko'rsin
    
    # Foydalanuvchini ma'lumotlar bazasiga qo'shish (faqat first_name ishlatiladi)
    try:
            await db.execute_query(
                "INSERT INTO users (user_id, username, first_name, tariff) VALUES (%s, %s, %s, 'NONE') ON DUPLICATE KEY UPDATE username = %s, first_name = %s",
                (user_id, username, first_name, username, first_name)
            )
    except Exception as e:
        logging.error(f"Foydalanuvchi qo'shishda xatolik: {e}")
    
    # Foydalanuvchi yangi yoki eski ekanligini tekshirish
    user_data = await db.get_user_data(user_id)
    
    # Boshlang'ich balans mavjudligini tekshirish (onboarding yakunlanganmi)
    has_initial_balance = False
    has_any_transactions = False
    if user_data:
        balance_query = """
        SELECT COUNT(*) as count FROM transactions 
        WHERE user_id = %s AND category IN ('boshlang_ich_balans', 'boshlang_ich_naqd', 'boshlang_ich_karta')
        """
        result = await db.execute_one(balance_query, (user_id,))
        has_initial_balance = result.get('count', 0) > 0 if result else False

        # Foydalanuvchida umuman tranzaksiya bormi (yangi foydalanuvchini ajratish uchun)
        tx_count_query = "SELECT COUNT(*) as count FROM transactions WHERE user_id = %s"
        tx_result = await db.execute_one(tx_count_query, (user_id,))
        has_any_transactions = (tx_result.get('count', 0) > 0) if tx_result else False

    # Eski onboarding logikasi olib tashlandi - endi barcha ma'lumotlar mini app da to'ldiriladi
    current_state = await state.get_state()
    
    # Eski onboarding state'larini tozalash (agar mavjud bo'lsa)
    old_onboarding_states = [
        UserStates.waiting_for_name.state,
        UserStates.waiting_for_source.state,
        UserStates.waiting_for_account_type.state,
        UserStates.onboarding_balance.state,
        UserStates.onboarding_waiting_for_debt_action.state,
        UserStates.onboarding_debt_waiting_for_person.state,
        UserStates.onboarding_debt_waiting_for_amount.state,
        UserStates.onboarding_debt_waiting_for_due_date.state,
        UserStates.waiting_for_initial_card.state,
        UserStates.waiting_for_debt_type.state
    ]
    if current_state in old_onboarding_states:
        await state.clear()
    
    # Agar foydalanuvchi onboarding yakunlagan bo'lsa
    if has_initial_balance or has_any_transactions:
        # Eski foydalanuvchi - asosiy menyuni ko'rsatish
        user_name = await get_user_name(user_id)
        user_tariff = await get_user_tariff(user_id)
        
        if user_tariff in ('NONE', None):
            # Menu bilan xabar yuborish
            await message.answer(
                f"👋 Salom, {user_name}!\n\nXabar yuboring...",
                reply_markup=get_free_menu()
            )
        elif user_tariff == 'BUSINESS':
            # Business menu
            await message.answer(
                f"👋 Salom, {user_name}!\n\nXabar yuboring...",
                reply_markup=get_business_menu()
            )
        elif user_tariff in ('PLUS', 'PRO', 'MAX'):
            # Premium menu
            await message.answer(
                f"👋 Salom, {user_name}!\n\nXabar yuboring...",
                reply_markup=get_premium_menu()
            )
        else:
            # Default menu
            await message.answer(
                f"👋 Salom, {user_name}!\n\nXabar yuboring...",
                reply_markup=get_free_menu()
            )
        return
    
    # Yangi foydalanuvchi uchun faqat xush kelibsiz xabari (onboarding boshlanmaydi)
    # Onboarding faqat telefon raqami yuborilgandan keyin boshlanadi
    
    # Onboarding oqimini to'g'ri tartibda yo'naltirish
    # 1) Telefon yo'q -> telefon so'rash
    if not (user_data and user_data.get('phone')):
        try:
            _msg = await message.answer_photo(
                photo=FSInputFile('welcome.png'),
                caption=(
                    "Balans AI’ga xush kelibsiz.\n\n"
                    "💵 Balans AI — sizning shaxsiy buxgalteringiz.\n"
                    "U har bir so‘mingizni hisoblab, daromad va xarajatlaringizni tartibda saqlaydi.\n\n"
                    "• Har kuni pulingiz qayerga ketayotganini aniq bilasiz.\n"
                    "• Har oy qancha tejayotganingizni ko‘rasiz.\n"
                    "• AI hammasini kuzatadi — siz esa xotirjam bo‘lasiz.\n\n"
                    "⏩ Boshlash: telefoningizni pastdagi tugma orqali yuboring."
                ),
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[[KeyboardButton(text="Telefon raqamni yuborish", request_contact=True)]],
                    resize_keyboard=True
                ),
                parse_mode="HTML"
            )
            await state.update_data(phone_request_msg_id=_msg.message_id)
        except Exception as _e:
            logging.warning(f"Welcome rasm yuborilmadi: {_e}")
            await message.answer(
                "Balans AI’ga xush kelibsiz.\n\n"
                "💵 Balans AI — sizning shaxsiy buxgalteringiz.\n"
                "U har bir so‘mingizni hisoblab, daromad va xarajatlaringizni tartibda saqlaydi.\n\n"
                "• Har kuni pulingiz qayerga ketayotganini aniq bilasiz.\n"
                "• Har oy qancha tejayotganingizni ko‘rasiz.\n"
                "• AI hammasini kuzatadi — siz esa xotirjam bo‘lasiz.\n\n"
                "⏩ Boshlash: telefoningizni pastdagi tugma orqali yuboring.",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[[KeyboardButton(text="Telefon raqamni yuborish", request_contact=True)]],
                    resize_keyboard=True
                ),
                parse_mode="Markdown"
            )
        await state.set_state(UserStates.waiting_for_phone)
        return

    # 2) Agar tarif tanlash jarayonida bo'lsa -> tarif menyusi
    if (await state.get_state()) == UserStates.waiting_for_tariff.state:
        await message.answer(
            get_tariff_overview_text(),
            reply_markup=build_main_tariff_keyboard()
        )
        return
    
    # 2.1) Agar to'lov usuli tanlash jarayonida bo'lsa -> to'lov usuli menyusi
    if (await state.get_state()) == UserStates.waiting_for_payment_method.state:
        data = await state.get_data()
        tariff = data.get('selected_tariff', 'PLUS')
        duration = data.get('selected_duration', '1')
        
        # To'lov usuli menyusini qaytadan yuborish
        price_info = calculate_subscription_price(tariff, int(duration))
        await message.answer(
            f"💳 **{get_tariff_detail_text(tariff)}**\n\n"
            f"📅 **Muddat:** {duration} oy\n"
            f"💰 **Narx:** {price_info.get('total', 0):,.0f} so'm\n\n"
            "To'lov usulini tanlang:",
            parse_mode='Markdown',
            reply_markup=build_payment_method_keyboard()
        )
        return

    # Eski onboarding state'lari olib tashlandi - endi barcha ma'lumotlar mini app da to'ldiriladi


    # 4) Telefon raqam bor - ro'yxatdan o'tganligini tekshirish
    if user_data and user_data.get('phone'):
        is_registration_complete = await check_registration_complete(user_id)
        
        if not is_registration_complete:
            # Ro'yxatdan to'liq o'tilmagan - mini app tugmasi berish
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="📱 Ro'yxatdan o'tishni davom ettirish",
                    web_app=WebAppInfo(url="https://balansai-app.onrender.com/register")
                )]
            ])
            await message.answer(
                f"⚠️ **Ro'yxatdan o'tish yakunlanmagan**\n\n"
                f"Botdan foydalanish uchun quyidagi tugmani bosing va ma'lumotlarni to'ldiring:",
                reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return

        # Ro'yxatdan to'liq o'tilgan - asosiy menyuni ko'rsatish
        user_name = await get_user_name(user_id)
        user_tariff = await get_user_tariff(user_id)
        
        # Tarifga qarab keyboard tanlash
        if user_tariff in ("FREE", None):
            # Tarif yo'q - Plus sotib olish taklifi
            await message.answer(
                f"👋 Salom, {user_name}!\n\n"
                "Balans AI'dan foydalanishni boshlash uchun Plus tarifni sotib oling.",
                reply_markup=get_plus_purchase_keyboard(),
                parse_mode="Markdown"
            )
        elif user_tariff == "BUSINESS":
            # Business tarif - business menu
            await message.answer(
                f"👋 Salom, {user_name}!\n\nXabar yuboring...",
                reply_markup=get_business_menu()
            )
        else:
            # PLUS, PRO va boshqa tariflar - premium menu
            await message.answer(
                f"👋 Salom, {user_name}!\n\nXabar yuboring...",
                reply_markup=get_premium_menu()
            )
        return

# Tur tanlash menyusini qaytaradi
def get_account_type_menu():
    """Hisob turini tanlash uchun tugmalar - faqat Shaxsiy va Biznes"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👤 Shaxsiy foydalanish uchun", callback_data="account_type_SHI")],
            [InlineKeyboardButton(text="🏢 Biznes uchun", callback_data="account_type_BIZNES")]
        ]
    )
    return keyboard

# Shaxsiy tarif tanlash menyusi (Plus va Pro)
def get_personal_tariff_menu():
    """Plus va Pro tariflardan birini tanlash uchun tugmalar"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Plus tarif (3 kun bepul)", callback_data="trial_tariff_PLUS")],
            [InlineKeyboardButton(text="💎 Pro tarif (3 kun bepul)", callback_data="trial_tariff_PRO")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_account_type")]
        ]
    )
    return keyboard

# Telefon raqam qabul qilish
@dp.message(lambda message: message.contact, UserStates.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    """Telefon raqamni qabul qilish"""
    user_id = message.from_user.id
    phone = message.contact.phone_number
    
    # Telefon raqamni saqlash
    await db.execute_query(
        "UPDATE users SET phone = %s WHERE user_id = %s",
        (phone, user_id)
    )
    
    # Eski xabarlarni o'chirish
    try:
        await message.delete()
        # Avvalgi "Telefon raqamni yuborish" xabarini o'chirish
        data = await state.get_data()
        if 'phone_request_msg_id' in data:
            phone_msg_id = data['phone_request_msg_id']
            await message.bot.delete_message(chat_id=user_id, message_id=phone_msg_id)
    except:
        pass
    
    # Mini app ochish uchun tugma berish
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📱 Ro'yxatdan o'tishni davom ettirish",
            web_app=WebAppInfo(url="https://balansai-app.onrender.com/register")
        )]
    ])
    
    await message.answer(
        "✅ **Telefon raqamingiz qabul qilindi!**\n\n"
        "Endi ro'yxatdan o'tishni davom ettirish uchun quyidagi tugmani bosing va barcha ma'lumotlarni to'ldiring:\n\n"
        "• Ism\n"
        "• Yosh\n"
        "• Sozlamalar\n"
        "• Onboarding\n"
        "• Tarif tanlash\n\n"
        "Barcha ma'lumotlar to'ldirilgandan keyin botdan foydalanishga ruxsat beriladi.",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    
    # State'ni tozalash va ro'yxatdan o'tish holatiga o'tkazish
    await state.clear()
    await state.set_state(None)

# waiting_for_phone state uchun universal handler - contact bo'lmagan xabarlar uchun
@dp.message(UserStates.waiting_for_phone)
async def handle_waiting_for_phone_message(message: types.Message, state: FSMContext):
    """Telefon raqam so'rash - har qanday xabar yozilsa yana telefon raqam so'rash xabari yuboriladi"""
    user_id = message.from_user.id
    
    # Eski xabarni o'chirish
    try:
        await message.delete()
    except:
        pass
    
    # Telefon raqam so'rash xabari
    try:
        _msg = await message.answer_photo(
            photo=FSInputFile('welcome.png'),
            caption=(
                "Balans AI'ga xush kelibsiz.\n\n"
                "💵 Balans AI — sizning shaxsiy buxgalteringiz.\n"
                "U har bir so‘mingizni hisoblab, daromad va xarajatlaringizni tartibda saqlaydi.\n\n"
                "• Har kuni pulingiz qayerga ketayotganini aniq bilasiz.\n"
                "• Har oy qancha tejayotganingizni ko‘rasiz.\n"
                "• AI hammasini kuzatadi — siz esa xotirjam bo‘lasiz.\n\n"
                "⏩ Boshlash: telefoningizni pastdagi tugma orqali yuboring."
            ),
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="Telefon raqamni yuborish", request_contact=True)]],
                resize_keyboard=True
            ),
            parse_mode="HTML"
        )

        await state.update_data(phone_request_msg_id=_msg.message_id)

    except Exception as _e:
        logging.warning(f"Welcome rasm yuborilmadi: {_e}")

    await message.answer(
        "Balans AI'ga xush kelibsiz.\n\n"
        "💵 Balans AI — sizning shaxsiy buxgalteringiz.\n"
        "U har bir so‘mingizni hisoblab, daromad va xarajatlaringizni tartibda saqlaydi.\n\n"
        "• Har kuni pulingiz qayerga ketayotganini aniq bilasiz.\n"
        "• Har oy qancha tejayotganingizni ko‘rasiz.\n"
        "• AI hammasini kuzatadi — siz esa xotirjam bo‘lasiz.\n\n"
        "⏩ Boshlash: telefoningizni pastdagi tugma orqali yuboring.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Telefon raqamni yuborish", request_contact=True)]],
            resize_keyboard=True
        ),
        parse_mode="Markdown"
    )

# Ism qabul qilish
@dp.message(UserStates.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    """Ismni qabul qilish"""
    user_id = message.from_user.id
    text = message.text
    
    # Agar /skip bo'lsa
    if text and text.lower() == '/skip':
        name = "Xojayin"
        await db.execute_query(
            "UPDATE users SET name = %s WHERE user_id = %s",
            (name, user_id)
        )
        
        # Eski xabarlarni o'chirish
        try:
            await message.delete()
            data = await state.get_data()
            if 'name_request_msg_id' in data:
                await message.bot.delete_message(chat_id=user_id, message_id=data['name_request_msg_id'])
        except:
            pass
        
        # So'rov noma so'rash
        await message.answer_photo(
            photo=FSInputFile('where_did_you_hear_us.png'),
            caption="Bizni qayerda eshitdingiz?",
            reply_markup=get_source_menu(),
            parse_mode="Markdown"
        )
        await state.set_state(UserStates.waiting_for_source)
        return
    
    # Ism AI tekshiruvi
    if text and len(text.strip()) > 0:
        # AI bilan tekshirish
        try:
            result = await ai_chat_free._check_name(text.strip())
            if result.get('is_valid', False):
                name = text.strip()
            else:
                name = "Xojayin"
        except:
            name = "Xojayin"
    else:
        name = "Xojayin"
    
    # Ismni saqlash
    await db.execute_query(
        "UPDATE users SET name = %s WHERE user_id = %s",
        (name, user_id)
    )
    
    # Eski xabarlarni o'chirish
    try:
        await message.delete()
        data = await state.get_data()
        if 'name_request_msg_id' in data:
            await message.bot.delete_message(chat_id=user_id, message_id=data['name_request_msg_id'])
    except:
        pass
    
    # So'rov noma so'rash
    await message.answer_photo(
        photo=FSInputFile('where_did_you_hear_us.png'),
        caption="Bizni qayerda eshitdingiz?",
        reply_markup=get_source_menu(),
        parse_mode="Markdown"
    )
    await state.set_state(UserStates.waiting_for_source)

# Tur tanlash handlerlari
@dp.callback_query(lambda c: c.data.startswith("account_type_"))
async def process_account_type(callback_query: CallbackQuery, state: FSMContext):
    """Hisob turini qabul qilish"""
    user_id = callback_query.from_user.id
    account_type = callback_query.data.split("_")[2]  # SHI, BIZNES
    
    # Account turini bazaga saqlash
    await db.execute_query(
        "UPDATE users SET account_type = %s WHERE user_id = %s",
        (account_type, user_id)
    )
    
    if account_type == 'BIZNES':
        # Biznes uchun ma'lumot va "3 kun sinab ko'rish" tugmasini ko'rsatish
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 3 kun bepul sinab ko'rish", callback_data="trial_tariff_BUSINESS")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_account_type")]
        ])
        
        try:
            await callback_query.message.edit_caption(
                caption=(
                    "🏢 **Business tarif**\n\n"
                    "Biznesingiz uchun to'liq boshqaruv tizimi!\n\n"
                    "✨ **Imkoniyatlar:**\n"
                    "• 📦 Ombor boshqaruvi (Mini CRM)\n"
                    "• 👥 Xodimlar va ularning maoshlarini boshqarish\n"
                    "• 🏪 Do'kon va filiallarni monitoring qilish\n"
                    "• 📊 Xarajatlar va foydaning tahlili\n"
                    "• 🤖 AI yordamida biznes tahlillari\n"
                    "• 📈 To'liq biznes hisobotlari\n"
                    "• ⚠️ Tovar kamayib qoldi bildirishnomalari\n\n"
                    "💰 **Narxi:** 199,000 so'm/oy\n\n"
                    "3 kunlik bepul sinov davomida barcha funksiyalardan foydalaning!"
                ),
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        except:
            await callback_query.message.delete()
            await callback_query.message.answer_photo(
                photo=FSInputFile('welcome.png'),
                caption=(
                    "🏢 **Business tarif**\n\n"
                    "Biznesingiz uchun to'liq boshqaruv tizimi!\n\n"
                    "✨ **Imkoniyatlar:**\n"
                    "• 📦 Ombor boshqaruvi (Mini CRM)\n"
                    "• 👥 Xodimlar va ularning maoshlarini boshqarish\n"
                    "• 🏪 Do'kon va filiallarni monitoring qilish\n"
                    "• 📊 Xarajatlar va foydaning tahlili\n"
                    "• 🤖 AI yordamida biznes tahlillari\n"
                    "• 📈 To'liq biznes hisobotlari\n"
                    "• ⚠️ Tovar kamayib qoldi bildirishnomalari\n\n"
                    "💰 **Narxi:** 199,000 so'm/oy\n\n"
                    "3 kunlik bepul sinov davomida barcha funksiyalardan foydalaning!"
                ),
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        await callback_query.answer()
        return
    
    # Shaxsiy tanlangan - Plus yoki Pro tanlash
    try:
        await callback_query.message.edit_caption(
            caption=(
                "👤 **Shaxsiy foydalanish**\n\n"
                "Quyidagi tariflardan birini tanlang:\n\n"
                "⭐ **Plus tarif** — 3 kun bepul sinov\n"
                "• AI yordamida matn va ovozli kiritish\n"
                "• Tezkor moliyaviy tahlillar\n"
                "• Shaxsiy byudjetni kuzatish\n"
                "• Eslatmalar va bildirishnomalar\n\n"
                "💎 **Pro tarif** — 3 kun bepul sinov\n"
                "• Plus tarifning barcha imkoniyatlari\n"
                "• Cheksiz AI so'rovlar\n"
                "• Kengaytirilgan hisobotlar\n"
                "• Shaxsiy moliyaviy maslahatlar\n"
                "• Maqsadlar va rejalar tuzish"
            ),
            reply_markup=get_personal_tariff_menu(),
            parse_mode='Markdown'
        )
    except:
        await callback_query.message.delete()
        await callback_query.message.answer_photo(
            photo=FSInputFile('welcome.png'),
            caption=(
                "👤 **Shaxsiy foydalanish**\n\n"
                "Quyidagi tariflardan birini tanlang:\n\n"
                "⭐ **Plus tarif** — 3 kun bepul sinov\n"
                "• AI yordamida matn va ovozli kiritish\n"
                "• Tezkor moliyaviy tahlillar\n"
                "• Shaxsiy byudjetni kuzatish\n"
                "• Eslatmalar va bildirishnomalar\n\n"
                "💎 **Pro tarif** — 3 kun bepul sinov\n"
                "• Plus tarifning barcha imkoniyatlari\n"
                "• Cheksiz AI so'rovlar\n"
                "• Kengaytirilgan hisobotlar\n"
                "• Shaxsiy moliyaviy maslahatlar\n"
                "• Maqsadlar va rejalar tuzish"
            ),
            reply_markup=get_personal_tariff_menu(),
            parse_mode='Markdown'
        )
    await callback_query.answer()

# Plus/Pro/Business tarif bepul sinov aktivlashtirish - TO'LIQ QAYTA YOZILGAN
@dp.callback_query(lambda c: c.data.startswith("trial_tariff_"))
async def process_trial_tariff(callback_query: CallbackQuery, state: FSMContext):
    """Plus, Pro yoki Business tarifni 3 kunlik bepul sinov bilan aktivlashtirish"""
    user_id = callback_query.from_user.id
    tariff = callback_query.data.split("_")[2]  # PLUS, PRO yoki BUSINESS
    
    from datetime import datetime, timedelta
    expires_at = datetime.now() + timedelta(days=3)
    
    # Tarif ma'lumotlari
    tariff_info = {
        'PLUS': {
            'name': 'Plus',
            'icon': '⭐',
            'features': (
                "• AI yordamida matn va ovozli kiritish\n"
                "• 300 ta matnli so'rov\n"
                "• 100 ta ovozli so'rov\n"
                "• Tezkor moliyaviy tahlillar\n"
                "• Shaxsiy byudjetni kuzatish\n"
                "• Eslatmalar va bildirishnomalar"
            )
        },
        'PRO': {
            'name': 'Pro',
            'icon': '💎',
            'features': (
                "• Cheksiz AI so'rovlar\n"
                "• Matn va ovozli kiritish\n"
                "• Kengaytirilgan hisobotlar\n"
                "• Shaxsiy moliyaviy maslahatlar\n"
                "• Maqsadlar va rejalar tuzish\n"
                "• To'liq tahlil va prognozlar"
            )
        },
        'BUSINESS': {
            'name': 'Business',
            'icon': '🏢',
            'features': (
                "• 📦 Ombor boshqaruvi (Mini CRM)\n"
                "• 👥 Xodimlar va maoshlarni boshqarish\n"
                "• 🏪 Do'kon va filiallarni monitoring\n"
                "• 📊 Xarajatlar va foyda tahlili\n"
                "• 🤖 AI biznes tahlillari\n"
                "• 📈 To'liq biznes hisobotlari"
            )
        }
    }
    
    info = tariff_info.get(tariff, tariff_info['PLUS'])
    
    # 1. Users jadvalini yangilash
    try:
        await db.execute_query(
            "UPDATE users SET tariff = %s, tariff_expires_at = %s WHERE user_id = %s",
            (tariff, expires_at, user_id)
        )
        logging.info(f"User {user_id} tarifi {tariff} ga yangilandi")
    except Exception as e:
        logging.error(f"{tariff}: users yangilashda xatolik: {e}")
    
    # 2. User subscriptions jadvaliga qo'shish
    try:
        await db.execute_query(
            """INSERT INTO user_subscriptions (user_id, tariff, is_active, expires_at) 
            VALUES (%s, %s, TRUE, %s) 
            ON DUPLICATE KEY UPDATE tariff = VALUES(tariff), is_active = TRUE, expires_at = VALUES(expires_at)""",
            (user_id, tariff, expires_at)
        )
    except Exception as e:
        logging.error(f"{tariff}: user_subscriptions da xatolik: {e}")
    
    # 3. PLUS tarifi uchun paket yaratish - MAJBURIY
    if tariff == 'PLUS':
        plus_package_created = False
        
        # 1-usul: Avvalgilarni o'chirib, yangi paket yaratish
        try:
            await db.execute_query(
                "DELETE FROM plus_package_purchases WHERE user_id = %s",
                (user_id,)
            )
            await db.execute_query(
                """INSERT INTO plus_package_purchases 
                (user_id, package_code, text_limit, voice_limit, text_used, voice_used, status, expires_at) 
                VALUES (%s, 'plus_trial', 300, 100, 0, 0, 'active', %s)""",
                (user_id, expires_at)
            )
            plus_package_created = True
            logging.info(f"User {user_id} uchun Plus paket yaratildi (1-usul)")
        except Exception as e:
            logging.error(f"PLUS paket yaratish 1-usul xatolik: {e}")
        
        # 2-usul: Agar 1-usul ishlamasa, ON DUPLICATE KEY UPDATE bilan
        if not plus_package_created:
            try:
                await db.execute_query(
                    """INSERT INTO plus_package_purchases 
                    (user_id, package_code, text_limit, voice_limit, text_used, voice_used, status, expires_at, purchased_at) 
                    VALUES (%s, 'plus_trial', 300, 100, 0, 0, 'active', %s, NOW())
                    ON DUPLICATE KEY UPDATE 
                    package_code = 'plus_trial', text_limit = 300, voice_limit = 100, 
                    text_used = 0, voice_used = 0, status = 'active', expires_at = %s""",
                    (user_id, expires_at, expires_at)
                )
                plus_package_created = True
                logging.info(f"User {user_id} uchun Plus paket yaratildi (2-usul)")
            except Exception as e:
                logging.error(f"PLUS paket yaratish 2-usul xatolik: {e}")
        
        # 3-usul: db.create_plus_package_purchase funksiyasidan foydalanish
        if not plus_package_created:
            try:
                await db.create_plus_package_purchase(user_id, 'plus_trial', 300, 100)
                plus_package_created = True
                logging.info(f"User {user_id} uchun Plus paket yaratildi (3-usul)")
            except Exception as e:
                logging.error(f"PLUS paket yaratish 3-usul xatolik: {e}")
        
        if not plus_package_created:
            logging.error(f"PLUS paket yaratish BUTUNLAY MUVAFFAQIYATSIZ user_id={user_id}")
    
    # Xabar yuborish
    try:
        await callback_query.message.delete()
    except:
        pass
    
    user_name = await get_user_name(user_id)
    
    await callback_query.message.answer(
        f"🎉 **3 kunlik bepul sinov aktivlashtirildi!**\n\n"
        f"Salom, {user_name}!\n\n"
        f"{info['icon']} **{info['name']} tarif** — 3 kun bepul sinov\n"
        f"📅 Tugash sanasi: {expires_at.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"✨ **Imkoniyatlar:**\n"
        f"{info['features']}\n\n"
        f"Sinov muddati tugagandan so'ng, tarifni davom ettirish uchun to'lov qilishingiz mumkin.",
        parse_mode='Markdown'
    )
    
    # Business tarif uchun to'g'ridan-to'g'ri menyu
    if tariff == 'BUSINESS':
        await callback_query.message.answer(
            "🏢 Business tarif menyusi:",
            reply_markup=get_business_menu()
        )
        await callback_query.answer(f"✅ {info['name']} tarif aktivlashtirildi!")
        await state.clear()
        return
    
    # PLUS va PRO uchun onboarding
    await callback_query.message.answer_photo(
        photo=FSInputFile('welcome.png'),
        caption=(
            "💰 **Onboarding bosqichi**\n\n"
            "1. Hozir balansingizda qancha pul bor?"
        ),
        parse_mode='Markdown'
    )
    
    await callback_query.answer(f"✅ {info['name']} tarif aktivlashtirildi!")
    await state.set_state(UserStates.onboarding_balance)

# Boshlash tugmasini bosish
@dp.callback_query(lambda c: c.data == "start_onboarding")
async def start_onboarding(callback_query: CallbackQuery, state: FSMContext):
    """Onboarding bosqichi boshlash"""
    try:
        await callback_query.message.delete()
    except:
        pass
    
    await callback_query.message.answer_photo(
        photo=FSInputFile('welcome.png'),
        caption=(
            "💰 **Onboarding bosqichi**\n\n"
            "1. Hozir balansingizda qancha pul bor?"
        ),
        parse_mode='Markdown'
    )
    await callback_query.answer()
    await state.set_state(UserStates.onboarding_balance)

# Aktivlashtirish tugmalari
@dp.callback_query(lambda c: c.data.startswith("activate_"))
async def activate_account_type(callback_query: CallbackQuery):
    """Aktivlashtirish tugmasi bosilganda"""
    account_type = callback_query.data.split("_")[1]  # oila yoki biznes
    
    # Modal xabar yuborish
    await callback_query.answer(
        "⚡ Tez orada ishga tushadi!",
        show_alert=True
    )

# Orqaga tugmasi
@dp.callback_query(lambda c: c.data == "back_to_account_type")
async def back_to_account_type(callback_query: CallbackQuery, state: FSMContext):
    """Hisob turi tanlash sahifasiga qaytish"""
    await callback_query.message.delete()
    await callback_query.message.answer_photo(
        photo=FSInputFile('hisob_turini_tanlang.png'),
        caption=(
            "🏢 **Hisob turini tanlang**\n\n"
            "Iltimos, hisobingiz uchun mos turini tanlang:"
        ),
        reply_markup=get_account_type_menu(),
        parse_mode="Markdown"
    )
    await callback_query.answer()
    await state.set_state(UserStates.waiting_for_account_type)

# Onboarding: 1-qadam — naqd balans
@dp.message(UserStates.waiting_for_initial_cash)
async def onboarding_initial_cash(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    txt = message.text.replace(' ', '').replace(',', '').replace("'", '')
    try:
        cash = float(txt)
        if cash < 0:
            raise ValueError()
    except Exception:
        await message.answer("❌ Noto'g'ri qiymat. Iltimos, faqat musbat son kiriting (masalan: 0 yoki 100000).")
        return

    await state.update_data(initial_cash=cash)
    # Avvalgi promptni va user xabarini o'chirishga urinamiz
    try:
        data_for_cleanup = await state.get_data()
        last_prompt_id = data_for_cleanup.get('onboarding_last_prompt_id')
        if last_prompt_id:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=last_prompt_id)
        await message.delete()
    except Exception:
        pass

    _msg = await message.answer(
        "💳 Endi kartadagi balansni kiriting.\n"
        "Masalan: 0 yoki 200000",
    )
    await state.set_state(UserStates.waiting_for_initial_card)
    try:
        await state.update_data(onboarding_last_prompt_id=_msg.message_id)
    except Exception:
        pass

# Onboarding: 2-qadam — karta balans
@dp.message(UserStates.waiting_for_initial_card)
async def onboarding_initial_card(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    txt = message.text.replace(' ', '').replace(',', '').replace("'", '')
    try:
        card = float(txt)
        if card < 0:
            raise ValueError()
    except Exception:
        await message.answer("❌ Noto'g'ri qiymat. Iltimos, faqat musbat son kiriting (masalan: 0 yoki 200000).")
        return

    data = await state.get_data()
    cash = float(data.get('initial_cash', 0))
    await state.update_data(initial_card=card)

    # Oldingi promptni va user xabarini o'chirishga urinamiz
    try:
        last_prompt_id = data.get('onboarding_last_prompt_id')
        if last_prompt_id:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=last_prompt_id)
        await message.delete()
    except Exception:
        pass

    # Balanslarni DBga saqlash: ikkita tranzaksiya sifatida (income)
    total_initial = cash + card
    if cash > 0:
        await db.add_transaction(user_id, 'income', cash, 'boshlang_ich_naqd', 'Onboarding: boshlang ich naqd balans')
    if card > 0:
        await db.add_transaction(user_id, 'income', card, 'boshlang_ich_karta', 'Onboarding: boshlang ich karta balans')
    # Agar ikkalasi ham 0 bo'lsa, onboarding yakunlanganini belgilash uchun marker yozuv qo'yamiz
    if cash == 0 and card == 0:
        try:
            await db.add_transaction(user_id, 'income', 0, 'boshlang_ich_naqd', 'Onboarding: boshlang ich (0)')
        except Exception:
            pass

    # Keyingi bosqich: qarzlarni kiritish
    _msg = await message.answer(
        "📒 2-qadam: Hozir mavjud qarzlaringizni kiriting.\n\n"
        "- Kimga qarz berdingiz yoki kimdan qarzdorsiz (ism yoki izoh).\n"
        "- Summani kiriting.\n"
        "- Qaytarish sanasini kiriting (ixtiyoriy).\n\n"
        "Tugallash uchun '✅ Tayyor' tugmasini bosing.",
        reply_markup=get_onboarding_debt_menu()
    )
    try:
        await state.update_data(onboarding_last_prompt_id=_msg.message_id)
    except Exception:
        pass
    await state.set_state(UserStates.onboarding_waiting_for_debt_action)

# Onboarding: qarzlar menyusi tugmalari
@dp.message(lambda m: m.text in ["➕ Qarzni qo'shish", "✅ Tayyor"], UserStates.onboarding_waiting_for_debt_action)
async def onboarding_debt_action(message: types.Message, state: FSMContext):
    if message.text == "✅ Tayyor":
        data = await state.get_data()
        tariff = data.get('onboarding_tariff', 'NONE')
        user_id = message.from_user.id

        # Tanlangan tarifni aktiv qilish
        await db.execute_query("UPDATE users SET tariff = %s WHERE user_id = %s", (tariff, user_id))

        # Yakuniy menyu
        user_name = await get_user_name(user_id)
        if tariff in ('PLUS', 'PRO', 'MAX', 'BUSINESS'):
            await message.answer(
                f"✅ Onboarding yakunlandi!\n\nSalom, {user_name}!\nMatn yoki ovoz yuboring, AI qayta ishlaydi:",
                reply_markup=get_premium_menu(),
                parse_mode='Markdown'
            )
        else:
            await message.answer(
                f"✅ Onboarding yakunlandi!\n\nSalom, {user_name}!\nBalans AI'dan foydalanishni davom ettirish uchun paket tanlang.",
                reply_markup=get_plus_purchase_keyboard(),
                parse_mode='Markdown'
            )
        await state.clear()
        return

    # ➕ Qarzni qo'shish
    # Onboarding qarz oqimi flagini saqlab qo'yamiz
    await state.update_data(is_onboarding_debt=True)

    await message.answer(
        "Qarz turini tanlang:",
        reply_markup=get_debt_type_menu()
    )
    await state.set_state(UserStates.waiting_for_debt_type)


# Ism qabul qilish
@dp.message(UserStates.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    """Ismni qabul qilish"""
    user_id = message.from_user.id
    name = message.text.strip()
    
    if not name or name.lower() in ['skip', 'otkazib yuborish', 'otkazib', ''] or name == "Xojayin deb chaqir":
        name = "Xojayin"
    
    # Avvalgi promptni va user xabarini o'chirishga harakat qilamiz
    try:
        data_for_cleanup = await state.get_data()
        last_prompt_id = data_for_cleanup.get('onboarding_last_prompt_id')
        if last_prompt_id:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=last_prompt_id)
        await message.delete()
    except Exception:
        pass

    # Ismni saqlash
    await db.execute_query(
        "UPDATE users SET name = %s WHERE user_id = %s",
        (name, user_id)
    )
    
    # Avval reply keyboardni olib tashlaymiz (minimal xabar bilan)
    _greet = await message.answer("Tanishganimdan Xursandman 🙂", reply_markup=ReplyKeyboardRemove())
    try:
        LAST_GREETING_MESSAGE_ID[message.from_user.id] = _greet.message_id
    except Exception:
        pass
    # So'ngra keyingi bosqichni rasm + caption bilan ko'rsatamiz
    _next = await message.answer_photo(
        photo=FSInputFile('where_did_you_hear_us.png'),
        caption=(
            f"{name} bizni qayerda eshitdingiz?"
        ),
        reply_markup=get_source_menu(),
        parse_mode="Markdown"
    )
    # Oldin yuborilgan "Tanishganimdan Xursandman" xabarini o'chiramiz
    try:
        greet_id = LAST_GREETING_MESSAGE_ID.get(message.from_user.id)
        if greet_id:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=greet_id)
            LAST_GREETING_MESSAGE_ID.pop(message.from_user.id, None)
    except Exception:
        pass
    try:
        await state.update_data(onboarding_last_prompt_id=_next.message_id)
    except Exception:
        pass
    await state.set_state(UserStates.waiting_for_source)

# Manba tanlash
# So'rov noma qabul qilish - faqat callback
@dp.callback_query(lambda c: c.data.startswith("source_"), UserStates.waiting_for_source)
async def process_source(callback_query: CallbackQuery, state: FSMContext):
    """Manbani qabul qilish"""
    user_id = callback_query.from_user.id
    source = callback_query.data.split("_")[1]
    
    # Manbani saqlash
    await db.execute_query(
        "UPDATE users SET source = %s WHERE user_id = %s",
        (source, user_id)
    )
    
    # Xabarni o'chirish va yangi xabar yuborish
    try:
        await callback_query.message.delete()
    except Exception:
        pass
    
    # Tur tanlash
    await callback_query.message.answer_photo(
        photo=FSInputFile('hisob_turini_tanlang.png'),
        caption=(
            "🏢 **Hisob turini tanlang**\n\n"
            "Iltimos, hisobingiz uchun mos turini tanlang:"
        ),
        reply_markup=get_account_type_menu(),
        parse_mode="Markdown"
    )
    await callback_query.answer()
    await state.set_state(UserStates.waiting_for_account_type)

# Help komandasi
@dp.message(Command("help"))
async def help_command(message: types.Message):
    """Yordam komandasi"""
    help_text = get_help_text()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_profile")]
    ])
    await message.answer(help_text, parse_mode="HTML", reply_markup=keyboard)

def get_help_text():
    """Yordam matnini qaytaradi"""
    return """
<b>📖 Balans AI - Yordam</b>

<b>🤖 Asosiy funksiyalar:</b>
• Moliyaviy ma'lumotlarni kiritish (matn yoki ovoz)
• Hisobotlar va tahlillar
• AI yordamchi maslahatlari (Premium tariflar)

<b>💰 Moliyaviy ma'lumotlar:</b>
• <b>Kirim:</b> "100 ming tushdi", "Ish haqi 500k"
• <b>Chiqim:</b> "Taksi 50k", "Ovqat 30 ming"
• <b>Qarz:</b> "Ali 200k qarz berdim", "Vali 100k qarz oldim"

<b>📊 Hisobotlar:</b>
• Balans ma'lumotlari
• Valyutalar bo'yicha tahlil
• Qarzlar ro'yxati
• So'nggi tranzaksiyalar

<b>🎯 Qanday ishlatish:</b>
1. Matn yoki ovozli xabar yuboring
2. AI avtomatik aniqlaydi va saqlaydi
3. Hisobotlar bo'limida ko'ring

<b>📱 Buyruqlar:</b>
/start - Botni qayta ishga tushirish
/help - Yordam sahifasi

<b>💡 Maslahat:</b>
Tabiiy til bilan yozing yoki gapiring. AI tushunadi va saqlaydi!
    """

# Tezkor balans komandasi
# /balance va /balans buyruqlari olib tashlandi - endi 📊 Hisobotlar tugmasi orqali ko'rish mumkin

# Bepul tarif - Kirim qo'shish
@dp.message(lambda message: message.text == "➕ Kirim")
async def add_income(message: types.Message, state: FSMContext):
    """Kirim qo'shish"""
    user_tariff = await get_user_tariff(message.from_user.id)
    if user_tariff != "FREE":
        return
    
    await message.answer(
        "💰 *Kirim qo'shish*\n\n"
        "Summani kiriting (masalan: 100000):",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await state.set_state(UserStates.waiting_for_amount)
    await state.update_data(transaction_type="income")

# Bepul tarif - Chiqim qo'shish
@dp.message(lambda message: message.text == "➖ Chiqim")
async def add_expense(message: types.Message, state: FSMContext):
    """Chiqim qo'shish"""
    user_tariff = await get_user_tariff(message.from_user.id)
    if user_tariff != "FREE":
        return
    # Naqd balansni tekshirish: 0 yoki manfiy bo'lsa ogohlantirish
    balances = await db.get_balances(message.from_user.id)
    if balances['cash_balance'] <= 0:
        await message.answer(
            "⚠️ Sizda naqd balans yo'q. Ehtimol xato kiritgandirsiz yoki avval kirim/qarz olish kiritib, keyin chiqim kiriting.",
            parse_mode='Markdown'
        )
    
    await message.answer(
        "💸 *Chiqim qo'shish*\n\n"
        "Summani kiriting (masalan: 50000):",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await state.set_state(UserStates.waiting_for_amount)
    await state.update_data(transaction_type="expense")

# Qarz ko'rish funksiyalari - o'chirildi

# Qarz turini qabul qilish
@dp.callback_query(UserStates.waiting_for_debt_type, lambda c: c.data.startswith("debt_type_"))
async def process_debt_type(callback_query: CallbackQuery, state: FSMContext):
    """Qarz turini qabul qilish"""
    debt_type = callback_query.data.replace("debt_type_", "")
    
    # Qarz turini saqlash
    await state.update_data(debt_type=debt_type)
    
    if debt_type == "lent":  # Qarz berish
        # Onboardingda (eski qarzlarni kiritish) balans cheklovini bekor qilamiz
        st_data = await state.get_data()
        is_onboarding = bool(st_data.get('onboarding_tariff') or st_data.get('is_onboarding_debt'))
        if not is_onboarding:
            # Naqd balans yetarlimi? Yetmasa ruxsat bermaymiz
            balances = await db.get_balances(callback_query.from_user.id)
            if balances['cash_balance'] <= 0:
                await callback_query.answer("❌ Naqd balans yetarli emas, qarz bera olmaysiz.", show_alert=True)
                return
        # Qarz olgan odamni ismini so'rash
        await callback_query.message.edit_text(
            "💸 *Qarz berish*\n\n"
            "Qarz olgan odamning ismini kiriting:",
            parse_mode="Markdown"
        )
        await callback_query.message.answer(
            "Qarz olgan odamning ismini kiriting:",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(UserStates.waiting_for_debt_person)
    else:  # Qarz olish
        # Summa so'rash
        await callback_query.message.edit_text(
            "💰 *Qarz olish*\n\n"
            "Summani kiriting (masalan: 200000):",
            parse_mode="Markdown"
        )
        await callback_query.message.answer(
            "Summa kiriting:",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(UserStates.waiting_for_amount)
    
    await callback_query.answer()

# Qarz olgan odamni ismini qabul qilish
@dp.message(UserStates.waiting_for_debt_person)
async def process_debt_person(message: types.Message, state: FSMContext):
    """Qarz olgan odamni ismini qabul qilish"""
    debt_person = message.text.strip()
    
    if not debt_person:
        await message.answer("Ism kiritilmadi. Qaytadan kiriting:")
        return
    
    # Qarz olgan odamni ismini saqlash
    await state.update_data(debt_person=debt_person)
    
    # Summa so'rash
    await message.answer(
        "💸 *Qarz berish*\n\n"
        "Summani kiriting (masalan: 200000):",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await state.set_state(UserStates.waiting_for_amount)

# Qarz ismni tahrirlash
@dp.message(UserStates.waiting_for_debt_edit_name)
async def process_debt_edit_name(message: types.Message, state: FSMContext):
    """Qarz ismini tahrirlash"""
    user_id = message.from_user.id
    person_name = message.text.strip()
    
    if not person_name:
        await message.answer("❌ Ism kiritilmadi. Qaytadan kiriting:")
        return
    
    data = await state.get_data()
    trans_id = data.get('editing_transaction_id')
    
    if not trans_id:
        await message.answer("❌ Tranzaksiya topilmadi. Qaytadan urinib ko'ring.")
        await state.clear()
        return
    
    # Tranzaksiyani yangilash
    update_result = await db.update_transaction(trans_id, user_id, person_name=person_name)
    
    if update_result.get('success'):
        # Kontaktni yaratish/yangilash
        contact = await db.get_or_create_contact(user_id, person_name)
        
        await message.answer(
            f"✅ **Ism qo'shildi!**\n\n👤 {person_name}\n\n"
            f"{'Kontakt qoshildi' if contact and contact.get('is_new') else 'Mavjud kontaktdagi shaxs'}",
            parse_mode='Markdown'
        )
        await state.clear()
    else:
        await message.answer(f"❌ {update_result.get('message', 'Xatolik yuz berdi')}")
        await state.clear()

# Summa tahrirlash
@dp.message(UserStates.waiting_for_trans_edit_amount)
async def process_trans_edit_amount(message: types.Message, state: FSMContext):
    """Tranzaksiya summasini tahrirlash"""
    user_id = message.from_user.id
    try:
        amount = float(message.text.replace(',', '').replace(' ', ''))
        if amount <= 0:
            await message.answer("❌ Summa 0 dan katta bo'lishi kerak. Qaytadan kiriting:")
            return
        
        data = await state.get_data()
        trans_id = data.get('editing_transaction_id')
        
        if not trans_id:
            await message.answer("❌ Tranzaksiya topilmadi. Qaytadan urinib ko'ring.")
            await state.clear()
            return
        
        # Database da UPDATE qilish
        await db.execute_query(
            "UPDATE transactions SET amount = %s WHERE id = %s AND user_id = %s",
            (amount, trans_id, user_id)
        )
        
        await message.answer(
            f"✅ **Summa yangilandi!**\n\nYangi summa: {amount:,.0f} so'm",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_transaction")]
            ])
        )
        await state.clear()
        
    except ValueError:
        await message.answer("❌ Noto'g'ri summa format! Iltimos, raqam kiriting.")

# Izoh tahrirlash
@dp.message(UserStates.waiting_for_trans_edit_description)
async def process_trans_edit_description(message: types.Message, state: FSMContext):
    """Tranzaksiya izohini tahrirlash"""
    user_id = message.from_user.id
    description = message.text.strip()
    
    data = await state.get_data()
    trans_id = data.get('editing_transaction_id')
    
    if not trans_id:
        await message.answer("❌ Tranzaksiya topilmadi. Qaytadan urinib ko'ring.")
        await state.clear()
        return
    
    # Database da UPDATE qilish
    await db.execute_query(
        "UPDATE transactions SET description = %s WHERE id = %s AND user_id = %s",
        (description, trans_id, user_id)
    )
    
    await message.answer(
        f"✅ **Izoh yangilandi!**\n\nYangi izoh: {description}",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_transaction")]
        ])
    )
    await state.clear()

# Qarz qaytarish sanasini tahrirlash
@dp.message(UserStates.waiting_for_debt_edit_date)
async def process_debt_edit_date(message: types.Message, state: FSMContext):
    """Qarz qaytarish sanasini tahrirlash"""
    user_id = message.from_user.id
    due_date_str = message.text.strip()
    
    if not due_date_str:
        await message.answer("❌ Sana kiritilmadi. Qaytadan kiriting:")
        return
    
    # Sana formatini tekshirish va parse qilish
    from datetime import datetime
    try:
        due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
        due_date_str = due_date.strftime('%Y-%m-%d')
    except ValueError:
        await message.answer("❌ Sana formati noto'g'ri. Iltimos, YYYY-MM-DD formatida kiriting (masalan: 2025-12-31):")
        return
    
    data = await state.get_data()
    trans_id = data.get('editing_transaction_id')
    
    if not trans_id:
        await message.answer("❌ Tranzaksiya topilmadi. Qaytadan urinib ko'ring.")
        await state.clear()
        return
    
    # Tranzaksiyani yangilash
    update_result = await db.update_transaction(trans_id, user_id, due_date=due_date_str)
    
    if update_result.get('success'):
        await message.answer(
            f"✅ **Qaytarish sanasi qo'shildi!**\n\n📅 {due_date.strftime('%d-%m-%Y')}\n\n"
            f"✅ Eslatma yaratildi!",
            parse_mode='Markdown'
        )
        await state.clear()
    else:
        await message.answer(f"❌ {update_result.get('message', 'Xatolik yuz berdi')}")
        await state.clear()

# Bekor qilish funksiyasi
@dp.message(lambda message: message.text == "❌ Bekor qilish")
async def cancel_operation(message: types.Message, state: FSMContext):
    """Amalni bekor qilish"""
    user_tariff = await get_user_tariff(message.from_user.id)
    
    await message.answer(
        "❌ *Amal bekor qilindi*\n\n"
        "Asosiy menyuga qaytildi.",
        reply_markup=(
            get_business_menu() if user_tariff == "BUSINESS"
            else get_premium_menu() if user_tariff in ("PLUS", "PRO", "MAX")
            else None
        ),
        parse_mode="Markdown"
    )
    if user_tariff in (None, "FREE"):
        await message.answer(
            "Balans AI'dan foydalanishni davom ettirish uchun Plus paket sotib oling yoki Pro tarifga o'ting.",
            reply_markup=get_plus_purchase_keyboard(),
            parse_mode="Markdown"
        )
    await state.clear()

# Summa qabul qilish
@dp.message(UserStates.waiting_for_amount)
async def process_amount(message: types.Message, state: FSMContext):
    """Summani qabul qilish"""
    try:
        amount = float(message.text.replace(',', '').replace(' ', ''))
        if amount <= 0:
            await message.answer("❌ Summa 0 dan katta bo'lishi kerak!")
            return
        
        user_id = message.from_user.id
        data = await state.get_data()
        transaction_type = data.get('transaction_type')
        
        # Xarajat qilishda balans tekshirish
        if transaction_type == "expense":
            balances = await db.get_balances(user_id)
            if balances['cash_balance'] <= 0:
                await message.answer(
                    "❌ **Naqd balans yetarli emas!**\n\n"
                    f"💰 **Hozirgi naqd balans:** {balances['cash_balance']:,.0f} so'm\n\n"
                    "Avval kirim yoki qarz olish kiritib, keyin xarajat qiling.",
                    parse_mode="Markdown"
                )
                return
            elif amount > balances['cash_balance']:
                await message.answer(
                    "❌ **Xarajat miqdori naqd balansdan ko'p!**\n\n"
                    f"💰 **Hozirgi naqd balans:** {balances['cash_balance']:,.0f} so'm\n"
                    f"💸 **Xarajat miqdori:** {amount:,.0f} so'm\n"
                    f"❌ **Yetishmayotgan:** {amount - balances['cash_balance']:,.0f} so'm\n\n"
                    "Avval kirim yoki qarz olish kiritib, keyin xarajat qiling.",
                    parse_mode="Markdown"
                )
                return
        
        # Qarz berishda balans tekshirish
        elif transaction_type == "debt" and data.get('debt_type') == 'lent':
            st_data = await state.get_data()
            is_onboarding = bool(st_data.get('onboarding_tariff') or st_data.get('is_onboarding_debt'))
            if not is_onboarding:
                balances = await db.get_balances(user_id)
                if balances['cash_balance'] <= 0:
                    await message.answer(
                        "❌ **Naqd balans yetarli emas!**\n\n"
                        f"💰 **Hozirgi naqd balans:** {balances['cash_balance']:,.0f} so'm\n\n"
                        "Qarz berish uchun avval kirim kiritib, naqd balansni to'ldiring.",
                        parse_mode="Markdown"
                    )
                    return
                elif amount > balances['cash_balance']:
                    await message.answer(
                        "❌ **Qarz miqdori naqd balansdan ko'p!**\n\n"
                        f"💰 **Hozirgi naqd balans:** {balances['cash_balance']:,.0f} so'm\n"
                        f"💸 **Qarz miqdori:** {amount:,.0f} so'm\n"
                        f"❌ **Yetishmayotgan:** {amount - balances['cash_balance']:,.0f} so'm\n\n"
                        "Qarz berish uchun avval kirim kiritib, naqd balansni to'ldiring.",
                        parse_mode="Markdown"
                    )
                    return
        
        await state.update_data(amount=amount)
        
        if transaction_type == "income":
            # Tavsif funksiyasini olib tashlash - to'g'ridan-to'g'ri kategoriya so'rash
            await message.answer(
                "📂 *Kategoriyani tanlang:*",
                reply_markup=get_income_category_menu(),
                parse_mode="Markdown"
            )
            await state.set_state(UserStates.waiting_for_category)
        else:
            # Kategoriya tanlash
            if transaction_type == "expense":
                await message.answer(
                    "📂 *Kategoriyani tanlang:*",
                    reply_markup=get_expense_category_menu(),
                    parse_mode="Markdown"
                )
            else:  # debt
                await message.answer(
                    "📂 *Kategoriyani tanlang:*",
                    reply_markup=get_debt_category_menu(),
                    parse_mode="Markdown"
                )
            await state.set_state(UserStates.waiting_for_category)
            
    except ValueError:
        await message.answer("❌ Noto'g'ri summa format! Iltimos, raqam kiriting.")

# Tavsif funksiyasi olib tashlandi - endi to'g'ridan-to'g'ri kategoriya so'raladi

@dp.message(UserStates.waiting_for_debt_due_date)
async def process_debt_due_date(message: types.Message, state: FSMContext):
    text = message.text.strip()
    due_date = None
    if text.lower() != 'skip':
        try:
            from datetime import datetime
            due_date = datetime.strptime(text, '%Y-%m-%d').date()
        except Exception:
            await message.answer("❌ Sana formati noto'g'ri. Masalan: 2025-10-25 yoki 'skip' deb yozing.")
            return
    await state.update_data(due_date=due_date)
    # Endi kategoriya so'raymiz (qarz uchun)
    await message.answer(
        "📂 *Kategoriyani tanlang:*",
        reply_markup=get_debt_category_menu(),
        parse_mode='Markdown'
    )
    await state.set_state(UserStates.waiting_for_category)

# Kategoriya tanlash
@dp.callback_query(lambda c: c.data.startswith("cat_"), UserStates.waiting_for_category)
async def process_category(callback_query: CallbackQuery, state: FSMContext):
    """Kategoriyani qabul qilish"""
    user_id = callback_query.from_user.id
    category = callback_query.data.split("_", 1)[1]
    
    if category == "skip":
        category = "Boshqa"
    
    data = await state.get_data()
    transaction_type = data.get('transaction_type')
    amount = data.get('amount')
    description = data.get('description', '')
    currency = data.get('currency', 'UZS')  # Valyuta olish (default UZS)
    
    # Valyutani to'g'ri formatda saqlash
    currency = currency.upper() if currency else 'UZS'
    if currency not in ['UZS', 'USD', 'EUR', 'RUB', 'TRY']:
        currency = 'UZS'
    
    # Qarzlar uchun transaction_type ni to'g'ri o'rnatish
    if not transaction_type:
        transaction_type = "debt"  # Default qarz
    
    # Tranzaksiyani saqlash
    try:
        due_date = data.get('due_date') if transaction_type == 'debt' else None
        debt_type = data.get('debt_type') if transaction_type == 'debt' else None
        # debt_type ni debt_direction ga o'zgartirish
        debt_direction = None
        if debt_type == 'lent':
            debt_direction = 'lent'
        elif debt_type == 'borrowed':
            debt_direction = 'borrowed'
        
        # Onboarding flag: onboardingda tarixiy qarzlar balansni o'zgartirmasligi kerak
        st_data = await state.get_data()
        is_onboarding = bool(st_data.get('onboarding_tariff') or st_data.get('is_onboarding_debt'))

        # Qarz berish (lent): balansdan kamaytirish faqat onboarding tugaganidan keyin
        if transaction_type == 'debt' and debt_type == 'lent':
            if not is_onboarding:
                # Balansni tekshirish (qayta tekshirish)
                balances = await db.get_balances(user_id)
                if balances['cash_balance'] < amount:
                    await callback_query.answer("❌ Naqd balans yetarli emas!", show_alert=True)
                    await state.clear()
                    return

            # Qarz berish qaydini saqlaymiz (valyuta bilan)
            insert_id = await db.execute_insert(
                "INSERT INTO transactions (user_id, transaction_type, amount, category, currency, description, due_date, debt_direction) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (user_id, transaction_type, amount, category, currency, description, due_date, debt_direction)
            )

            # Onboarding tugagan bo'lsa, balansdan chiqim yozamiz (valyuta bilan)
            if not is_onboarding:
                await db.execute_query(
                    "INSERT INTO transactions (user_id, transaction_type, amount, category, currency, description) VALUES (%s, %s, %s, %s, %s, %s)",
                    (user_id, 'expense', amount, f"Qarz berish: {category}", currency, f"Qarz berish - {description}")
                )

        # Qarz olish (borrowed): balansga kirim yozish faqat onboarding tugaganidan keyin
        elif transaction_type == 'debt' and debt_type == 'borrowed':
            # Qarz olish qaydini saqlaymiz (valyuta bilan)
            insert_id = await db.execute_insert(
                "INSERT INTO transactions (user_id, transaction_type, amount, category, currency, description, due_date, debt_direction) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (user_id, transaction_type, amount, category, currency, description, due_date, debt_direction)
            )

            # Onboarding tugagan bo'lsa, balansga kirim yozamiz (valyuta bilan)
            if not is_onboarding:
                await db.execute_query(
                    "INSERT INTO transactions (user_id, transaction_type, amount, category, currency, description) VALUES (%s, %s, %s, %s, %s, %s)",
                    (user_id, 'income', amount, f"Qarz olish: {category}", currency, f"Qarz olish - {description}")
                )

        else:
            # Oddiy tranzaksiya (kirim, chiqim) - valyuta bilan
            insert_id = await db.execute_insert(
                "INSERT INTO transactions (user_id, transaction_type, amount, category, currency, description, due_date, debt_direction) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (user_id, transaction_type, amount, category, currency, description, due_date, debt_direction)
            )
        
        type_emoji = {"income": "📈", "expense": "📉", "debt": "💳"}.get(transaction_type, "❓")
        type_name = {"income": "Kirim", "expense": "Chiqim", "debt": "Qarz"}.get(transaction_type, "Tranzaksiya")
        
        # Valyuta nomini ko'rsatish
        currency_names = {'UZS': "so'm", 'USD': "dollar", 'EUR': "evro", 'RUB': "rubl", 'TRY': "lira"}
        currency_name = currency_names.get(currency, currency)
        currency_symbols = {'UZS': "🇺🇿", 'USD': "🇺🇸", 'EUR': "🇪🇺", 'RUB': "🇷🇺", 'TRY': "🇹🇷"}
        currency_symbol = currency_symbols.get(currency, "💰")
        
        # So'mga o'girilgan qiymat (agar UZS bo'lmasa)
        if currency != 'UZS':
            rates = await db.get_currency_rates()
            rate = rates.get(currency, 1)
            amount_uzs = amount * rate
            amount_text = f"{currency_symbol} {amount:,.2f} {currency_name} ({amount_uzs:,.0f} so'm)"
        else:
            amount_text = f"{amount:,.0f} so'm"
        
        # Qarzlar uchun qarz turini ko'rsatish
        debt_type_text = ""
        if transaction_type == "debt":
            debt_type = data.get('debt_type', 'borrowed')
            debt_person = data.get('debt_person', '')
            debt_type_name = "Qarz oldim" if debt_type == "borrowed" else "Qarz berdim"
            debt_type_text = f"🔄 {debt_type_name}"
            if debt_person:
                debt_type_text += f" ({debt_person})"
            debt_type_text += "\n"
        
        await callback_query.message.edit_text(
            f"✅ *{type_name} qo'shildi!*\n\n"
            f"{type_emoji} {amount_text}\n"
            f"{debt_type_text}"
            f"📂 {category}\n",
            parse_mode="Markdown"
        )
        # Qarz eslatmalari endi save_confirmed_transactions da yaratiladi (faqat qaytarish sanasi bo'lsa)

        # Onboarding davomida bo'lsa: foydalanuvchini yana qarz menyusiga qaytaramiz
        st_data = await state.get_data()
        is_onboarding = bool(st_data.get('onboarding_tariff') or st_data.get('is_onboarding_debt'))
        if is_onboarding:
            await callback_query.message.answer_photo(
                photo=FSInputFile('welcome.png'),
                caption="Yana qarz qo'shishni istaysizmi yoki tugatamizmi?",
                reply_markup=get_onboarding_debt_menu()
            )
            await state.set_state(UserStates.onboarding_waiting_for_debt_action)
        else:
            # Onboarding emas: amaldagi tarifga mos menyuni ko'rsatamiz
            current_tariff = await get_user_tariff(user_id)
            if current_tariff == 'BUSINESS':
                await callback_query.message.answer(
                    "Business menyusi:",
                    reply_markup=get_business_menu()
                )
            elif current_tariff in ('PLUS', 'PRO', 'MAX'):
                await callback_query.message.answer(
                    "Premium menyusi:",
                    reply_markup=get_premium_menu()
                )
            else:
                await callback_query.message.answer(
                    "Balans AI bilan davom etish uchun paket tanlang:",
                    reply_markup=get_plus_purchase_keyboard()
                )
        
    except Exception as e:
        logging.error(f"Tranzaksiya saqlashda xatolik: {e}")
        await callback_query.message.edit_text(
            "❌ Xatolik yuz berdi! Qaytadan urinib ko'ring.",
            parse_mode="Markdown"
        )
        # Onboarding bo'lsa, jarayonni davom ettirish uchun menyuga qaytaramiz
        st_data = await state.get_data()
        is_onboarding = bool(st_data.get('onboarding_tariff') or st_data.get('is_onboarding_debt'))
        if is_onboarding:
            await callback_query.message.answer_photo(
                photo=FSInputFile('welcome.png'),
                caption="Yana urinib ko'rasizmi yoki tugatamizmi?",
                reply_markup=get_onboarding_debt_menu()
            )
            await state.set_state(UserStates.onboarding_waiting_for_debt_action)
        else:
            await callback_query.message.answer(
                "Balans AI bilan davom etish uchun paket tanlang:",
                reply_markup=get_plus_purchase_keyboard()
            )

    # Onboarding bo'lsa state'ni tozalamaymiz; onboarding yakunida tozalanadi
    st_data = await state.get_data()
    is_onboarding = bool(st_data.get('onboarding_tariff') or st_data.get('is_onboarding_debt'))
    if not is_onboarding:
        await state.clear()

# Hisobotlar menyusi
@dp.message(lambda message: message.text == "📊 Hisobotlar")
async def reports_menu(message: types.Message, state: FSMContext):
    """Hisobotlar menyusi - tushunarli va qulay ko'rsatish"""
    user_id = message.from_user.id
    user_tariff = await get_user_tariff(user_id)
    
    # Biznes tarifi uchun alohida handler
    if user_tariff == "BUSINESS":
        await business_reports_handler(message, state)
        return
    
    try:
        # Ko'p valyutali balans ma'lumotlarini olish
        multi_balance = await db.get_balance_multi_currency(user_id)
        total_uzs = multi_balance.get('total_uzs', {})
        by_currency = multi_balance.get('by_currency', {})
    
        # Eng oxirgi 3 ta tranzaksiyani olish
        recent_query = """
            SELECT 
                transaction_type,
                amount,
                currency,
                category,
                description,
                debt_direction,
                created_at
            FROM transactions
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 3
        """
        recent_transactions = await db.execute_query(recent_query, (user_id,))
        
        # Xabarni yaratish
        # Markdown formatida xatolik bo'lishi mumkin, shuning uchun HTML ga o'girish
        safe_message = "<b>📊 Hisobotlar</b>\n\n"
        
        # 1. Umumiy balans (kirim/chiqim ko'rsatilmaydi)
        total_balance = total_uzs.get('balance', 0)
        safe_message += "<b>💰 Umumiy balans (so'mda)</b>\n"
        safe_message += f"💵 Jami balans: {total_balance:,.0f} so'm\n\n"
        
        # 2. Valyutalar (kirim/chiqim ko'rsatilmaydi)
        if by_currency:
            safe_message += "💱 <b>Valyutalar bo'yicha:</b>\n"
            currency_symbols = {'UZS': "🇺🇿", 'USD': "🇺🇸", 'EUR': "🇪🇺", 'RUB': "🇷🇺", 'TRY': "🇹🇷"}
            currency_names = {'UZS': "so'm", 'USD': "dollar", 'EUR': "evro", 'RUB': "rubl", 'TRY': "lira"}
                
            for curr, data in sorted(by_currency.items()):
                symbol = currency_symbols.get(curr, "💰")
                name = currency_names.get(curr, curr)
                balance = data.get('balance', 0)
                
                safe_message += f"{symbol} <b>{curr}</b> ({name}): {balance:,.2f} {name}\n"
            safe_message += "\n"
            
            # 3. Qarzlar
            total_lent = total_uzs.get('lent', 0)
            total_borrowed = total_uzs.get('borrowed', 0)
            safe_message += "💳 <b>Qarzlar:</b>\n"
            safe_message += f"💸 Berilgan qarz: {total_lent:,.0f} so'm\n"
            safe_message += f"💰 Olingan qarz: {total_borrowed:,.0f} so'm\n\n"
        
        # 4. Oxirgi tranzaksiyalar (qisqa format)
        if recent_transactions:
            safe_message += "📋 <b>Oxirgi tranzaksiyalar:</b>\n"
            for i, trans in enumerate(recent_transactions, 1):
                trans_type = trans.get('transaction_type', '')
                amount = float(trans.get('amount', 0) or 0)
                currency = trans.get('currency', 'UZS') or 'UZS'
                category = trans.get('category', 'Noma\'lum') or 'Noma\'lum'
                description = trans.get('description', '') or ''
                debt_direction = trans.get('debt_direction', '')
                
                # Valyuta nomi
                currency_names = {'UZS': "so'm", 'USD': "dollar", 'EUR': "evro", 'RUB': "rubl", 'TRY': "lira"}
                currency_name = currency_names.get(currency, currency)
                
                # Ma'lumotlarni escape qilish
                safe_category = category.replace('<', '&lt;').replace('>', '&gt;')
                
                # Kirim yoki chiqim
                if trans_type == 'income':
                    type_emoji = "📈"
                    type_text = "Kirim"
                elif trans_type == 'expense':
                    type_emoji = "📉"
                    type_text = "Chiqim"
                elif trans_type == 'debt':
                    # Qarz: lent = chiqim, borrowed = kirim
                    if debt_direction == 'lent':
                        type_emoji = "💸"
                        type_text = "Qarz (Chiqim)"
                    elif debt_direction == 'borrowed':
                        type_emoji = "💰"
                        type_text = "Qarz (Kirim)"
                    else:
                        type_emoji = "💳"
                        type_text = "Qarz"
                else:
                    type_emoji = "💳"
                    type_text = "Tranzaksiya"
                
                safe_message += f"{i}. {type_emoji} {type_text}\n"
                safe_message += f"   💵 {amount:,.2f} {currency_name}\n"
                
                # Qarz bo'lsa - kimdan/kimga
                if trans_type == 'debt' and description:
                    # Description dan shaxs nomini ajratish
                    desc_parts = description.split()
                    if desc_parts:
                        possible_name = desc_parts[0]
                        if len(possible_name) < 30 and not any(char.isdigit() for char in possible_name):
                            safe_name = possible_name.replace('<', '&lt;').replace('>', '&gt;')
                            if debt_direction == 'lent':
                                safe_message += f"   👤 Kimga: {safe_name}\n"
                            elif debt_direction == 'borrowed':
                                safe_message += f"   👤 Kimdan: {safe_name}\n"
                else:
                    # Kirim/chiqim - faqat nomi (kategoriya)
                    safe_message += f"   📂 {safe_category}\n"
                
                safe_message += "\n"
        else:
            safe_message += "📋 <b>Oxirgi tranzaksiyalar:</b>\n"
            safe_message += "❌ Hozircha tranzaksiyalar yo'q.\n\n"
    
        # Mini app uchun tugma
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
        # Barcha tariflar uchun "To'liq ko'rish" tugmasi
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text="📱 To'liq ko'rish", 
                web_app=WebAppInfo(url="https://balansai-app.onrender.com/business")
            )
        ])
    
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="💱 Valyuta kurslari", callback_data="currency_rates")
        ])
    
        await message.answer(
                        safe_message,
            reply_markup=keyboard,
                        parse_mode="HTML"
                    )

    except Exception as e:
        logging.error(f"Hisobotlar ko'rsatishda xatolik: {e}")
        import traceback
        logging.error(traceback.format_exc())
        await message.answer(
            "❌ Xatolik yuz berdi. Qaytadan urinib ko'ring.",
            parse_mode="HTML"
    )

# Valyuta kurslari callback
@dp.callback_query(lambda c: c.data == "currency_rates")
async def currency_rates_callback(callback_query: CallbackQuery):
    """Valyuta kurslarini ko'rsatish"""
    try:
        rates = await db.get_currency_rates()
        
        message_text = "💱 **Valyuta kurslari**\n\n"
        message_text += "1 valyuta = ... so'm\n\n"
        
        currency_info = {
            'USD': ('🇺🇸 Dollar (USD)', rates.get('USD', 12750)),
            'EUR': ('🇪🇺 Evro (EUR)', rates.get('EUR', 13800)),
            'RUB': ('🇷🇺 Rubl (RUB)', rates.get('RUB', 135)),
            'TRY': ('🇹🇷 Lira (TRY)', rates.get('TRY', 370))
        }
        
        for code, (name, rate) in currency_info.items():
            message_text += f"{name}: {rate:,.2f} so'm\n"
        
        message_text += "\n💡 _Kurslar taxminiy. Tranzaksiya kiritishda valyutani ayting (masalan: \"50 dollar xarajat\")_"
        
        await callback_query.message.edit_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_reports")]
            ]),
            parse_mode="Markdown"
        )
        await callback_query.answer()
    except Exception as e:
        logging.error(f"Currency rates error: {e}")
        await callback_query.answer("Xatolik yuz berdi", show_alert=True)

@dp.callback_query(lambda c: c.data == "back_to_reports")
async def back_to_reports_callback(callback_query: CallbackQuery):
    """Hisobotlarga qaytish"""
    try:
        user_id = callback_query.from_user.id
        
        # Ko'p valyutali balans ma'lumotlarini olish
        multi_balance = await db.get_balance_multi_currency(user_id)
        total_uzs = multi_balance.get('total_uzs', {})
        by_currency = multi_balance.get('by_currency', {})
        
        # Umumiy balans (so'mda)
        message_text = "📊 **Umumiy balans (so'mda)**\n\n"
        message_text += f"💵 **Naqd balans:** {total_uzs.get('balance', 0):,.0f} so'm\n"
        message_text += f"📊 **Sof balans:** {total_uzs.get('net_balance', 0):,.0f} so'm\n"
        message_text += f"📈 **Jami kirim:** {total_uzs.get('income', 0):,.0f} so'm\n"
        message_text += f"📉 **Jami chiqim:** {total_uzs.get('expense', 0):,.0f} so'm\n"
        
        # Qarzlar bo'lsa ko'rsatish
        if total_uzs.get('lent', 0) > 0:
            message_text += f"💸 **Berilgan qarz:** {total_uzs.get('lent', 0):,.0f} so'm\n"
        if total_uzs.get('borrowed', 0) > 0:
            message_text += f"💳 **Olingan qarz:** {total_uzs.get('borrowed', 0):,.0f} so'm\n"
        
        # Har bir valyutadagi balans
        if by_currency:
            message_text += "\n💱 **Valyutalar bo'yicha:**\n"
            currency_symbols = {'UZS': "🇺🇿", 'USD': "🇺🇸", 'EUR': "🇪🇺", 'RUB': "🇷🇺", 'TRY': "🇹🇷"}
            currency_names = {'UZS': "so'm", 'USD': "dollar", 'EUR': "evro", 'RUB': "rubl", 'TRY': "lira"}
            for curr, data in by_currency.items():
                symbol = currency_symbols.get(curr, "💰")
                name = currency_names.get(curr, curr)
                balance = data.get('balance', 0)
                message_text += f"{symbol} {balance:,.2f} {name}\n"
        
        # User tarifini tekshirish
        user_tariff = await get_user_tariff(user_id)
        
        # Mini app uchun tugma (Plus va Pro tariflar uchun)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        
        if user_tariff in ('PLUS', 'PRO', 'BIZNES', 'BUSINESS'):
            # Business tarif uchun /business sahifasi
            if user_tariff in ('BUSINESS', 'PLUS'):
                app_url = "https://balansai-app.onrender.com/business"
            else:
                app_url = "https://balansai-app.onrender.com"
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text="📱 To'liq ko'rish", 
                    web_app=WebAppInfo(url=app_url)
                )
            ])
        
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="💱 Valyuta kurslari", callback_data="currency_rates")
        ])
        
        await callback_query.message.edit_text(
            message_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await callback_query.answer()
    except Exception as e:
        logging.error(f"Back to reports error: {e}")
        await callback_query.answer("Xatolik yuz berdi", show_alert=True)

# Profil menyusi
@dp.message(lambda message: message.text == "👤 Profil")
async def profile_handler(message: Message, state: FSMContext):
    """Profil menyusini ko'rsatish"""
    user_id = message.from_user.id
    
    # Foydalanuvchi ma'lumotlarini olish
    user_data = await db.get_user_data(user_id)
    if not user_data:
        await message.answer("❌ Foydalanuvchi ma'lumotlari topilmadi!")
        return
    
    # Foydalanuvchi tarifini olish
    user_tariff = await get_user_tariff(user_id)
    all_subscriptions = await get_user_all_subscriptions(user_id)
    
    # Xodim bo'lsa, maxsus profil ko'rsatish
    if user_tariff == 'EMPLOYEE':
        # Boshliq ma'lumotlarini olish
        manager_data = await db.get_user_data(user_data.get('manager_id', 0))
        manager_name = manager_data.get('first_name', 'Noma\'lum') if manager_data else 'Noma\'lum'
        
        profile_text = f"👤 **Xodim Profili**\n\n"
        profile_text += f"🆔 ID: `{user_id}`\n"
        profile_text += f"📅 Ro'yxat: {user_data['created_at'].strftime('%d.%m.%Y')}\n"
        profile_text += f"👤 Ism: {user_data.get('first_name', 'Nomalum')}\n"
        if user_data.get('phone'):
            profile_text += f"📱 Tel: {user_data['phone']}\n\n"
        
        profile_text += f"🎯 **Rol:** Xodim\n"
        profile_text += f"👨‍💼 **Boshliq:** {manager_name}\n"
        profile_text += f"⚠️ **Cheklov:** Tarif sotib olish imkoniyati yo'q\n"
        
        await message.answer(profile_text, reply_markup=get_employee_profile_menu(), parse_mode='Markdown')
        return
    
    # Oddiy foydalanuvchi profili (yangi UI)
    display_name = user_data.get('first_name', 'Xojayin')
    
    if user_tariff == 'PLUS':
        # Plus tarif uchun obuna ma'lumotlari
        expires_str = None
        try:
            # Avval user_subscriptions dan tekshirish
            sub_row = await db.execute_one(
                """SELECT expires_at FROM user_subscriptions 
                   WHERE user_id = %s AND tariff = 'PLUS' AND status = 'active'
                   ORDER BY expires_at DESC LIMIT 1""",
                (user_id,)
            )
            if sub_row and sub_row.get('expires_at'):
                expires_str = sub_row['expires_at'].strftime('%d.%m.%Y')
            elif user_data.get('tariff_expires_at'):
                # users jadvalidagi tariff_expires_at ni tekshirish
                expires_str = user_data['tariff_expires_at'].strftime('%d.%m.%Y')
        except:
            if user_data.get('tariff_expires_at'):
                try:
                    expires_str = user_data['tariff_expires_at'].strftime('%d.%m.%Y')
                except:
                    pass
        
        if expires_str:
            profile_text = (
                f"{display_name} (ID: {user_id})\n\n"
                f"Tarif: ⭐ Plus\n"
                f"Tugash sanasi: {expires_str}"
            )
        else:
            profile_text = (
                f"{display_name} (ID: {user_id})\n\n"
                f"Tarif: ⭐ Plus"
            )
    elif user_tariff in ('NONE', None, 'FREE'):
        # Free tarif uchun oylik tranzaksiya limitini tekshirish
        try:
            monthly_row = await db.execute_one(
                """SELECT COUNT(*) as count FROM transactions 
                   WHERE user_id = %s 
                   AND MONTH(created_at) = MONTH(NOW())
                   AND YEAR(created_at) = YEAR(NOW())""",
                (user_id,)
            )
            monthly_count = monthly_row.get('count', 0) if monthly_row else 0
        except:
            monthly_count = 0
        
        profile_text = (
            f"{display_name} (ID: {user_id})\n\n"
            f"Tarif: 🆓 Free\n"
            f"Oylik tranzaksiyalar: {monthly_count}/100\n\n"
            "💡 Ko'proq imkoniyatlar uchun tarifni kuchaytiring!"
        )
    elif user_tariff == 'PRO':
        # PRO tarif uchun maxsus format
        try:
            row = await db.execute_one(
                """
                SELECT COUNT(*) as count
                FROM transactions 
                WHERE user_id = %s 
                AND MONTH(created_at) = MONTH(NOW())
                AND YEAR(created_at) = YEAR(NOW())
                """,
                (user_id,)
            )
            monthly_count = row.get('count', 0) if row else 0
            
            audio_row = await db.execute_one(
                """
                SELECT COUNT(*) as count
                FROM transactions 
                WHERE user_id = %s 
                AND MONTH(created_at) = MONTH(NOW())
                AND YEAR(created_at) = YEAR(NOW())
                AND description LIKE '%voice%'
                """,
                (user_id,)
            )
            audio_count = audio_row.get('count', 0) if audio_row else 0
            
            expires_str = _format_date_uz(user_data['tariff_expires_at']) + " gacha" if user_data.get('tariff_expires_at') else '—'
            
            profile_text = (
                f"{display_name} (ID: {user_id})\n\n"
                f"Tarif: Pro ({expires_str})\n"
                f"Tranzaksiyalar: {monthly_count}/1000\n"
                f"Ovozli Tranzaksiyalar: {audio_count}/500"
            )
        except Exception as e:
            logging.error(f"Error getting PRO stats: {e}")
            try:
                expires_str = _format_date_uz(user_data.get('tariff_expires_at')) + " gacha" if user_data and user_data.get('tariff_expires_at') else '—'
            except:
                expires_str = '—'
            profile_text = (
                f"{display_name} (ID: {user_id})\n\n"
                f"Tarif: Pro ({expires_str})"
            )
    else:
        # Boshqa tariflar uchun eski format
        expires_str = '—'
        if user_data.get('tariff_expires_at'):
            expires_str = _format_date_uz(user_data['tariff_expires_at']) + " gacha"
        profile_text = (
            f"{display_name} (ID: {user_id})\n\n"
            f"Joriy tarif:\n"
            f"• {TARIFFS.get(user_tariff, 'Nomalum')}\n"
            f"• Tugash: {expires_str}"
        )
    # Klaviatura: Sozlamalar|Tarif (ID tugmasi olib tashlandi — matndan nusxa olinadi)
    profile_kb = get_profile_menu(user_tariff)
    try:
        await message.answer_photo(
            photo=FSInputFile('Profil.png'),
            caption=profile_text,
            reply_markup=profile_kb
        )
    except Exception:
        await message.answer(profile_text, reply_markup=profile_kb)

# Profil callback handlerlari
@dp.callback_query(lambda c: c.data == "settings")
async def settings_callback(callback_query: CallbackQuery):
    """Sozlamalar menyusini ko'rsatish"""
    text = "🚧 <b>Tez orada</b>"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Yordam", callback_data="help_menu")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_profile")]
    ])
    try:
        await callback_query.message.edit_caption(caption=text, reply_markup=keyboard, parse_mode='HTML')
    except Exception:
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "settings_language")
async def settings_language_callback(callback_query: CallbackQuery):
    """Til tanlash menyusini ko'rsatish"""
    # Til tanlash - bitta tugma orqali, qulay va sodda
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇺🇿 O'zbek", callback_data="lang_uz")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en")],
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="settings")]
    ])
    
    text = "🌐 **Til tanlash**\n\nKerakli tilni tanlang:"
    try:
        await callback_query.message.edit_caption(caption=text, reply_markup=keyboard, parse_mode='Markdown')
    except Exception:
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode='Markdown')
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "help_menu")
async def help_menu_callback(callback_query: CallbackQuery):
    """Yordam sahifasini ko'rsatish"""
    help_text = get_help_text()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_profile")]
    ])
    try:
        await callback_query.message.edit_caption(caption=help_text, reply_markup=keyboard, parse_mode='HTML')
    except Exception:
        await callback_query.message.edit_text(help_text, reply_markup=keyboard, parse_mode='HTML')
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "back_to_profile")
async def back_to_profile_callback(callback_query: CallbackQuery):
    """Profilga qaytish"""
    user_id = callback_query.from_user.id
    user_tariff = await get_user_tariff(user_id)
    
    # Profil ma'lumotlarini qayta yuklash
    user_data = await db.get_user_data(user_id)
    if not user_data:
        await callback_query.answer("❌ Xatolik yuz berdi!", show_alert=True)
        return
    
    display_name = user_data.get('first_name', 'Xojayin')
    profile_text = f"👤 <b>Profil</b>\n\n"
    profile_text += f"👋 Salom, {display_name}!\n\n"
    profile_text += f"💳 <b>Tarif:</b> {TARIFFS.get(user_data['tariff'], 'Nomalum')}\n"
    
    if user_data['tariff'] in ['PRO', 'MAX'] and user_data.get('tariff_expires_at'):
        profile_text += f"⏰ <b>Faol bo'lish muddati:</b> {user_data['tariff_expires_at'].strftime('%d.%m.%Y %H:%M')}\n"
    
    keyboard = get_profile_menu(user_tariff)
    try:
        await callback_query.message.edit_caption(caption=profile_text, reply_markup=keyboard, parse_mode='HTML')
    except Exception:
        await callback_query.message.edit_text(profile_text, reply_markup=keyboard, parse_mode='HTML')
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "profile_stats")
async def profile_stats_callback(callback_query: CallbackQuery):
    """Foydalanuvchi shaxsiy statistika: jami tranzaksiyalar soni"""
    user_id = callback_query.from_user.id
    user_tariff = await get_user_tariff(user_id)
    
    if user_tariff == 'EMPLOYEE':
        await callback_query.answer("Bu bo'lim pullik tariflar uchun", show_alert=True)
        return
    
    try:
        row = await db.execute_one("SELECT COUNT(*) as count FROM transactions WHERE user_id = %s", (user_id,))
        total = row.get('count', 0) if row else 0
    except Exception as e:
        logging.error(f"profile_stats_callback error: {e}")
        total = 0
    
    if user_tariff in ('NONE', None):
        text = (
            "📊 Statistika\n\n"
        "Hozircha paket sotib olinmagan. Plus paketlardan birini yoki Pro tarifni tanlang, "
            "shunda AI statistikalarini ko'rish va tranzaksiyalarni avtomatik qayd etish imkoniyati ochiladi."
        )
    else:
        text = f"📊 Statistika\n\nJami tranzaksiyalar (so'rovlar): {total:,} ta"
    
    try:
        await callback_query.message.edit_caption(caption=text, reply_markup=get_profile_menu(user_tariff), parse_mode='Markdown')
    except Exception:
        await callback_query.message.edit_text(text, reply_markup=get_profile_menu(user_tariff), parse_mode='Markdown')
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "start_onboarding")
async def start_onboarding_callback(callback_query: CallbackQuery, state: FSMContext):
    """Yangi onboarding boshlash"""
    user_id = callback_query.from_user.id
    
    # Avvalgi xabarni o'chirish
    try:
        await callback_query.message.delete()
    except:
        pass
    
    # Onboarding davomida aktiv tarifni state ga qo'yib qo'yamiz (yakunda menyu uchun)
    try:
        await ensure_tariff_valid(user_id)
    except Exception:
        pass
    try:
        current_tariff = await get_user_tariff(user_id)
        await state.update_data(onboarding_tariff=current_tariff)
    except Exception:
        pass

    # Onboardingda qo'shimcha kirish xabarisiz darhol savollarni boshlaymiz
    
    # 1-qadam: Balans so'rash (rasm + caption)
    _bal_msg = await callback_query.message.answer_photo(
        photo=FSInputFile('welcome.png'),
        caption=(
            "💰 **1-qadam: Hozirgi balansingiz qancha?**\n\n"
            "Naqd pul va kartadagi pulni birga yozing.\n"
            "Masalan: 500000 (agar 500,000 so'm bo'lsa)\n"
            "Agar pulingiz yo'q bo'lsa: 0 yozing"
        ),
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='Markdown'
    )
    try:
        await state.update_data(onboarding_balance_msg_id=_bal_msg.message_id)
    except Exception:
        pass
    await state.set_state(UserStates.onboarding_balance)
    await callback_query.answer()

# Yangi onboarding handlerlari
@dp.message(UserStates.onboarding_balance)
async def process_onboarding_balance(message: types.Message, state: FSMContext):
    """Onboarding balans qabul qilish"""
    user_id = message.from_user.id
    text = message.text
    
    # AI bilan balansni tahlil qilish
    try:
        from ai_chat import AIChat
        ai = AIChat(db=db)
        ai_result = await ai._analyze_balance_response(text)
        balance = ai_result.get('balance', 0)
        ai_message = ai_result.get('message', '')
    except Exception as e:
        logging.error(f"AI balans tahlili xatolik: {e}")
        # Fallback - oddiy parse
        try:
            balance = float(text.replace(',', '').replace(' ', ''))
            ai_message = ""
        except ValueError:
            await message.answer("❌ Noto'g'ri format. Iltimos, faqat raqam kiriting (masalan: 500000):")
            return
    
    if balance < 0:
        balance = 0
    
    # AI xabari yuborish
    if ai_message:
        await message.answer(ai_message, parse_mode='Markdown')
    
    # Balansni saqlash (so'mda kiritilgan)
    if balance > 0:
        await db.add_transaction(user_id, 'income', int(balance), 'boshlang_ich_balans', 'Onboarding: boshlang\'ich balans')
    else:
        # 0 bo'lsa ham marker qo'shamiz
        await db.add_transaction(user_id, 'income', 0, 'boshlang_ich_balans', 'Onboarding: boshlang\'ich balans (0)')
    
    # Eski xabarlarni o'chirish
    try:
        await message.delete()
        # Avvalgi xabarni o'chirish
        if 'onboarding_balance_msg_id' in (await state.get_data()):
            balance_msg_id = (await state.get_data())['onboarding_balance_msg_id']
            await message.bot.delete_message(chat_id=user_id, message_id=balance_msg_id)
    except:
        pass
    
    # 2-qadam: Qarzlar so'rash (rasm + caption)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Qarz berganman", callback_data="onboarding_debt_lent")],
        [InlineKeyboardButton(text="➖ Qarz olganman", callback_data="onboarding_debt_borrowed")],
        [InlineKeyboardButton(text="❌ Qarzlar yo'q", callback_data="onboarding_no_debts")]
    ])
    _msg = await message.answer_photo(
        photo=FSInputFile('welcome.png'),
        caption=(
            "💳 **2-qadam: Qarzlar holati**\n\n"
            "Kimga qarz berganmisiz yoki kimdan qarzdormisiz?"
        ),
        reply_markup=keyboard,
        parse_mode='Markdown'
    )
    # Oldingi onboarding xabarlarini tozalash uchun id ni saqlaymiz
    await state.update_data(onboarding_balance_msg_id=_msg.message_id)
    await state.set_state(UserStates.onboarding_waiting_for_debt_action)

async def send_onboarding_completion_message(user_id: int) -> None:
    """Onboarding yakunlanganda yakuniy xabarni yuborish"""
    try:
        await ensure_tariff_valid(user_id)
    except Exception as _e:
        logging.debug(f"ensure_tariff_valid skip in onboarding completion: {_e}")

    # Foydalanuvchi tarifini tekshirish
    user_tariff = await get_user_tariff(user_id)
    
    # Agar foydalanuvchi pullik tarifda bo'lsa (PLUS, PRO, BUSINESS), 
    # tarif tanlash xabarini ko'rsatmaslik
    if user_tariff in ('PLUS', 'PRO', 'BUSINESS'):
        # Faqat muvaffaqiyatli xabar va asosiy menyuni ko'rsatish
        if user_tariff == 'BUSINESS':
            menu = get_business_menu()
        else:
            menu = get_premium_menu()
        
        await bot.send_message(
            chat_id=user_id,
            text="✅ **Onboarding yakunlandi!**\n\n"
                 f"Siz {user_tariff} tarifidan foydalanmoqdasiz.\n"
                 "Endi botdan to'liq foydalanishingiz mumkin!",
            reply_markup=menu,
            parse_mode="Markdown"
        )
        return

    # FREE tarif uchun - tarif tanlash
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Plus tarifni sotib olish", web_app=WebAppInfo(url=PAYMENT_PLUS_WEBAPP_URL))],
        [InlineKeyboardButton(text="🔥 Pro tarifga o'tish", web_app=WebAppInfo(url=PAYMENT_PRO_WEBAPP_URL))]
    ])

    caption = (
        "✅ **Sizning buxgalteringiz ishga tayyor!**\n\n"
        "Davom etish uchun tarif tanlang:\n"
        "• Plus tarif – oylik obuna bilan barcha imkoniyatlar\n"
        "• Pro tarif – oylik premium imkoniyatlar\n\n"
        "👇 Quyidagilardan birini tanlang:"
    )

    try:
        await bot.send_photo(
            chat_id=user_id,
            photo=FSInputFile('tarifflar.png'),
            caption=caption,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    except Exception as photo_error:
        logging.warning(f"Onboarding completion photo yuborishda xatolik: {photo_error}")
        try:
            await bot.send_message(
                chat_id=user_id,
                text=caption,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        except Exception as text_error:
            logging.error(f"Onboarding completion xabar yuborilmadi: {text_error}")


async def _handle_onboarding_debt_entry(
    message: types.Message,
    state: FSMContext,
    debt_type: str,
    text: str
) -> None:
    """Onboarding davomida qarz ma'lumotini qabul qilish va saqlash"""
    user_id = message.from_user.id
    text = text.strip()

    if not text:
        await message.answer("Iltimos, qarz ma'lumotlarini kiriting.")
        await state.set_state(UserStates.onboarding_debt_waiting_for_person)
        return

    # AI yordamida parse qilish
    try:
        ai = AIChat(db=db)
        debt_info = await ai._parse_debt_info(text)
        person_name = debt_info.get('person', "Noma'lum")
        amount = debt_info.get('amount', 0) or 0
        due_date = debt_info.get('due_date')
    except Exception as e:
        logging.error(f"AI qarz parse xatolik: {e}")
        person_name = text.split()[0] if text.split() else "Noma'lum"
        try:
            import re
            numbers = re.findall(r'\d+', text)
            amount = float(''.join(numbers)) if numbers else 0
        except Exception:
            amount = 0
        due_date = None

    if amount <= 0:
        await message.answer(
            "❌ Qarzni aniqlay olmadim. Iltimos, ism va summani birga yozib yuboring.\n"
            "Masalan: *Akmalga 100000 so'm qarz berdim* yoki *Karimdan 200000 so'm qarz oldim.*",
            parse_mode="Markdown"
        )
        await state.set_state(UserStates.onboarding_debt_waiting_for_person)
        return

    await db.add_transaction(
        user_id,
        'expense' if debt_type == 'lent' else 'income',
        int(amount),
        'qarz_berdim' if debt_type == 'lent' else 'qarz_oldim',
        f"Onboarding: {person_name}ga qarz" + (f" (Qaytish: {due_date})" if due_date else "")
    )

    try:
        await message.delete()
    except Exception:
        pass

    confirmation_text = (
        f"✅ **{person_name}ga {amount:,.0f} so'm qarz qo'shildi!**\n"
        f"{'🔁 Qaytarish sanasi: ' + str(due_date) if due_date else ''}\n\n"
        "Yana qarz qo'shmoqchimisiz yoki davom etamizmi?"
    )

    keyboard_buttons = [
        [InlineKeyboardButton(text="➕ Yana qo'shish", callback_data=f"onboarding_debt_{debt_type}")]
    ]
    if debt_type == 'borrowed':
        keyboard_buttons.append([InlineKeyboardButton(text="✅ Tugatish", callback_data="onboarding_complete_final")])
    else:
        keyboard_buttons.append([InlineKeyboardButton(text="✅ Keyingi bosqich", callback_data="onboarding_move_to_next")])

    confirmation_message = await message.answer(
        confirmation_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons),
        parse_mode="Markdown"
    )

    await state.update_data(onboarding_debt_amount_msg_id=confirmation_message.message_id, is_onboarding_debt=True)
    await state.set_state(UserStates.onboarding_waiting_for_debt_action)


@dp.callback_query(lambda c: c.data == "onboarding_no_debts")
async def onboarding_no_debts(callback_query: CallbackQuery, state: FSMContext):
    """Qarzlar yo'q - onboarding tugatish"""
    user_id = callback_query.from_user.id
    
    # Eski xabarni o'chirish
    try:
        await callback_query.message.delete()
    except:
        pass
    
    await send_onboarding_completion_message(user_id)
    await state.clear()
    await callback_query.answer()

# Qarz bosqichida matnli javoblar uchun fallback
@dp.message(UserStates.onboarding_waiting_for_debt_action)
async def onboarding_debt_action_text(message: types.Message, state: FSMContext):
    """Foydalanuvchi tugma o'rniga matn yuborgan holatlarni ko'rib chiqish"""
    user_id = message.from_user.id
    text = (message.text or "").strip()
    
    if not text:
        await message.answer("Qarzlar bo'yicha ma'lumot kiriting yoki 'yo'q' deb yozing.")
        return
    
    lower_text = text.lower()
    no_debt_phrases = {"yo'q", "yoq", "yok", "yoʻq", "yo’q", "yo`q", "0", "yoq emas", "no", "none"}
    if lower_text in no_debt_phrases or lower_text.startswith("yo'q") or lower_text.startswith("yoq"):
        try:
            await message.delete()
        except Exception:
            pass
        await send_onboarding_completion_message(user_id)
        await state.clear()
        return
    
    borrowed_keywords = ["oldim", "qarz oldim", "olganman", "qarz ol", "olib", "qarzdorman"]
    debt_type = 'borrowed' if any(keyword in lower_text for keyword in borrowed_keywords) else 'lent'
    
    await state.update_data(debt_type=debt_type, is_onboarding_debt=True)
    await state.set_state(UserStates.onboarding_debt_waiting_for_person)
    await _handle_onboarding_debt_entry(message, state, debt_type, text)

# Qarz qo'shishdan keyin keyingi bosqichga o'tish
@dp.callback_query(lambda c: c.data == "onboarding_move_to_next")
async def onboarding_move_to_next(callback_query: CallbackQuery, state: FSMContext):
    """Qarzlar qo'shildi, keyingi bosqich - qarz olganlar"""
    user_id = callback_query.from_user.id
    
    # Eski xabarni o'chirish
    try:
        await callback_query.message.delete()
    except:
        pass
    
    # 3-qadam: Qarz olgan odamlar
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Qarz olganman", callback_data="onboarding_debt_borrowed")],
        [InlineKeyboardButton(text="❌ Qarzlar yo'q", callback_data="onboarding_complete_final")]
    ])
    
    await callback_query.message.answer_photo(
        photo=FSInputFile('welcome.png'),
        caption=(
            "💳 **3-qadam: Qarzlar holati**\n\n"
            "Kimdan qarz olganmisiz?"
        ),
        reply_markup=keyboard,
        parse_mode='Markdown'
    )
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "onboarding_debt_lent")
async def onboarding_debt_lent(callback_query: CallbackQuery, state: FSMContext):
    """Qarz bergan - AI bilan qarzlar qo'shish"""
    user_id = callback_query.from_user.id
    
    # Eski xabarni o'chirish
    try:
        await callback_query.message.delete()
    except:
        pass
    
    await callback_query.message.answer_photo(
        photo=FSInputFile('welcome.png'),
        caption=(
            "💸 **Kimga qarz berganmisiz?**\n\n"
            "Ism, summa va qaytarish sanasini yozing.\n\n"
            "Masalan: *Akmalga 100000 so'm qarz bergan edim, 20-noyabrda qaytarishi kerak.*\n\n"
            "Yoki oddiy: *Akmal 100000*"
        ),
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='Markdown'
    )
    await state.set_state(UserStates.onboarding_debt_waiting_for_person)
    await state.update_data(debt_type='lent')
    await callback_query.answer()

# Qarz OLGAN handler
@dp.callback_query(lambda c: c.data == "onboarding_debt_borrowed")
async def onboarding_debt_borrowed(callback_query: CallbackQuery, state: FSMContext):
    """Qarz olgan - AI bilan qarzlar qo'shish"""
    user_id = callback_query.from_user.id
    
    # Eski xabarni o'chirish
    try:
        await callback_query.message.delete()
    except:
        pass
    
    await callback_query.message.answer_photo(
        photo=FSInputFile('welcome.png'),
        caption=(
            "💸 **Kimdan qarz olganmisiz?**\n\n"
            "Ism, summa va qaytarish sanasini yozing.\n\n"
            "Masalan: *Karimdan 200000 so'm qarz oldim, 15-dekabrda qaytaraman.*\n\n"
            "Yoki oddiy: *Karim 200000*"
        ),
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='Markdown'
    )
    await state.set_state(UserStates.onboarding_debt_waiting_for_person)
    await state.update_data(debt_type='borrowed')
    await callback_query.answer()

@dp.message(UserStates.onboarding_debt_waiting_for_person)
async def process_onboarding_debt_person(message: types.Message, state: FSMContext):
    """Onboarding qarz - AI bilan pars qilish"""
    data = await state.get_data()
    debt_type = data.get('debt_type', 'lent')
    await _handle_onboarding_debt_entry(message, state, debt_type, message.text or "")

# Onboarding yakunlash
@dp.callback_query(lambda c: c.data == "onboarding_complete_final")
async def onboarding_complete_final(callback_query: CallbackQuery, state: FSMContext):
    """Onboarding tugadi - final"""
    user_id = callback_query.from_user.id
    
    # Eski xabarni o'chirish
    try:
        await callback_query.message.delete()
    except:
        pass
    
    await send_onboarding_completion_message(user_id)
    await state.clear()
    await callback_query.answer()

@dp.message(UserStates.onboarding_debt_waiting_for_amount)
async def process_onboarding_debt_amount(message: types.Message, state: FSMContext):
    """Onboarding qarz miqdorini qabul qilish"""
    user_id = message.from_user.id
    
    try:
        amount = float(message.text.replace(',', '').replace(' ', ''))
        if amount < 0:
            await message.answer("❌ Miqdor manfiy bo'lishi mumkin emas. Qaytadan kiriting:")
            return
    except ValueError:
        await message.answer("❌ Noto'g'ri format. Faqat raqam kiriting (masalan: 100000):")
        return
    
    # Qarzni saqlash
    data = await state.get_data()
    person_name = data.get('debt_person', 'Noma\'lum')
    debt_type = data.get('debt_type', 'lent')
    
    await db.add_transaction(
        user_id, 
        'expense' if debt_type == 'lent' else 'income',
        int(amount),  # so'mda kiritilgan
        'qarz_berdim' if debt_type == 'lent' else 'qarz_oldim',
        f"Onboarding: {person_name}ga qarz berdim" if debt_type == 'lent' else f"Onboarding: {person_name}dan qarz oldim"
    )
    
    # Eski xabarlarni o'chirish
    try:
        await message.delete()
        # Avvalgi xabarni o'chirish
        if 'onboarding_debt_amount_msg_id' in (await state.get_data()):
            amount_msg_id = (await state.get_data())['onboarding_debt_amount_msg_id']
            await message.bot.delete_message(chat_id=user_id, message_id=amount_msg_id)
    except:
        pass
    
    # Yana qarz qo'shish yoki tugatish
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Yana qarz qo'shish", callback_data="onboarding_debt_lent")],
        [InlineKeyboardButton(text="✅ Tayyor", callback_data="onboarding_no_debts")]
    ])
    
    _msg = await message.answer(
        f"✅ **{person_name}ga {amount:,.0f} so'm qarz qo'shildi!**\n\n"
        "Yana qarz qo'shmoqchimisiz yoki tayyormisiz?",
        reply_markup=keyboard
    )
    await state.update_data(onboarding_debt_amount_msg_id=_msg.message_id)
    await state.set_state(UserStates.onboarding_waiting_for_debt_action)

@dp.callback_query(lambda c: c.data == "back_to_transaction")
async def back_to_transaction_callback(callback_query: CallbackQuery, state: FSMContext):
    """Tranzaksiyaga qaytish"""
    # Oddiy javob
    await callback_query.answer("Bekor qilindi")
    await state.clear()
    try:
        await callback_query.message.delete()
    except:
        pass
    return

@dp.callback_query(lambda c: c.data == "back_to_profile")
async def back_to_profile_callback(callback_query: CallbackQuery):
    """Profil menyusiga qaytish"""
    user_id = callback_query.from_user.id
    user_data = await db.get_user_data(user_id)
    
    # Foydalanuvchi tarifini olish
    user_tariff = await get_user_tariff(user_id)
    
    # Yangi yagona profil formatiga mos
    display_name = user_data.get('first_name', 'Xojayin')
    
    # FREE tarif uchun
    if user_tariff == 'PLUS':
        # PLUS tarif uchun maxsus format
        try:
            row = await db.execute_one(
                """
                SELECT COUNT(*) as count
                FROM transactions 
                WHERE user_id = %s 
                AND MONTH(created_at) = MONTH(NOW())
                AND YEAR(created_at) = YEAR(NOW())
                """,
                (user_id,)
            )
            monthly_count = row.get('count', 0) if row else 0
            
            audio_row = await db.execute_one(
                """
                SELECT COUNT(*) as count
                FROM transactions 
                WHERE user_id = %s 
                AND MONTH(created_at) = MONTH(NOW())
                AND YEAR(created_at) = YEAR(NOW())
                AND description LIKE '%voice%'
                """,
                (user_id,)
            )
            audio_count = audio_row.get('count', 0) if audio_row else 0
            
            expires_str = _format_date_uz(user_data['tariff_expires_at']) + " gacha" if user_data.get('tariff_expires_at') else '—'
            
            profile_text = (
                f"{display_name} (ID: {user_id})\n\n"
                f"Tarif: Plus ({expires_str})\n"
                f"Tranzaksiyalar: {monthly_count}/500\n"
                f"Ovozli Tranzaksiyalar: {audio_count}/250"
            )
        except Exception as e:
            logging.error(f"Error getting PLUS stats: {e}")
            expires_str = _format_date_uz(user_data['tariff_expires_at']) + " gacha" if user_data.get('tariff_expires_at') else '—'
            profile_text = (
                f"{display_name} (ID: {user_id})\n\n"
                f"Tarif: Plus ({expires_str})"
            )
    elif user_tariff == 'PRO':
        # PRO tarif uchun maxsus format
        try:
            row = await db.execute_one(
                """
                SELECT COUNT(*) as count
                FROM transactions 
                WHERE user_id = %s 
                AND MONTH(created_at) = MONTH(NOW())
                AND YEAR(created_at) = YEAR(NOW())
                """,
                (user_id,)
            )
            monthly_count = row.get('count', 0) if row else 0
            
            audio_row = await db.execute_one(
                """
                SELECT COUNT(*) as count
                FROM transactions 
                WHERE user_id = %s 
                AND MONTH(created_at) = MONTH(NOW())
                AND YEAR(created_at) = YEAR(NOW())
                AND description LIKE '%voice%'
                """,
                (user_id,)
            )
            audio_count = audio_row.get('count', 0) if audio_row else 0
            
            expires_str = _format_date_uz(user_data['tariff_expires_at']) + " gacha" if user_data.get('tariff_expires_at') else '—'
            
            profile_text = (
                f"{display_name} (ID: {user_id})\n\n"
                f"Tarif: Pro ({expires_str})\n"
                f"Tranzaksiyalar: {monthly_count}/1000\n"
                f"Ovozli Tranzaksiyalar: {audio_count}/500"
            )
        except Exception as e:
            logging.error(f"Error getting PRO stats: {e}")
            try:
                expires_str = _format_date_uz(user_data.get('tariff_expires_at')) + " gacha" if user_data and user_data.get('tariff_expires_at') else '—'
            except:
                expires_str = '—'
            profile_text = (
                f"{display_name} (ID: {user_id})\n\n"
                f"Tarif: Pro ({expires_str})"
            )
    else:
        # Boshqa tariflar uchun eski format
        expires_str = '—'
        if user_data.get('tariff_expires_at'):
            expires_str = _format_date_uz(user_data['tariff_expires_at']) + " gacha"
        profile_text = (
            f"{display_name} (ID: {user_id})\n\n"
            f"Joriy tarif:\n"
            f"• {TARIFFS.get(user_tariff, 'Nomalum')}\n"
            f"• Tugash: {expires_str}"
        )
    
    keyboard = get_profile_menu(user_tariff)
    try:
        await callback_query.message.edit_caption(caption=profile_text, reply_markup=keyboard, parse_mode='Markdown')
    except Exception:
        await callback_query.message.edit_text(profile_text, reply_markup=keyboard, parse_mode='Markdown')
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "change_tariff")
async def change_tariff_callback(callback_query: CallbackQuery):
    # Endi bu bo'lim olib tashlangan
    await callback_query.answer("Bu bo'lim olib tashlangan.", show_alert=True)

@dp.callback_query(lambda c: c.data == "tariff_info")
async def tariff_info_callback(callback_query: CallbackQuery):
    """Tarif ma'lumotlarini ko'rsatish"""
    user_id = callback_query.from_user.id
    user_tariff = await get_user_tariff(user_id)
    all_subscriptions = await get_user_all_subscriptions(user_id)
    
    # Yangi format
    current_tariff_line = f"• {TARIFFS.get(user_tariff, user_tariff)}"
    current_expires_line = ""
    if user_data := await db.get_user_data(user_id):
        if user_data.get('tariff_expires_at'):
            current_expires_line = _format_date_uz(user_data['tariff_expires_at']) + " gacha"
    tariff_text = "Joriy tarif:\n" \
                  f"{current_tariff_line}\n" \
                  f"• Tugash: {current_expires_line if current_expires_line else '—'}\n\n"
    other_lines = []
    if all_subscriptions:
        for sub in all_subscriptions:
            tariff_code, is_active, expires_at = sub[0], sub[1], sub[2]
            if tariff_code == user_tariff and is_active:
                continue
            name = TARIFFS.get(tariff_code, tariff_code)
            expires_str = (_format_date_uz(expires_at) + " gacha") if expires_at else '—'
            other_lines.append(f"• {name} (tugash: {expires_str})")
    if other_lines:
        tariff_text += "Sizda mavjud boshqa tarfilar:\n" + "\n".join(other_lines)
    
    if user_tariff == "FREE":
        tariff_text += "\n🆓 **Bepul tarif imkoniyatlari:**\n"
        tariff_text += "• Asosiy moliyaviy funksiyalar\n"
        tariff_text += "• Qarzlar boshqaruvi\n"
        tariff_text += "• Balans ko'rish\n\n"
        tariff_text += "💡 **Pro tarifga o'tish uchun:**\n"
        tariff_text += "• AI yordamida avtomatik qayta ishlash\n"
        tariff_text += "• Kengaytirilgan hisobotlar\n"
        tariff_text += "• Shaxsiy maslahatlar"
    else:
        tariff_text += "\n⭐ **Pullik tarif imkoniyatlari:**\n"
        tariff_text += "• AI yordamida avtomatik qayta ishlash\n"
        tariff_text += "• Kengaytirilgan hisobotlar\n"
        tariff_text += "• Shaxsiy maslahatlar\n"
        tariff_text += "• Cheksiz tranzaksiya qayta ishlash"
    
    # Yangi tarif sotib olish uchun tugma qo'shamiz
    keyboard_buttons = [
        [InlineKeyboardButton(text="🆕 Yangi tarif sotib olish", callback_data="buy_new_tariff")],
        [InlineKeyboardButton(text="🔄 Tarifni o'zgartirish", callback_data="switch_tariff")],
        [InlineKeyboardButton(text="🆘 Yordam", callback_data="help_tariff")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_profile")]
    ]
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    try:
        await callback_query.message.edit_caption(caption=tariff_text, reply_markup=keyboard, parse_mode='Markdown')
    except Exception:
        await callback_query.message.edit_text(tariff_text, reply_markup=keyboard, parse_mode='Markdown')
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "switch_tariff")
async def switch_tariff_callback(callback_query: CallbackQuery):
    """Tarifni o'zgartirish menyusini ko'rsatish"""
    user_id = callback_query.from_user.id
    user_tariff = await get_user_tariff(user_id)
    
    # Xodim bo'lsa, tarif o'zgartirishni taqiqlash
    if user_tariff == 'EMPLOYEE':
        await callback_query.answer("❌ Xodimlar tarif o'zgartira olmaydi!", show_alert=True)
        return
    
    all_subscriptions = await get_user_all_subscriptions(user_id)
    
    if not all_subscriptions:
        await callback_query.answer("❌ Sizda sotib olingan tariflar yo'q!", show_alert=True)
        return
    
    keyboard_buttons = []
    for sub in all_subscriptions:
        tariff_name = TARIFFS.get(sub[0], sub[0])
        status = "🟢" if sub[1] else "⚪"
        keyboard_buttons.append([InlineKeyboardButton(
            text=f"{status} {tariff_name}",
            callback_data=f"activate_tariff_{sub[0]}"
        )])
    
    keyboard_buttons.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="tariff_info")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    try:
        await callback_query.message.edit_caption(
            caption="🔄 **Tarifni o'zgartirish**\n\nQaysi tarifni aktiv qilmoqchisiz?",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    except Exception:
        await callback_query.message.edit_text(
            "🔄 **Tarifni o'zgartirish**\n\nQaysi tarifni aktiv qilmoqchisiz?",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    await callback_query.answer()

@dp.callback_query(lambda c: c.data.startswith("test_activate_"))
async def test_activate_business_callback(callback_query: CallbackQuery):
    """Test rejimida Business tarifini aktiv qilish"""
    user_id = callback_query.from_user.id
    tariff_code = callback_query.data.split("_")[2]
    
    if tariff_code != "BUSINESS":
        await callback_query.answer("❌ Faqat Business tarif test rejimida mavjud", show_alert=True)
        return
    
    try:
        from datetime import datetime, timedelta
        
        # 1 oylik test muddati
        expires_at = datetime.now() + timedelta(days=30)
        
        # Users jadvalini yangilash
        await db.execute_query(
            "UPDATE users SET tariff = %s, tariff_expires_at = %s WHERE user_id = %s",
            (tariff_code, expires_at, user_id)
        )
        
        # User subscriptions jadvaliga qo'shish
        await db.execute_query(
            "INSERT INTO user_subscriptions (user_id, tariff, is_active, expires_at) VALUES (%s, %s, %s, %s)",
            (user_id, tariff_code, True, expires_at)
        )
        
        # Payments jadvaliga qo'shish (test uchun 0 so'm)
        await db.execute_query(
            "INSERT INTO payments (user_id, tariff, provider, total_amount, currency, status, merchant_trans_id, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())",
            (user_id, tariff_code, 'test_mode', 0, 'UZS', 'paid', None)
        )
        
        tariff_name = TARIFFS.get(tariff_code, tariff_code)
        
        await callback_query.message.edit_text(
            f"✅ **{tariff_name} tarif aktivlashtirildi!**\n\n"
            f"🧪 **Test rejimi:** 30 kun bepul\n"
            f"📅 Tugash sanasi: {expires_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"Endi barcha {tariff_name} imkoniyatlaridan foydalanishingiz mumkin!",
            parse_mode='Markdown'
        )
        
        # Business menyusini ko'rsatish
        await callback_query.message.answer(
            "🏢 Business tarif menyusi:",
            reply_markup=get_business_menu()
        )
        
        await callback_query.answer("✅ Tarif aktivlashtirildi!")
        
    except Exception as e:
        logging.error(f"Test tarif aktivlashtirishda xatolik: {e}")
        await callback_query.answer("❌ Xatolik yuz berdi!", show_alert=True)

@dp.callback_query(lambda c: c.data.startswith("activate_tariff_"))
async def activate_tariff_callback(callback_query: CallbackQuery):
    """Tanlangan tarifni aktiv qilish"""
    user_id = callback_query.from_user.id
    tariff = callback_query.data.split("_")[2]
    
    try:
        await db.set_active_tariff(user_id, tariff)
        tariff_name = TARIFFS.get(tariff, tariff)
        
        await callback_query.message.edit_text(
            f"✅ **Tarif o'zgartirildi!**\n\n"
            f"🎯 **Aktiv tarif:** {tariff_name}\n\n"
            f"Endi {tariff_name} imkoniyatlaridan foydalanishingiz mumkin.",
            parse_mode='Markdown'
        )
        
        # Menyuni yangilash
        if tariff == "BUSINESS":
            await callback_query.message.answer("Business tarif menyusi:", reply_markup=get_business_menu())
        elif tariff in ("PLUS", "PRO"):
            await callback_query.message.answer("Pro tarif menyusi:", reply_markup=get_premium_menu())
        else:
            await callback_query.message.answer(
                "Balans AI bilan davom etish uchun paket tanlang:",
                reply_markup=get_plus_purchase_keyboard()
            )
            
    except Exception as e:
        logging.error(f"Tarif o'zgartirishda xatolik: {e}")
        await callback_query.answer("❌ Xatolik yuz berdi!", show_alert=True)
    
    await callback_query.answer()

@dp.callback_query(lambda c: c.data.startswith("back_to_profile"))
async def back_to_profile_callback_handler(callback_query: CallbackQuery):
    """Profilga qaytish - duplicated, redirecting to main handler"""
    # Ignore this duplicate, use the first one
    pass
    
    if all_subscriptions:
        profile_text += f"\n📋 **Sotib olingan tariflar:**\n"
        for sub in all_subscriptions:
            tariff_name = TARIFFS.get(sub[0], sub[0])
            status = "🟢 Aktiv" if sub[1] else "⚪ Mavjud"
            expires = sub[2].strftime('%d.%m.%Y') if sub[2] else "Cheksiz"
            profile_text += f"• {tariff_name} - {status} (tugash: {expires})\n"
    
    user_tariff = await get_user_tariff(user_id)
    await callback_query.message.edit_text(
        profile_text,
        reply_markup=get_profile_menu(user_tariff),
        parse_mode='Markdown'
    )
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "buy_new_tariff")
async def buy_new_tariff_callback(callback_query: CallbackQuery):
    """Yangi tarif sotib olish menyusini ko'rsatish"""
    try:
        await callback_query.message.edit_text(
            get_tariff_overview_text(),
            reply_markup=build_main_tariff_keyboard(),
            parse_mode='Markdown'
        )
    except Exception:
        # Agar photo bo'lsa
        await callback_query.message.delete()
        await callback_query.message.answer_photo(
            photo=FSInputFile('welcome1.png'),
            caption=get_tariff_overview_text(),
            reply_markup=build_main_tariff_keyboard(),
            parse_mode='Markdown'
        )
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "help_tariff")
async def help_tariff_callback(callback_query: CallbackQuery):
    """Yordam xabarini ko'rsatish"""
    help_text = (
        "🆘 **Tarif bo'yicha yordam**\n\n"
        "Tarifni almashtirish yoki yangi tarif sotib olish haqida savollar bormi?\n\n"
        "📞 **Bog'lanish:**\n"
        "• Admin: @AdminUsername\n"
        "• Yordam markazi: +998 XX XXX XX XX\n\n"
        "💬 **Ko'p so'raladigan savollar:**\n"
        "• Tarifni qanday o'zgartirish mumkin?\n"
        "→ Profil > Tarif > Tarifni o'zgartirish\n\n"
        "• 3 kunlik bepul sinov qanday?\n"
        "→ Yangi tarifni tanlang > 3 kun bepul sinov tugmasini bosing\n\n"
        "• To'lov qanday amalga oshiriladi?\n"
        "→ Click, Payme yoki bank orqali\n\n"
        "Savollaringiz bo'lsa, biz bilan bog'laning! 👇"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="tariff_info")]
    ])
    
    try:
        await callback_query.message.edit_caption(
            caption=help_text,
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    except Exception:
        await callback_query.message.edit_text(
            help_text,
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    await callback_query.answer()

# Muddat tanlash handleri
@dp.callback_query(lambda c: c.data.startswith("duration_"), UserStates.waiting_for_subscription_duration)
async def process_subscription_duration(callback_query: CallbackQuery, state: FSMContext):
    """Obuna muddatini qabul qilish"""
    user_id = callback_query.from_user.id
    
    # 3 kunlik bepul sinov (legacy callback uchun)
    if callback_query.data == "duration_trial":
        data = await state.get_data()
        tariff = data.get('selected_tariff')
        
        # Debug: State ma'lumotlarini ko'ramiz
        logging.info(f"Duration trial - State data: {data}")
        logging.info(f"Duration trial - Selected tariff: {tariff}")
        
        if not tariff:
            await callback_query.answer("❌ Tarif topilmadi. Qaytadan boshlang.", show_alert=True)
            return
        
        # Eski "duration_trial" oqimini 3 kunlik umumiy handlerga yo'naltiramiz
        callback_query.data = f"trial_tariff_{tariff}"
        return await process_trial_tariff(callback_query, state)
    
    months = int(callback_query.data.split("_")[1])
    
    # State dan tarifni olamiz
    data = await state.get_data()
    tariff = data.get('selected_tariff')
    
    if not tariff:
        await callback_query.answer("❌ Tarif topilmadi. Qaytadan boshlang.", show_alert=True)
        return
    
    # Narxni hisoblaymiz
    price_info = calculate_subscription_price(tariff, months)
    if "error" in price_info:
        await callback_query.answer("❌ Xatolik yuz berdi.", show_alert=True)
        return
    
    # State ga muddatni saqlaymiz
    await state.update_data(selected_months=months, price_info=price_info)
    
    # To'lov usuli tanlash menyusini ko'rsatamiz
    tariff_name = TARIFFS.get(tariff, tariff)
    discount_text = f" ({price_info['discount_rate']}% chegirma)" if price_info['discount_rate'] > 0 else ""
    
    text = f"💳 **To'lov usulini tanlang**\n\n"
    text += f"📋 **Tarif:** {tariff_name}\n"
    text += f"⏰ **Muddat:** {months} oy{discount_text}\n"
    text += f"💰 **Narx:** {int(price_info['final_price']/100):,} so'm\n"
    
    if price_info['discount_rate'] > 0:
        text += f"💸 **Chegirma:** {int(price_info['discount_amount']/100):,} so'm\n"
    
    try:
        await callback_query.message.delete()
    except Exception:
        pass
    await callback_query.message.answer_photo(
        photo=FSInputFile('welcome1.png'),
        caption=text,
        reply_markup=get_payment_method_keyboard(),
        parse_mode='Markdown'
    )
    await state.set_state(UserStates.waiting_for_payment_method)
    await callback_query.answer()

# To'lov usuli tanlash handleri
@dp.callback_query(lambda c: c.data.startswith("payment_"), UserStates.waiting_for_payment_method)
async def process_payment_method(callback_query: CallbackQuery, state: FSMContext):
    """To'lov usulini qabul qilish"""
    user_id = callback_query.from_user.id
    payment_method = callback_query.data.replace("payment_", "")
    
    # State dan ma'lumotlarni olamiz
    data = await state.get_data()
    tariff = data.get('selected_tariff')
    months = data.get('selected_months')
    price_info = data.get('price_info')
    
    if not all([tariff, months, price_info]):
        await callback_query.answer("❌ Ma'lumotlar topilmadi. Qaytadan boshlang.", show_alert=True)
        return
    
    # To'lov usullarini routing
    if payment_method not in {"telegram_click", "telegram_stars"}:
        await callback_query.answer("🚧 Bu to'lov usuli tez orada qo'shiladi!", show_alert=True)
        return
    
    # Telegram Payments orqali to'lov (Click yoki Stars)
    try:
        # Stars uchun provider token talab qilinmaydi, Click uchun talab qilinadi
        if payment_method == "telegram_click":
            if not TELEGRAM_PAYMENT_PROVIDER_TOKEN:
                await callback_query.message.answer("❌ Payment token topilmadi. Admin tokenni sozlashi kerak.")
                return
        
        # Pending holatini qo'shamiz
        if tariff == 'PLUS':
            _pending_add(PENDING_PLUS_PAYMENTS, user_id)
        else:
            _pending_add(PENDING_BUSINESS_PAYMENTS, user_id)
        
        # Invoice yuboramiz
        tariff_name = TARIFFS.get(tariff, tariff)
        discount_text = f" ({price_info['discount_rate']}% chegirma)" if price_info['discount_rate'] > 0 else ""
        
        # Stars bo'lsa XTR valyutada, aks holda UZS
        if payment_method == "telegram_stars":
            # Stars miqdori tarif narxiga so'mda teng (1 Star ≈ 1 so'm)
            stars_amount = max(1, price_info['final_price'] // 100)
            prices = [types.LabeledPrice(
                label=f"{tariff_name} ({months} oy{discount_text})",
                amount=stars_amount
            )]
            currency = "XTR"
            provider_token = ""
        else:
            prices = [types.LabeledPrice(
                label=f"{tariff_name} ({months} oy{discount_text})",
                amount=price_info['final_price']
            )]
            currency = "UZS"
            provider_token = TELEGRAM_PAYMENT_PROVIDER_TOKEN
        
        amount_text = (
            f"💰 **Narx:** {int(price_info['final_price']/100):,} so'm\n\n"
            if payment_method != "telegram_stars"
            else f"⭐️ **Yulduzlar:** {max(1, int(price_info['final_price'] // 100)):,} Stars\n\n"
        )
        
        # To'lov ma'lumotlarini ko'rsatamiz
        text = (
            "💳 **To'lov usulini tanlang**\n\n"
            f"📋 **Tarif:** {tariff_name}\n"
            f"⏰ **Muddat:** {months} oy\n"
            f"{amount_text}"
            "To'lovni amalga oshirish uchun pastdagi tugmani bosing."
        )
        
        # To'lov usulini tanlash tugmalari
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            # [InlineKeyboardButton(text="💳 Telegram (Click)", callback_data="select_payment_telegram_click")],  # Commentga olindi
            [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="select_payment_telegram_stars")],
            [InlineKeyboardButton(text="◀️ Orqaga", callback_data=f"back_to_duration_{tariff}")]
        ])
        
        try:
            await callback_query.message.edit_text(text, parse_mode='Markdown', reply_markup=keyboard)
        except Exception as e:
            logging.error(f"Message edit error: {e}")
            # Agar xabar o'zgartirishda xatolik bo'lsa, yangi xabar yuboramiz
            await callback_query.message.answer(text, parse_mode='Markdown', reply_markup=keyboard)
        
        await state.clear()
        await callback_query.answer()
        
    except Exception as e:
        logging.error(f"Payment initiation error: {e}")
        await callback_query.answer("❌ To'lovni boshlashda xatolik yuz berdi.", show_alert=True)
        
        # Pending holatini tozalaymiz
        if tariff == 'PLUS':
            _pending_clear(PENDING_PLUS_PAYMENTS, user_id)
        else:
            _pending_clear(PENDING_BUSINESS_PAYMENTS, user_id)

# To'lov usulini tanlash (yangi)
@dp.callback_query(lambda c: c.data and c.data.startswith("select_payment_") and c.data not in ["select_payment_early_access"])
async def select_payment_method(callback_query: CallbackQuery, state: FSMContext):
    """To'lov usulini tanlash"""
    user_id = callback_query.from_user.id
    payment_method = callback_query.data.replace("select_payment_", "")
    
    # Click va Payme uchun "Tez orqada" xabari
    if payment_method in ["click", "payme"]:
        await callback_query.answer("🚧 Bu to'lov usuli tez orada qo'shiladi!\n\nIltimos, boshqa to'lov usulini tanlang.", show_alert=True)
        return
    
    # State dan ma'lumotlarni olamiz
    data = await state.get_data()
    tariff = data.get('selected_tariff')
    months = data.get('selected_months')
    price_info = data.get('price_info')
    
    if not all([tariff, months, price_info]):
        await callback_query.answer("❌ Ma'lumotlar topilmadi. Qaytadan boshlang.", show_alert=True)
        return
    
    try:
        tariff_name = TARIFFS.get(tariff, tariff)
        amount_text = f"💰 **Narx:** {int(price_info['final_price']/100):,} so'm\n\n"
        
        # To'lov usulini tanlash xabarini edit qilamiz
        if payment_method == "telegram_click":
            text = (
                "💳 **Telegram (Click) orqali to'lash:**\n\n"
                f"📋 **Tarif:** {tariff_name}\n"
                f"⏰ **Muddat:** {months} oy\n"
                f"{amount_text}"
                "To'lash uchun tugma yuborildi 👇."
            )
        elif payment_method == "telegram_stars":
            stars_amount = max(1, price_info['final_price'] // 100)
            text = (
                "⭐️ **Telegram Stars orqali to'lash:**\n\n"
                f"📋 **Tarif:** {tariff_name}\n"
                f"⏰ **Muddat:** {months} oy\n"
                f"⭐️ **Yulduzlar:** {stars_amount:,} Stars\n\n"
                "To'lash uchun tugma yuborildi 👇."
            )
        else:
            text = (
                f"💳 **{payment_method.upper()} orqali to'lash:**\n\n"
                f"📋 **Tarif:** {tariff_name}\n"
                f"⏰ **Muddat:** {months} oy\n"
                f"{amount_text}"
                "To'lash uchun tugma yuborildi 👇."
            )
        
        # Qayta tanlash tugmasi
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Boshqa usulni tanlash", callback_data=f"back_to_payment_method_{tariff}_{months}")]
        ])
        
        try:
            # Rasmli xabar bo'lsa caption ni edit qilamiz, aks holda text ni
            if callback_query.message.photo:
                msg = await callback_query.message.edit_caption(caption=text, parse_mode='Markdown', reply_markup=keyboard)
            else:
                msg = await callback_query.message.edit_text(text, parse_mode='Markdown', reply_markup=keyboard)
        except Exception as e:
            logging.error(f"Message edit error: {e}")
            # Agar xabar o'zgartirishda xatolik bo'lsa, yangi xabar yuboramiz
            if callback_query.message.photo:
                sent = await callback_query.message.answer_photo(
                    photo=callback_query.message.photo[-1].file_id,
                    caption=text,
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
            else:
                sent = await callback_query.message.answer(text, parse_mode='Markdown', reply_markup=keyboard)
            try:
                LAST_PAYMENT_INFO_MESSAGE_ID[user_id] = sent.message_id
            except Exception:
                pass
        else:
            # Muvaffaqiyatli edit bo'lsa, o'sha xabar id sini saqlamaymiz; lekin fallback uchun current id ni saqlaymiz
            try:
                LAST_PAYMENT_INFO_MESSAGE_ID[user_id] = callback_query.message.message_id
            except Exception:
                pass
        
        # To'lov usuliga qarab tugma yuboramiz
        if payment_method == "telegram_click":
            if not TELEGRAM_PAYMENT_PROVIDER_TOKEN:
                await callback_query.message.answer("❌ Payment token topilmadi. Admin tokenni sozlashi kerak.")
                return
            
            # Pending holatini qo'shamiz
            if tariff == 'PLUS':
                _pending_add(PENDING_PLUS_PAYMENTS, user_id)
            else:
                _pending_add(PENDING_BUSINESS_PAYMENTS, user_id)
            
            # Telegram Click uchun invoice
            discount_text = f" ({price_info['discount_rate']}% chegirma)" if price_info['discount_rate'] > 0 else ""
            prices = [types.LabeledPrice(
                label=f"{tariff_name} ({months} oy{discount_text})",
                amount=price_info['final_price']
            )]
            
            inv_msg = await bot.send_invoice(
                chat_id=user_id,
                title=f"Balans AI - {tariff_name} tarif ({months} oy)",
                description=f"{tariff_name} tarif: {months} oylik obuna{discount_text}",
                payload=f"{tariff.lower()}:{user_id}:{int(datetime.now().timestamp())}:{months}",
                provider_token=TELEGRAM_PAYMENT_PROVIDER_TOKEN,
                currency="UZS",
                prices=prices,
                need_name=False,
                need_phone_number=False,
                is_flexible=False
            )
            
            # Invoice xabarini saqlaymiz
            LAST_INVOICE_MESSAGE_ID[user_id] = inv_msg.message_id
            
        elif payment_method == "telegram_stars":
            # Pending holatini qo'shamiz
            if tariff == 'PLUS':
                _pending_add(PENDING_PLUS_PAYMENTS, user_id)
            else:
                _pending_add(PENDING_BUSINESS_PAYMENTS, user_id)
            
            # Telegram Stars uchun invoice
            discount_text = f" ({price_info['discount_rate']}% chegirma)" if price_info['discount_rate'] > 0 else ""
            stars_amount = max(1, price_info['final_price'] // 100)
            prices = [types.LabeledPrice(
                label=f"{tariff_name} ({months} oy{discount_text})",
                amount=stars_amount
            )]
            
            inv_msg = await bot.send_invoice(
                chat_id=user_id,
                title=f"Balans AI - {tariff_name} tarif ({months} oy)",
                description=f"{tariff_name} tarif: {months} oylik obuna{discount_text}",
                payload=f"{tariff.lower()}:{user_id}:{int(datetime.now().timestamp())}:{months}",
                provider_token="",
                currency="XTR",
                prices=prices,
                need_name=False,
                need_phone_number=False,
                is_flexible=False
            )
            
            # Invoice xabarini saqlaymiz
            LAST_INVOICE_MESSAGE_ID[user_id] = inv_msg.message_id
            
        else:
            # Boshqa to'lov usullari uchun (hozircha link yuboramiz)
            await callback_query.message.answer(
                f"🔗 **{payment_method.upper()} orqali to'lash**\n\n"
                f"To'lov linki: https://example.com/payment/{tariff.lower()}/{months}\n\n"
                f"Tarif: {tariff_name}\n"
                f"Muddat: {months} oy\n"
                f"Summa: {int(price_info['final_price']/100):,} so'm"
            )
        
        await state.clear()
        await callback_query.answer()
        
    except Exception as e:
        logging.error(f"Payment initiation error: {e}")
        await callback_query.answer("❌ To'lovni boshlashda xatolik yuz berdi.", show_alert=True)
        
        # Pending holatini tozalaymiz
        if tariff == 'PLUS':
            _pending_clear(PENDING_PLUS_PAYMENTS, user_id)
        else:
            _pending_clear(PENDING_BUSINESS_PAYMENTS, user_id)

# Boshqa to'lov usullari uchun handlerlar

@dp.callback_query(lambda c: c.data and c.data.startswith("select_payment_") and c.data not in ["select_payment_telegram_click", "select_payment_telegram_stars", "select_payment_early_access"])
async def select_other_payment_methods(callback_query: CallbackQuery, state: FSMContext):
    """Boshqa to'lov usullari uchun handler"""
    await callback_query.answer("🚧 Bu to'lov usuli tez orada qo'shiladi!\n\nIltimos, boshqa to'lov usulini tanlang.", show_alert=True)

# Qayta to'lov usulini tanlash
@dp.callback_query(lambda c: c.data and c.data.startswith("back_to_payment_method_"))
async def back_to_payment_method(callback_query: CallbackQuery, state: FSMContext):
    """To'lov usulini qayta tanlash"""
    user_id = callback_query.from_user.id
    
    # Callback data: back_to_payment_method_PLUS_1
    # Format: back_to_payment_method_{tariff}_{months}
    try:
        # "back_to_payment_method_" ni olib tashlaymiz
        data_part = callback_query.data.replace("back_to_payment_method_", "")
        # "_" orqali bo'lamiz
        parts = data_part.split("_")
        if len(parts) >= 2:
            tariff = parts[0]
            months = int(parts[1])
        else:
            raise ValueError("Not enough parts")
    except (ValueError, IndexError) as e:
        logging.error(f"Callback data parsing error: {e}, data: {callback_query.data}")
        await callback_query.answer("❌ Xatolik yuz berdi", show_alert=True)
        return
    
    # Avvalgi to'lov tugmasini o'chirish
    try:
        if user_id in LAST_INVOICE_MESSAGE_ID:
            invoice_msg_id = LAST_INVOICE_MESSAGE_ID[user_id]
            await callback_query.bot.delete_message(chat_id=user_id, message_id=invoice_msg_id)
            del LAST_INVOICE_MESSAGE_ID[user_id]
        # To'lov ma'lumotlari (edit qilingan yoki qayta yuborilgan) xabarini ham o'chiramiz
        if user_id in LAST_PAYMENT_INFO_MESSAGE_ID:
            info_msg_id = LAST_PAYMENT_INFO_MESSAGE_ID[user_id]
            try:
                await callback_query.bot.delete_message(chat_id=user_id, message_id=info_msg_id)
            except Exception:
                pass
            LAST_PAYMENT_INFO_MESSAGE_ID.pop(user_id, None)
    except:
        pass
    
    # State ga ma'lumotlarni qayta saqlaymiz
    price_info = calculate_subscription_price(tariff, months)
    await state.update_data(
        selected_tariff=tariff,
        selected_months=months,
        price_info=price_info
    )
    
    # To'lov usullari menusi
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        # [InlineKeyboardButton(text="💳 Telegram (Click)", callback_data="select_payment_telegram_click")],  # Commentga olindi
        [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="select_payment_telegram_stars")],
        [InlineKeyboardButton(text="🔵 Click", callback_data="select_payment_click")],
        [InlineKeyboardButton(text="🟢 Payme", callback_data="select_payment_payme")],
        [InlineKeyboardButton(text="🟡 Uzum Pay", callback_data="select_payment_uzum_pay")],
        [InlineKeyboardButton(text="◀️ Orqaga", callback_data=f"back_to_duration_{tariff}")]
    ])
    
    # Dastlabki holatga qaytaramiz
    tariff_name = TARIFFS.get(tariff, tariff)
    amount_text = f"💰 **Narx:** {int(price_info['final_price']/100):,} so'm\n\n"
    
    text = (
        "💳 **To'lov usulini tanlang**\n\n"
        f"📋 **Tarif:** {tariff_name}\n"
        f"⏰ **Muddat:** {months} oy\n"
        f"{amount_text}"
        "To'lovni amalga oshirish uchun pastdagi tugmani bosing."
    )
    
    try:
        # Rasmli xabar bo'lsa caption ni edit qilamiz, aks holda text ni
        if callback_query.message.photo:
            msg = await callback_query.message.edit_caption(caption=text, parse_mode='Markdown', reply_markup=keyboard)
        else:
            msg = await callback_query.message.edit_text(text, parse_mode='Markdown', reply_markup=keyboard)
    except Exception as e:
        logging.error(f"Message edit error: {e}")
        # Agar xabar o'zgartirishda xatolik bo'lsa, yangi xabar yuboramiz
        if callback_query.message.photo:
            sent = await callback_query.message.answer_photo(
                photo=callback_query.message.photo[-1].file_id,
                caption=text,
                parse_mode='Markdown',
                reply_markup=keyboard
            )
        else:
            sent = await callback_query.message.answer(text, parse_mode='Markdown', reply_markup=keyboard)
        try:
            LAST_PAYMENT_INFO_MESSAGE_ID[user_id] = sent.message_id
        except Exception:
            pass
    else:
        try:
            LAST_PAYMENT_INFO_MESSAGE_ID[user_id] = callback_query.message.message_id
        except Exception:
            pass
    await callback_query.answer()

# Orqaga qaytish handlerlari
@dp.callback_query(lambda c: c.data == "back_to_tariff_selection")
async def back_to_tariff_selection(callback_query: CallbackQuery, state: FSMContext):
    """Tarif tanlashga qaytish"""
    await callback_query.message.edit_text(
        get_tariff_overview_text(),
        reply_markup=build_main_tariff_keyboard()
    )
    await state.clear()
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "back_to_duration_selection")
async def back_to_duration_selection(callback_query: CallbackQuery, state: FSMContext):
    """Muddat tanlashga qaytish"""
    data = await state.get_data()
    tariff = data.get('selected_tariff')
    
    if not tariff:
        await callback_query.answer("❌ Ma'lumotlar topilmadi.", show_alert=True)
        return
    
    tariff_name = TARIFFS.get(tariff, tariff)
    
    try:
        await callback_query.message.edit_caption(
            caption=f"📅 **{tariff_name} tarifini tanladingiz**\n\n"
                    f"Qancha oylik obuna olishni xohlaysiz?\n\n"
                    f"Uzoq muddatli obunalar uchun chegirma mavjud:",
            reply_markup=get_subscription_duration_keyboard(),
            parse_mode='Markdown'
        )
    except Exception:
        await callback_query.message.edit_text(
            f"📅 **{tariff_name} tarifini tanladingiz**\n\n"
            f"Qancha oylik obuna olishni xohlaysiz?\n\n"
            f"Uzoq muddatli obunalar uchun chegirma mavjud:",
            reply_markup=get_subscription_duration_keyboard(),
            parse_mode='Markdown'
        )
    
    await state.set_state(UserStates.waiting_for_subscription_duration)
    await callback_query.answer()

@dp.callback_query(lambda c: not c.data.startswith("trans_") and not c.data.startswith("accept_employee_") and not c.data.startswith("reject_employee") and not c.data.startswith("leave_team") and not c.data.startswith("confirm_leave_team") and not c.data.startswith("biz_") and not c.data.startswith("debt_add_") and not c.data.startswith("debt_edit_") and not c.data.startswith("debt_date_"))
async def process_all_callbacks(callback_query: CallbackQuery, state: FSMContext):
    print(f"DEBUG: Non-transaction callback received: {callback_query.data}")
    # Avtomatik tarif muddatini tekshirish
    await ensure_tariff_valid(callback_query.from_user.id)
    # Bugungi qarz eslatmalarini yuborish (agar bo'lsa)
    try:
        user_id = callback_query.from_user.id
        rows = await db.execute_query(
            "SELECT tr.id, tr.amount, tr.debt_direction, tr.due_date FROM transactions tr JOIN debt_reminders dr ON dr.transaction_id = tr.id AND dr.user_id = tr.user_id WHERE dr.user_id = %s AND dr.reminder_date = CURDATE()",
            (user_id,)
        )
        for (tx_id, amount, direction, due_date) in rows:
            dir_text = "qarz qaytarish" if direction == 'borrowed' else "qarz qaytarilishini kutish"
            await callback_query.message.answer(
                f"🔔 Eslatma: Bugun {dir_text} kuni!\n"
                f"Summa: {float(amount):,.0f} so'm\n"
                f"Sana: {due_date}",
                parse_mode='Markdown'
            )
    except Exception as e:
        logging.error(f"Eslatma yuborishda xatolik: {e}")
    
    # Tarif tanlash callbacklari
    if callback_query.data.startswith("tariff_"):
        code = callback_query.data.split("_", 1)[1]
        user_id = callback_query.from_user.id
        
        if code == "FAMILY_MENU":
            try:
                await callback_query.message.delete()
            except Exception:
                pass
            await callback_query.message.answer_photo(
                photo=FSInputFile('welcome1.png'),
                caption=get_family_overview_text(),
                reply_markup=get_family_tariff_keyboard()
            )
            await callback_query.answer()
            return

        if code == "BUSINESS_MENU":
            try:
                await callback_query.message.delete()
            except Exception:
                pass
            await callback_query.message.answer_photo(
                photo=FSInputFile('welcome1.png'),
                caption=get_business_overview_text(),
                reply_markup=get_business_tariff_keyboard()
            )
            await callback_query.answer()
            return
        if code in ["BUSINESS_PLUS_INFO", "BUSINESS_MAX_INFO"]:
            await callback_query.answer("🚧 Tez orada: hozircha faqat ‘Biznes’ tarifini faollashtirish mumkin.", show_alert=True)
            return
        
        if code == "BACK_MAIN":
            try:
                await callback_query.message.delete()
            except Exception:
                pass
            await callback_query.message.answer_photo(
                photo=FSInputFile('welcome1.png'),
                caption=get_tariff_overview_text(),
                reply_markup=build_main_tariff_keyboard()
            )
            await callback_query.answer()
            return
        
        tariff_code = code
        if tariff_code not in TARIFFS:
            await callback_query.answer("🚧 Tez kunda: bu tarifni tez orada faollashtirasiz!", show_alert=True)
            return

        detail_text = get_tariff_detail_text(tariff_code)
        back_callback = "tariff_BACK_MAIN"
        if tariff_code in {"FAMILY", "FAMILY_PLUS", "FAMILY_MAX"}:
            back_callback = "tariff_FAMILY_MENU"
        elif tariff_code in {"BUSINESS", "BUSINESS_PLUS", "BUSINESS_MAX"}:
            back_callback = "tariff_BUSINESS_MENU"

        # Aktiv foydalanuvchi uchun Aktivlashtirish tugmasini yashirish
        user_tariff = await get_user_tariff(user_id)
        if (user_tariff == tariff_code and user_tariff not in ('NONE', 'FREE')):
            # Expiry ma'lumotini chiqarish
            user_data = await db.get_user_data(user_id)
            expires_text = ""
            if user_data and user_data.get('tariff_expires_at'):
                expires = user_data['tariff_expires_at']
                try:
                    exp_str = expires.strftime('%d.%m.%Y %H:%M')
                except Exception:
                    exp_str = str(expires)
                expires_text = f"\n\n⏰ Muddati: {exp_str}\n🔁 Qayta to‘lash: Tarif muddati tugaganda qayta to‘lashingiz mumkin."
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back_callback)]])
            try:
                await callback_query.message.delete()
            except Exception:
                pass
            await callback_query.message.answer_photo(
                photo=FSInputFile('welcome1.png'),
                caption=detail_text + expires_text,
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        else:
            # FREE tarif uchun alohida keyboard
            if tariff_code == "FREE":
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back_callback),
                     InlineKeyboardButton(text="🚀 Aktivlashtirish", callback_data="activate_FREE")]
                ])
            else:
                keyboard = build_tariff_detail_keyboard(tariff_code, back_callback)
            try:
                await callback_query.message.delete()
            except Exception:
                pass
            await callback_query.message.answer_photo(
                photo=FSInputFile('welcome1.png'),
                caption=detail_text,
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        await callback_query.answer()
        return
    
    # 3 kunlik sinov callbacklari (legacy free_trial_* aliaslari)
    if callback_query.data.startswith("free_trial_"):
        tariff_code = callback_query.data.replace("free_trial_", "")
        # Eski callbacklarni yangi 3 kunlik sinov oqimiga yo'naltiramiz
        callback_query.data = f"trial_tariff_{tariff_code}"
        return await process_trial_tariff(callback_query, state)

    # Aktivlashtirish callbacklari
    if callback_query.data.startswith("activate_"):
        tariff_code = callback_query.data.replace("activate_", "")
        print(f"DEBUG: Activation callback received for tariff: {tariff_code}")
        
        if tariff_code == "FREE":
            print("DEBUG: Processing FREE activation")
            user_id = callback_query.from_user.id
            # FREE tarif har doim aktivlashtirish mumkin (pullik obuna bo'lsa ham)
            try:
                user_name = await get_user_name(user_id)
                await db.execute_query(
                    "UPDATE users SET tariff = %s, tariff_expires_at = NULL WHERE user_id = %s",
                    ("FREE", user_id)
                )
                
                # Xabarni o'chirish yoki yangi xabar yuborish
                try:
                    await callback_query.message.delete()
                except Exception:
                    pass
                
                await callback_query.message.answer(
                    f"✅ **Bepul tarif aktivlashtirildi!**\n\n"
                    f"Salom, {user_name}!\n\n"
                    "Quyidagi tugmalardan foydalaning:",
                    parse_mode="Markdown"
                )
                await callback_query.message.answer(
                    "Bepul tarif menyusi:",
                    reply_markup=get_free_menu()
                )
                await callback_query.answer("✅ Bepul tarif aktivlashtirildi!")
                return
            except Exception as e:
                logging.error(f"FREE activation error: {e}")
                await callback_query.answer("❌ Xatolik yuz berdi.", show_alert=True)
                return

        if tariff_code in ("PLUS", "BUSINESS", "PRO", "FAMILY", "FAMILY_PLUS", "FAMILY_PRO", "BUSINESS_PLUS", "BUSINESS_PRO"):
            # Yangi tarif sotib olish jarayoni - muddat tanlash
            print(f"DEBUG: Processing paid tariff selection: {tariff_code}")
            user_id = callback_query.from_user.id
            
            # State ga tarifni saqlaymiz
            await state.update_data(selected_tariff=tariff_code)
            
            # Muddat tanlash menyusini ko'rsatamiz
            tariff_name = TARIFFS.get(tariff_code, tariff_code)
            try:
                await callback_query.message.delete()
            except Exception:
                pass
            await callback_query.message.answer_photo(
                photo=FSInputFile('welcome1.png'),
                caption=(
                    f"📅 **{tariff_name} tarifini tanladingiz**\n\n"
                    f"Qancha oylik obuna olishni xohlaysiz?\n\n"
                    f"Uzoq muddatli obunalar uchun chegirma mavjud:"
                ),
                reply_markup=get_subscription_duration_keyboard(),
                parse_mode='Markdown'
            )
            await state.set_state(UserStates.waiting_for_subscription_duration)
            await callback_query.answer()
            return

        # Boshqa barcha tariflar uchun
        print(f"DEBUG: Processing other tariff activation: {tariff_code}")
        await callback_query.answer(
            "🚧 Tez orada: hozircha faqat Bepul va Plus tariflari ishlayotgani. Kuzatishda davom eting!",
            show_alert=True
        )
        return

# Tarif tanlash (faqat onboarding paytida) - oxirida qo'yilgan
@dp.callback_query(lambda c: c.data.startswith("tariff_"), UserStates.waiting_for_tariff)
async def process_tariff_onboarding_only(callback_query: CallbackQuery, state: FSMContext):
    """Tarifni qabul qilish (onboarding)"""
    user_id = callback_query.from_user.id
    tariff = callback_query.data.split("_", 1)[1]

    if tariff == "FREE":
        # Free tarif uchun onboarding (eski UI bilan)
        await state.update_data(onboarding_tariff=tariff)
        
        # Onboarding bosqichi 1: Boshlang'ich balans (rasmli xabar)
        await callback_query.message.answer_photo(
            photo=FSInputFile('welcome.png'),
            caption=(
                "💰 **1-qadam: Boshlang'ich balans**\n\n"
                "Qancha pulingiz bor? (naqd pul + karta)\n\n"
                "Masalan: 500000 (agar 500,000 so'm bo'lsa)"
            ),
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='Markdown'
        )
        
        await state.set_state(UserStates.onboarding_balance)
        await callback_query.answer()
        return

    if tariff == "FAMILY_MENU":
        await callback_query.message.edit_text(
            get_family_overview_text(),
            reply_markup=get_family_tariff_keyboard()
        )
        await callback_query.answer()
        return

    if tariff == "BUSINESS_MENU":
        await callback_query.message.edit_text(
            get_business_overview_text(),
            reply_markup=get_business_tariff_keyboard()
        )
        await callback_query.answer()
        return
    
    if tariff == "BACK_MAIN":
        await callback_query.message.edit_text(
            get_tariff_overview_text(),
            reply_markup=build_main_tariff_keyboard()
        )
        await callback_query.answer()
        return

    if tariff == "PLUS":
        # PLUS tarif uchun onboarding (eski UI bilan)
        await state.update_data(onboarding_tariff=tariff, selected_tariff=tariff)
        
        # Onboarding bosqichi 1: Boshlang'ich balans (rasmli xabar)
        await callback_query.message.answer_photo(
            photo=FSInputFile('welcome.png'),
            caption=(
                "💰 **1-qadam: Boshlang'ich balans**\n\n"
                "Qancha pulingiz bor? (naqd pul + karta)\n\n"
                "Masalan: 500000 (agar 500,000 so'm bo'lsa)"
            ),
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='Markdown'
        )
        
        await state.set_state(UserStates.onboarding_balance)
        await callback_query.answer()
        return

    if tariff != "FREE":
        # Boshqa tariflar uchun ma'lumot ko'rsatish; aktiv bo'lsa Aktivlashtirish tugmasini yashirish
        detail_text = get_tariff_detail_text(tariff)
        back_callback = "tariff_BACK_MAIN"
        if tariff in {"FAMILY", "FAMILY_PLUS", "FAMILY_MAX"}:
            back_callback = "tariff_FAMILY_MENU"
        elif tariff in {"BUSINESS", "BUSINESS_PLUS", "BUSINESS_MAX"}:
            back_callback = "tariff_BUSINESS_MENU"

        try:
            user_data = await db.get_user_data(user_id)
            current = user_data.get('tariff') if user_data else 'NONE'
            if current == tariff and current not in ('NONE', 'FREE'):
                expires_text = ""
                if user_data and user_data.get('tariff_expires_at'):
                    exp = user_data['tariff_expires_at']
                    try:
                        exp_str = exp.strftime('%d.%m.%Y %H:%M')
                    except Exception:
                        exp_str = str(exp)
                    expires_text = f"\n\n⏰ Muddati: {exp_str}\n🔁 Qayta to‘lash: Tarif muddati tugaganda qayta sotib olishingiz mumkin."
                keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back_callback)]])
                await callback_query.message.edit_text(detail_text + expires_text, reply_markup=keyboard, parse_mode='Markdown')
                await callback_query.answer()
                return
        except Exception as _e:
            logging.error(f"onboarding detail active-check error: {_e}")

        # State ga selected_tariff ni saqlaymiz
        await state.update_data(selected_tariff=tariff)
        
        keyboard = build_tariff_detail_keyboard(tariff, back_callback)
        await callback_query.message.edit_text(detail_text, reply_markup=keyboard, parse_mode='Markdown')
        await callback_query.answer()
        return

    # Boshqa holatlar yuqorida qayta ishlangan
    await callback_query.answer()

# ================== BIZNES HANDLERLARI (YANGI TZ) ==================

# 📊 Hisobotlar handler
async def business_reports_handler(message: types.Message, state: FSMContext):
    """Hisobotlar menyusi - Business uchun"""
    user_id = message.from_user.id
    user_tariff = await get_user_tariff(user_id)
    
    if user_tariff != "BUSINESS":
        # Boshqa tariflar uchun standart hisobotlar (bu holat endi bo'lmaydi, chunki reports_menu tekshiradi)
        return
    
    # Hisobotlar menyusi keyboard
    reports_menu = business_module.get_reports_menu()
    
    # Mini app tugmasini qo'shish
    reports_menu.inline_keyboard.insert(0, [
        InlineKeyboardButton(
            text="📱 To'liq ko'rish", 
            web_app=WebAppInfo(url="https://balansai-app.onrender.com/business")
        )
    ])
    
g

# Business sahifasiga o'tish callback
@dp.callback_query(lambda c: c.data == "go_to_business")
async def go_to_business_callback(callback: types.CallbackQuery, state: FSMContext):
    """Hisobotlardan Business sahifasiga o'tish"""
    user_id = callback.from_user.id
    user_tariff = await get_user_tariff(user_id)
    
    if user_tariff != "BUSINESS":
        await callback.answer("❌ Bu funksiya faqat Business tarif uchun mavjud.", show_alert=True)
        return
    
    await callback.answer()
    
    # Business profil sahifasini ko'rsatish
    await callback.message.answer(
        "🏢 **Business Panel**\n\n"
        "Biznesingizni boshqarish uchun quyidagi bo'limlardan birini tanlang:",
        reply_markup=business_module.get_profile_menu(),
        parse_mode='Markdown'
    )

# 📦 Ombor handler
@dp.message(lambda message: message.text == "📦 Ombor")
async def warehouse_menu_handler(message: types.Message, state: FSMContext):
    """Ombor menyusi"""
    user_id = message.from_user.id
    user_tariff = await get_user_tariff(user_id)
    
    if user_tariff != "BUSINESS":
        await message.answer("❌ Bu funksiya faqat Business tarif uchun mavjud.")
        return
    
    # Ombor ma'lumotlarini ko'rsatish
    products_text = await business_module.get_warehouse_products(user_id)
    
    await message.answer(
        products_text + "\n\n💡 **Tovar qo'shish:** \"Omborga 50 kg shakar qo'sh\"\n"
        "💡 **Chiqim:** \"10 ta yog' sotildi\"",
        reply_markup=business_module.get_warehouse_menu(),
        parse_mode='Markdown'
    )

# 🤖 AI Chat handler - REJIM BOSHLASH
@dp.message(lambda message: message.text == "🤖 AI Chat")
async def ai_chat_start_handler(message: types.Message, state: FSMContext):
    """AI Chat rejimini boshlash"""
    user_id = message.from_user.id
    user_tariff = await get_user_tariff(user_id)
    
    if user_tariff != "BUSINESS":
        await message.answer("❌ Bu funksiya faqat Business tarif uchun mavjud.")
        return
    
    await state.set_state(BusinessStates.ai_chat_mode)
    
    await message.answer(
        "🤖 **AI Chat rejimi faollashtirildi!**\n\n"
        "Men sizning biznes yordamchingizman. Menga savollaringizni bering:\n\n"
        "💡 **Misollar:**\n"
        "• \"Bu oy foydam qancha?\"\n"
        "• \"Qaysi kun eng yaxshi savdo bo'lgan?\"\n"
        "• \"Xarajatlarimni qayerdan qisqartirsam bo'ladi?\"\n"
        "• \"Qaysi mahsulot eng ko'p sotilmoqda?\"\n\n"
        "🛑 Chatni to'xtatish uchun pastdagi tugmani bosing.",
        reply_markup=get_ai_chat_stop_menu(),
        parse_mode='Markdown'
    )

# 🛑 AI Chat to'xtatish
@dp.message(lambda message: message.text == "🛑 AI Chatni to'xtatish")
async def ai_chat_stop_handler(message: types.Message, state: FSMContext):
    """AI Chat rejimini to'xtatish"""
    await state.clear()
    
    await message.answer(
        "✅ AI Chat rejimi to'xtatildi.\n\n"
        "Endi odatdagidek yozing yoki menyudan foydalaning.",
        reply_markup=get_business_menu()
    )

# AI Chat rejimida xabarlar
@dp.message(BusinessStates.ai_chat_mode)
async def ai_chat_message_handler(message: types.Message, state: FSMContext):
    """AI Chat rejimida xabarlarni qayta ishlash"""
    user_id = message.from_user.id
    text = message.text
    
    if not text:
        return
    
    # Processing xabari
    processing_msg = await message.answer("🤔 O'ylayapman...")
    
    try:
        # AI dan javob olish
        response = await business_module.ai_chat_response(user_id, text)
        
        await processing_msg.edit_text(
            f"🤖 **AI Javob:**\n\n{response}",
            parse_mode='Markdown'
        )
    except Exception as e:
        logging.error(f"AI Chat error: {e}")
        await processing_msg.edit_text("❌ Xatolik yuz berdi. Qaytadan urinib ko'ring.")

# 👤 Profil handler (Business uchun)
@dp.message(lambda message: message.text == "👤 Profil")
async def business_profile_handler(message: types.Message, state: FSMContext):
    """Profil - Business uchun kengaytirilgan"""
    user_id = message.from_user.id
    user_tariff = await get_user_tariff(user_id)
    
    if user_tariff != "BUSINESS":
        # Boshqa tariflar uchun standart profil
        return
    
    await message.answer(
        "👤 **Profil**\n\n"
        "Biznes sozlamalari va ma'lumotlari:",
        reply_markup=business_module.get_profile_menu(),
        parse_mode='Markdown'
    )

# Business callbacks - biz_ prefiksi bilan
@dp.callback_query(lambda c: c.data.startswith("biz_"))
async def business_callback_handler(callback_query: CallbackQuery, state: FSMContext):
    """Barcha biznes callbacklarni qayta ishlash"""
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    try:
        # MAIN
        if data == "biz_main":
            await callback_query.message.delete()
            await callback_query.message.answer(
                "🏢 Business menyusi:",
                reply_markup=get_business_menu()
            )
            await state.clear()
        
        # HISOBOTLAR
        elif data == "biz_report_daily":
            report = await business_module.get_daily_report(user_id)
            await callback_query.message.edit_text(
                report,
                reply_markup=business_module.get_reports_menu(),
                parse_mode='Markdown'
            )
        
        elif data == "biz_report_weekly":
            report = await business_module.get_weekly_report(user_id)
            await callback_query.message.edit_text(
                report,
                reply_markup=business_module.get_reports_menu(),
                parse_mode='Markdown'
            )
        
        elif data == "biz_report_monthly":
            report = await business_module.get_monthly_report(user_id)
            await callback_query.message.edit_text(
                report,
                reply_markup=business_module.get_reports_menu(),
                parse_mode='Markdown'
            )
        
        elif data == "biz_report_debts":
            report = await business_module.get_debts_report(user_id)
            await callback_query.message.edit_text(
                report,
                reply_markup=business_module.get_reports_menu(),
                parse_mode='Markdown'
            )
        
        elif data == "biz_report_ai":
            await callback_query.message.edit_text("🤖 AI tahlil qilinmoqda...", parse_mode='Markdown')
            analysis = await business_module.ai_business_analysis(user_id)
            await callback_query.message.edit_text(
                analysis,
                reply_markup=business_module.get_reports_menu(),
                parse_mode='Markdown'
            )
        
        # OMBOR
        elif data == "biz_warehouse_products":
            products = await business_module.get_warehouse_products(user_id)
            await callback_query.message.edit_text(
                products,
                reply_markup=business_module.get_warehouse_menu(),
                parse_mode='Markdown'
            )
        
        elif data == "biz_warehouse_stats":
            stats = await business_module.get_warehouse_stats(user_id)
            await callback_query.message.edit_text(
                stats,
                reply_markup=business_module.get_warehouse_menu(),
                parse_mode='Markdown'
            )
        
        elif data == "biz_warehouse_low":
            low_stock = await business_module.get_low_stock_products(user_id)
            await callback_query.message.edit_text(
                low_stock,
                reply_markup=business_module.get_warehouse_menu(),
                parse_mode='Markdown'
            )
        
        elif data == "biz_warehouse_ai":
            await callback_query.message.edit_text("🤖 AI tahlil qilinmoqda...", parse_mode='Markdown')
            analysis = await business_module.ai_warehouse_analysis(user_id)
            await callback_query.message.edit_text(
                analysis,
                reply_markup=business_module.get_warehouse_menu(),
                parse_mode='Markdown'
            )
        
        # PROFIL
        elif data == "biz_profile_info":
            user_name = await get_user_name(user_id)
            user_data = await db.execute_query(
                "SELECT tariff, tariff_expires_at FROM users WHERE user_id = %s",
                (user_id,)
            )
            
            tariff_expires = user_data[0].get('tariff_expires_at') if user_data else None
            expires_text = tariff_expires.strftime('%d.%m.%Y') if tariff_expires else "Belgilanmagan"
            
            info_text = (
                f"🏢 **Biznes ma'lumotlari**\n\n"
                f"👤 Ism: {user_name}\n"
                f"📋 Tarif: Business\n"
                f"📅 Amal qilish: {expires_text}\n"
            )
            await callback_query.message.edit_text(
                info_text,
                reply_markup=business_module.get_profile_menu(),
                parse_mode='Markdown'
            )
        
        elif data == "biz_profile_employees":
            employees = await business_module.get_employees_list(user_id)
            await callback_query.message.edit_text(
                employees,
                reply_markup=business_module.get_employees_menu(),
                parse_mode='Markdown'
            )
        
        elif data == "biz_emp_list":
            employees = await business_module.get_employees_list(user_id)
            await callback_query.message.edit_text(
                employees,
                reply_markup=business_module.get_employees_menu(),
                parse_mode='Markdown'
            )
        
        elif data == "biz_emp_add":
            await callback_query.message.edit_text(
                "👥 **Xodim qo'shish**\n\n"
                "Xodimning Telegram ID sini yuboring:\n"
                "(Xodim avval botda /start bosgan bo'lishi kerak)",
                parse_mode='Markdown'
            )
            await state.set_state(BusinessStates.waiting_for_employee_telegram_id)
        
        elif data == "biz_profile_settings":
            await callback_query.message.edit_text(
                "⚙️ **Sozlamalar**\n\n"
                "Tez orada...",
                reply_markup=business_module.get_profile_menu(),
                parse_mode='Markdown'
            )
        
        elif data == "biz_profile_export":
            await callback_query.message.edit_text(
                "📤 **Ma'lumotlarni eksport**\n\n"
                "Tez orada...",
                reply_markup=business_module.get_profile_menu(),
                parse_mode='Markdown'
            )
        
        elif data == "biz_profile_help":
            help_text = (
                "💬 **Yordam**\n\n"
                "Balans AI Biznes - bu AI-powered Mini CRM.\n\n"
                "**Qanday ishlaydi:**\n"
                "Siz shunchaki yozasiz yoki gapirasiz - AI tushunadi va saqlaydi.\n\n"
                "**Misollar:**\n"
                "💰 \"Bugun 1.2 mln savdo bo'ldi\"\n"
                "💸 \"Elektrga 350 ming to'ladim\"\n"
                "📝 \"Aliga 500 ming qarz berdim\"\n"
                "📦 \"Omborga 50 kg shakar qo'sh\"\n"
                "📦 \"10 ta yog' sotildi\"\n\n"
                "🤖 AI Chat - savol-javob rejimi\n"
                "📊 Hisobotlar - statistika va tahlil\n"
                "📦 Ombor - tovarlar boshqaruvi"
            )
            await callback_query.message.edit_text(
                help_text,
                reply_markup=business_module.get_profile_menu(),
                parse_mode='Markdown'
            )
        
        await callback_query.answer()
        
    except Exception as e:
        logging.error(f"Business callback error: {e}")
        await callback_query.answer("❌ Xatolik yuz berdi!", show_alert=True)

# Xodim qo'shish - Telegram ID
@dp.message(BusinessStates.waiting_for_employee_telegram_id)
async def process_employee_telegram_id(message: types.Message, state: FSMContext):
    """Xodim Telegram ID qabul qilish"""
    try:
        telegram_id = int(message.text.strip())
        await state.update_data(employee_telegram_id=telegram_id)
        
        await message.answer(
            "👤 **Xodim ismi:**\n\n"
            "Xodim ismini kiriting:",
            parse_mode='Markdown'
        )
        await state.set_state(BusinessStates.waiting_for_employee_name)
        
    except ValueError:
        await message.answer("❌ Noto'g'ri format. Faqat raqam kiriting (Telegram ID).")

# Xodim qo'shish - Ism
@dp.message(BusinessStates.waiting_for_employee_name)
async def process_employee_name(message: types.Message, state: FSMContext):
    """Xodim ismini qabul qilish"""
    name = message.text.strip()
    await state.update_data(employee_name=name)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Xodim", callback_data="emp_role_employee")],
        [InlineKeyboardButton(text="👔 Menejer", callback_data="emp_role_manager")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="biz_profile_employees")]
    ])
    
    await message.answer(
        "📋 **Rol tanlang:**",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )
    await state.set_state(BusinessStates.waiting_for_employee_role)

# Xodim role callback
@dp.callback_query(lambda c: c.data.startswith("emp_role_"))
async def process_employee_role_callback(callback_query: CallbackQuery, state: FSMContext):
    """Xodim rolini qabul qilish va saqlash"""
    user_id = callback_query.from_user.id
    role = callback_query.data.replace("emp_role_", "")
    
    data = await state.get_data()
    telegram_id = data.get('employee_telegram_id')
    name = data.get('employee_name')
    
    result = await business_module.add_employee(user_id, telegram_id, name, role)
    
    await callback_query.message.edit_text(
        result['message'],
        reply_markup=business_module.get_employees_menu(),
        parse_mode='Markdown'
    )
    
    await state.clear()
    await callback_query.answer()

# ================== /BIZNES HANDLERLARI ==================

@dp.message(lambda message: message.text == "➕ Xodim qo'shish")
async def add_employee_handler(message: types.Message, state: FSMContext):
    """Xodim qo'shish"""
    user_id = message.from_user.id
    user_tariff = await get_user_tariff(user_id)
    
    if user_tariff != "BUSINESS":
        await message.answer("❌ Bu funksiya faqat Business tarif uchun mavjud.")
        return
    
    await message.answer(
        "👥 *Xodim qo'shish*\n\n"
        "Xodimning Telegram ID sini yuboring:\n"
        "(Xodim avval botda /start bosgan bo'lishi kerak)",
        parse_mode="Markdown"
    )
    await state.set_state(UserStates.waiting_for_employee_id)

@dp.message(UserStates.waiting_for_employee_id)
async def process_employee_id(message: types.Message, state: FSMContext):
    """Xodim ID sini qabul qilish"""
    user_id = message.from_user.id
    employee_id = message.text.strip()
    
    print(f"DEBUG: Processing employee ID: {employee_id} from user: {user_id}")
    
    try:
        employee_id = int(employee_id)
    except ValueError:
        await message.answer("❌ Noto'g'ri ID! Faqat raqam kiriting.")
        return
    
    # Xodimning mavjudligini tekshirish
    employee_data = await db.get_user_data(employee_id)
    print(f"DEBUG: Employee data: {employee_data}")
    
    if not employee_data:
        await message.answer("❌ Bu ID da foydalanuvchi topilmadi. Xodim avval botda /start bosishi kerak.")
        return
    
    # Xodimga taklif yuborish
    try:
        print(f"DEBUG: Sending invitation to employee {employee_id}")
        await message.bot.send_message(
            chat_id=employee_id,
            text=f"👥 *Xodim taklifi*\n\n"
                 f"@{message.from_user.username} sizni o'z jamoasiga qo'shmoqchi.\n\n"
                 f"Qabul qilasizmi?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"accept_employee_{user_id}")],
                [InlineKeyboardButton(text="❌ Rad etish", callback_data="reject_employee")]
            ])
        )
        print("DEBUG: Invitation sent successfully")
        
        username = employee_data.get('username', 'Noma\'lum')
        await message.answer(
            f"✅ Taklif yuborildi! Xodim @{username} ga xabar jo'natildi.\n"
            f"U taklifni qabul qilsa, sizning jamoangizga qo'shiladi."
        )
        
    except Exception as e:
        print(f"DEBUG: Error sending invitation: {e}")
        logging.error(f"Xodimga xabar yuborishda xatolik: {e}")
        await message.answer("❌ Xodimga xabar yuborishda xatolik yuz berdi.")
    
    await state.clear()

@dp.callback_query(lambda c: c.data.startswith("accept_employee_"))
async def accept_employee_invite(callback_query: CallbackQuery):
    """Xodim taklifini qabul qilish"""
    print(f"DEBUG: accept_employee callback received: {callback_query.data}")
    await callback_query.answer()
    
    user_id = callback_query.from_user.id
    manager_id = int(callback_query.data.split("_")[2])
    
    print(f"DEBUG: user_id={user_id}, manager_id={manager_id}")
    
    try:
        # Xodimni jamoaga qo'shish (EMPLOYEE tarifiga o'zgartirish)
        await db.execute_query(
            "UPDATE users SET tariff = 'EMPLOYEE', manager_id = %s WHERE user_id = %s",
            (manager_id, user_id)
        )
        print("DEBUG: Database updated successfully")
        
        await callback_query.message.edit_text(
            "✅ *Taklif qabul qilindi!*\n\n"
            "Endi siz jamoaning bir qismisiz. Kirim va chiqimlarni kiritishingiz mumkin.\n"
            "Tarif sotib olish imkoniyati sizga berilmagan.",
            parse_mode="Markdown"
        )
        
        # Xodim menyusini alohida xabar sifatida yuboramiz
        await callback_query.message.answer(
            "Xodim menyusi:",
            reply_markup=get_employee_menu()
        )
        print("DEBUG: Message edited successfully")
        
        # Boshliqga xabar yuborish
        try:
            await callback_query.bot.send_message(
                chat_id=manager_id,
                text=f"✅ @{callback_query.from_user.username} taklifingizni qabul qildi!\n"
                     f"Endi u jamoangizning bir qismi."
            )
            print("DEBUG: Manager notification sent successfully")
        except Exception as e:
            print(f"DEBUG: Manager notification error: {e}")
            logging.error(f"Boshliqga xabar yuborishda xatolik: {e}")
            
    except Exception as e:
        print(f"DEBUG: Main error: {e}")
        logging.error(f"Xodim qo'shishda xatolik: {e}")
        await callback_query.answer("❌ Xatolik yuz berdi!", show_alert=True)

@dp.callback_query(lambda c: c.data == "reject_employee")
async def reject_employee_invite(callback_query: CallbackQuery):
    """Xodim taklifini rad etish"""
    await callback_query.answer()
    
    await callback_query.message.edit_text(
        "❌ *Taklif rad etildi*",
        parse_mode="Markdown"
    )

# Warehouse (Ombor) callback handlerlar
@dp.callback_query(lambda c: c.data.startswith("warehouse_"))
async def warehouse_callback_handler(callback_query: CallbackQuery, state: FSMContext):
    """Ombor callback handlerlari"""
    user_id = callback_query.from_user.id
    user_tariff = await get_user_tariff(user_id)
    
    if user_tariff != "BUSINESS":
        await callback_query.answer("❌ Bu funksiya faqat Business tarif uchun mavjud.", show_alert=True)
        return
    
    action = callback_query.data.replace("warehouse_", "")
    
    if action == "add_product":
        await callback_query.message.edit_text(
            "➕ **Tovar qo'shish**\n\n"
            "Tovar ma'lumotlarini quyidagi formatda yuboring:\n\n"
            "**Format:**\n"
            "Nomi | Kategoriya | Narx | Soni | Min soni | Shtrix kod\n\n"
            "**Misol:**\n"
            "Non | Ovqat | 5000 | 100 | 20 | 1234567890\n\n"
            "Yoki oddiy: \"Non 5000 so'm 100 ta\"",
            parse_mode='Markdown'
        )
        await state.set_state(UserStates.waiting_for_product_info)
        await callback_query.answer()
    
    elif action == "list_products":
        products_text = await warehouse_module.get_products_list(user_id)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="warehouse_back")]
        ])
        await callback_query.message.edit_text(products_text, reply_markup=keyboard, parse_mode='Markdown')
        await callback_query.answer()
    
    elif action == "movement_in":
        products = await db.get_warehouse_products(user_id)
        if not products:
            await callback_query.answer("❌ Avval tovar qo'shing!", show_alert=True)
            return
        
        keyboard_buttons = []
        for product in products[:10]:  # Eng ko'p 10 ta
            keyboard_buttons.append([InlineKeyboardButton(
                text=f"{product['name']} (qoldiq: {product['quantity']})",
                callback_data=f"warehouse_select_product_{product['id']}_in"
            )])
        keyboard_buttons.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="warehouse_back")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        await callback_query.message.edit_text(
            "📥 **Kirim qo'shish**\n\nTovarni tanlang:",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        await callback_query.answer()
    
    elif action == "movement_out":
        products = await db.get_warehouse_products(user_id)
        if not products:
            await callback_query.answer("❌ Avval tovar qo'shing!", show_alert=True)
            return
        
        keyboard_buttons = []
        for product in products[:10]:  # Eng ko'p 10 ta
            keyboard_buttons.append([InlineKeyboardButton(
                text=f"{product['name']} (qoldiq: {product['quantity']})",
                callback_data=f"warehouse_select_product_{product['id']}_out"
            )])
        keyboard_buttons.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="warehouse_back")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        await callback_query.message.edit_text(
            "📤 **Chiqim qo'shish**\n\nTovarni tanlang:",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        await callback_query.answer()
    
    elif action == "statistics":
        stats_text = await warehouse_module.get_warehouse_statistics(user_id)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="warehouse_back")]
        ])
        await callback_query.message.edit_text(stats_text, reply_markup=keyboard, parse_mode='Markdown')
        await callback_query.answer()
    
    elif action == "ai_analysis":
        await callback_query.message.edit_text("🤖 AI tahlil qilmoqda...")
        analysis_text = await warehouse_module.ai_warehouse_analysis(user_id)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="warehouse_back")]
        ])
        await callback_query.message.edit_text(analysis_text, reply_markup=keyboard, parse_mode='Markdown')
        await callback_query.answer()
    
    elif action == "back":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Tovar qo'shish", callback_data="warehouse_add_product")],
            [InlineKeyboardButton(text="📋 Tovarlar ro'yxati", callback_data="warehouse_list_products")],
            [InlineKeyboardButton(text="📥 Kirim", callback_data="warehouse_movement_in"), 
             InlineKeyboardButton(text="📤 Chiqim", callback_data="warehouse_movement_out")],
            [InlineKeyboardButton(text="📊 Statistikalar", callback_data="warehouse_statistics")],
            [InlineKeyboardButton(text="🤖 AI Tahlil", callback_data="warehouse_ai_analysis")]
        ])
        await callback_query.message.edit_text(
            "📦 **Ombor boshqaruvi**\n\n"
            "Quyidagi funksiyalardan foydalaning:",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        await callback_query.answer()

@dp.callback_query(lambda c: c.data.startswith("warehouse_select_product_"))
async def warehouse_select_product_handler(callback_query: CallbackQuery, state: FSMContext):
    """Tovar tanlash va kirim/chiqim qo'shish"""
    user_id = callback_query.from_user.id
    parts = callback_query.data.split("_")
    product_id = int(parts[3])
    movement_type = parts[4]  # 'in' yoki 'out'
    
    product = await db.get_warehouse_product(product_id, user_id)
    if not product:
        await callback_query.answer("❌ Tovar topilmadi!", show_alert=True)
        return
    
    await state.update_data(warehouse_product_id=product_id, warehouse_movement_type=movement_type)
    
    movement_text = "Kirim" if movement_type == "in" else "Chiqim"
    await callback_query.message.edit_text(
        f"📥 **{movement_text} qo'shish**\n\n"
        f"📦 Tovar: {product['name']}\n"
        f"📊 Hozirgi qoldiq: {product['quantity']}\n\n"
        f"Miqdor va narxni yuboring:\n\n"
        f"**Format:**\n"
        f"Miqdor | Narx (so'm)\n\n"
        f"**Misol:**\n"
        f"50 | 5000\n\n"
        f"Yoki oddiy: \"50 ta 5000 so'm\"",
        parse_mode='Markdown'
    )
    await state.set_state(UserStates.waiting_for_warehouse_movement)
    await callback_query.answer()

@dp.message(UserStates.waiting_for_product_info)
async def process_product_info(message: types.Message, state: FSMContext):
    """Tovar ma'lumotlarini qabul qilish"""
    user_id = message.from_user.id
    text = message.text.strip()
    
    # Oddiy format: "Non 5000 so'm 100 ta"
    # Yoki: "Non | Ovqat | 5000 | 100 | 20 | 1234567890"
    
    try:
        # AI orqali tovar ma'lumotlarini ajratish
        # Oddiy parsing
        parts = text.split("|")
        if len(parts) >= 4:
            name = parts[0].strip()
            category = parts[1].strip() if len(parts) > 1 else None
            price = float(parts[2].strip().replace("so'm", "").replace(" ", ""))
            quantity = int(parts[3].strip().replace("ta", "").replace(" ", ""))
            min_quantity = int(parts[4].strip()) if len(parts) > 4 and parts[4].strip() else 0
            barcode = parts[5].strip() if len(parts) > 5 and parts[5].strip() else None
        else:
            # Oddiy format parsing
            import re
            name_match = re.search(r'^([^0-9]+)', text)
            name = name_match.group(1).strip() if name_match else text.split()[0]
            
            price_match = re.search(r'(\d+)\s*so\'?m', text, re.IGNORECASE)
            price = float(price_match.group(1)) if price_match else 0
            
            quantity_match = re.search(r'(\d+)\s*ta', text, re.IGNORECASE)
            quantity = int(quantity_match.group(1)) if quantity_match else 0
            
            category = None
            min_quantity = 0
            barcode = None
        
        result = await warehouse_module.add_product(
            user_id, name, category, barcode, price, quantity, min_quantity
        )
        
        await message.answer(result['message'], parse_mode='Markdown')
        await state.clear()
        
    except Exception as e:
        logging.error(f"Tovar qo'shishda xatolik: {e}")
        await message.answer(f"❌ Xatolik: {str(e)}\n\nIltimos, to'g'ri formatda yuboring.")

@dp.message(UserStates.waiting_for_warehouse_movement)
async def process_warehouse_movement(message: types.Message, state: FSMContext):
    """Kirim/chiqim ma'lumotlarini qabul qilish"""
    user_id = message.from_user.id
    text = message.text.strip()
    data = await state.get_data()
    product_id = data.get('warehouse_product_id')
    movement_type = data.get('warehouse_movement_type')
    
    if not product_id or not movement_type:
        await message.answer("❌ Xatolik yuz berdi. Qayta urinib ko'ring.")
        await state.clear()
        return
    
    try:
        # Format: "50 | 5000" yoki "50 ta 5000 so'm"
        import re
        parts = text.split("|")
        if len(parts) >= 2:
            quantity = int(parts[0].strip().replace("ta", "").replace(" ", ""))
            unit_price = float(parts[1].strip().replace("so'm", "").replace(" ", ""))
        else:
            quantity_match = re.search(r'(\d+)\s*ta', text, re.IGNORECASE)
            quantity = int(quantity_match.group(1)) if quantity_match else 0
            
            price_match = re.search(r'(\d+)\s*so\'?m', text, re.IGNORECASE)
            unit_price = float(price_match.group(1)) if price_match else None
        
        if quantity <= 0:
            await message.answer("❌ Miqdor 0 dan katta bo'lishi kerak!")
            return
        
        result = await warehouse_module.add_movement(
            user_id, product_id, movement_type, quantity, unit_price
        )
        
        await message.answer(result['message'], parse_mode='Markdown')
        
        # Kam qolgan tovarlar haqida bildirishnoma
        alert = await warehouse_module.get_low_stock_alert(user_id)
        if alert:
            await message.answer(alert, parse_mode='Markdown')
        
        await state.clear()
        
    except Exception as e:
        logging.error(f"Kirim/chiqim qo'shishda xatolik: {e}")
        await message.answer(f"❌ Xatolik: {str(e)}\n\nIltimos, to'g'ri formatda yuboring.")

@dp.callback_query(lambda c: c.data == "leave_team")
async def leave_team_callback(callback_query: CallbackQuery):
    """Jamoadan chiqish"""
    await callback_query.answer()
    
    user_id = callback_query.from_user.id
    user_data = await db.get_user_data(user_id)
    
    if not user_data or user_data.get('tariff') != 'EMPLOYEE':
        await callback_query.answer("❌ Siz xodim emassiz!", show_alert=True)
        return
    
    # Tasdiqlash tugmasi
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Ha, chiqaman", callback_data="confirm_leave_team")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_to_profile")]
        ]
    )
    
    await callback_query.message.edit_text(
        "⚠️ **Jamoadan chiqish**\n\n"
        "Siz jamoangizdan chiqmoqchimisiz?\n"
        "Bu amalni bekor qilib bo'lmaydi!",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

@dp.callback_query(lambda c: c.data == "confirm_leave_team")
async def confirm_leave_team_callback(callback_query: CallbackQuery):
    """Jamoadan chiqishni tasdiqlash"""
    await callback_query.answer()
    
    user_id = callback_query.from_user.id
    
    try:
        # Xodimni FREE tarifiga qaytarish
        await db.execute_query(
            "UPDATE users SET tariff = 'NONE', manager_id = NULL WHERE user_id = %s",
            (user_id,)
        )
        
        await callback_query.message.edit_text(
            "✅ **Jamoadan chiqdingiz!**\n\n"
            "Endi siz oddiy foydalanuvchisiz. Yangi jamoaga qo'shilishingiz mumkin.",
            parse_mode="Markdown",
            reply_markup=get_main_menu()
        )
        
    except Exception as e:
        logging.error(f"Jamoadan chiqishda xatolik: {e}")
        await callback_query.answer("❌ Xatolik yuz berdi!", show_alert=True)

# MAX tarif - AI chat (real-time muloqot)
# Ro'yxatdan to'liq o'tilganligini tekshirish funksiyasi
async def check_registration_complete(user_id: int) -> bool:
    """Foydalanuvchi ro'yxatdan to'liq o'tganligini tekshirish"""
    try:
        user_data = await db.get_user_data(user_id)
        if not user_data or not user_data.get('phone'):
            return False
        
        # 1) Agar tarif bo'lsa (PLUS, PRO, BUSINESS) - ro'yxatdan o'tgan
        user_tariff = user_data.get('tariff', '').upper() if user_data.get('tariff') else ''
        if user_tariff in ('PLUS', 'PRO', 'BUSINESS'):
            return True
        
        # 2) Eski foydalanuvchilar uchun: agar tranzaksiyalar bo'lsa, ro'yxatdan o'tgan
        tx_count_query = "SELECT COUNT(*) as count FROM transactions WHERE user_id = %s"
        tx_result = await db.execute_one(tx_count_query, (user_id,))
        has_any_transactions = (tx_result.get('count', 0) > 0) if tx_result else False
        
        if has_any_transactions:
            return True
        
        # 3) Yangi foydalanuvchilar uchun: telefon bor = ro'yxatdan o'tgan
        # Tarif tanlash alohida qadamda bo'ladi
        return True
        
    except Exception as e:
        logging.error(f"Registration check error: {e}")
        return False

@dp.message(lambda message: message.text and not message.text.startswith('/') and message.text not in [
    "📊 Hisobotlar", "👤 Profil", "➕ Kirim", "➖ Chiqim", "💳 Qarzlar", 
    "➕ Xodim qo'shish", "❌ Bekor qilish", "📦 Ombor", "🤖 AI Chat", 
    "🛑 AI Chatni to'xtatish", "👥 Xodimlar", "🏪 Filiallar"
])
async def process_financial_message(message: types.Message, state: FSMContext):
    """MAX va FREE tariflar uchun AI chat"""
    user_id = message.from_user.id
    current_state = await state.get_state()
    
    # waiting_for_phone state'da bo'lsa, uni ignore qilamiz (alohida handler bor)
    if current_state == UserStates.waiting_for_phone.state:
        return
    
    # Telefon raqam bor-yo'qligini tekshirish
    user_data = await db.get_user_data(user_id)
    if not user_data or not user_data.get('phone'):
        # Telefon raqam yo'q - /start ga yo'naltirish
        await message.answer(
            "⚠️ Iltimos, avval /start buyrug'ini yuboring va telefon raqamingizni kiriting.",
            parse_mode="Markdown"
        )
        return
    
    # Onboarding state'larda xabar qabul qilinmasligi kerak
    current_state = await state.get_state()
    onboarding_states = [
        UserStates.waiting_for_phone.state,
        UserStates.waiting_for_name.state,
        UserStates.waiting_for_source.state,
        UserStates.waiting_for_account_type.state,
        UserStates.onboarding_balance.state,
        UserStates.onboarding_complete.state,
        UserStates.onboarding_waiting_for_debt_action.state,
        UserStates.onboarding_debt_waiting_for_person.state,
        UserStates.onboarding_debt_waiting_for_amount.state,
        UserStates.onboarding_debt_waiting_for_due_date.state,
    ]
    
    if current_state in onboarding_states:
        # Onboarding jarayonida oddiy xabarlar bloklanadi
        return
    
    await ensure_tariff_valid(user_id)
    user_tariff = await get_user_tariff(user_id)
    
    # BUSINESS tarif - AI orqali avtomatik aniqlash
    if user_tariff == 'BUSINESS':
        # AI Chat rejimida bo'lsa, bu handler ishlamaydi (BusinessStates.ai_chat_mode)
        if current_state == BusinessStates.ai_chat_mode.state:
            return  # AI Chat handler qayta ishlaydi
        
        # Oddiy xabarlarni AI orqali qayta ishlash
        processing_msg = await message.answer("🔄 AI qayta ishlamoqda...")
        
        try:
            result = await business_module.process_business_message(user_id, message.text)
            
            await processing_msg.delete()
            
            if result.get('success'):
                if result.get('type') == 'question':
                    # Savol - AI Chat javob beradi
                    response = await business_module.ai_chat_response(user_id, result.get('question', message.text))
                    await message.answer(
                        f"🤖 **AI Javob:**\n\n{response}",
                        parse_mode='Markdown',
                        reply_markup=get_business_menu()
                    )
                else:
                    # Amaliyot (kirim/chiqim/qarz/ombor)
                    await message.answer(
                        result.get('message', '✅ Saqlandi!'),
                        parse_mode='Markdown',
                        reply_markup=get_business_menu()
                    )
            else:
                await message.answer(
                    result.get('message', '❌ Xatolik yuz berdi'),
                    parse_mode='Markdown',
                    reply_markup=get_business_menu()
                )
        except Exception as e:
            logging.error(f"Business message error: {e}")
            try:
                await processing_msg.delete()
            except:
                pass
            await message.answer(
                "❌ Xatolik yuz berdi. Qaytadan urinib ko'ring.",
                reply_markup=get_business_menu()
            )
        return
    
    # FREE tarif uchun - faqat text tranzaksiyalar (oyiga 100 ta limit)
    if user_tariff in ('NONE', None, 'FREE'):
        # Oylik limit tekshirish
        try:
            monthly_row = await db.execute_one(
                """SELECT COUNT(*) as count FROM transactions 
                   WHERE user_id = %s 
                   AND MONTH(created_at) = MONTH(NOW())
                   AND YEAR(created_at) = YEAR(NOW())""",
                (user_id,)
            )
            monthly_count = monthly_row.get('count', 0) if monthly_row else 0
        except:
            monthly_count = 0
        
        if monthly_count >= 100:
            # Limit tugagan
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚀 Kuchaytirish", web_app=WebAppInfo(url="https://balansai-app.onrender.com/tariffs"))]
            ])
            await message.answer(
                f"⚠️ **Oylik limit tugadi!**\n\n"
                f"Free tarifda oyiga 100 ta tranzaksiya kiritish mumkin.\n"
                f"Siz {monthly_count}/100 ta ishlatdingiz.\n\n"
                f"Ko'proq imkoniyatlar uchun tarifni kuchaytiring!",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            return
        
        # "Bajarilyapti..." xabari
        processing_msg = await message.answer("🔄 Bajarilyapti...")
        
        try:
            # FREE uchun financial_module orqali qayta ishlaymiz
            text = message.text
            result = await financial_module.process_ai_input_advanced(text, user_id)
            
            # Processing xabarni o'chirish
            try:
                await processing_msg.delete()
            except:
                pass
            
            if result.get('success') and 'transaction_data' in result and result['transaction_data'].get('transactions'):
                # Tranzaksiya aniqlandi
                transaction_type = result.get('type', '')
                buttons = financial_module.generate_transaction_buttons({
                    'type': transaction_type,
                    'transactions': result['transaction_data']['transactions']
                })
                
                # Xabarni tozalash - "Tarif sotib oling" xabarini olib tashlash
                response_message = result.get('message', '✅ Tranzaksiya aniqlandi!')
                if 'Tarif sotib oling' in response_message or 'tarifni sotib oling' in response_message.lower():
                    response_message = '✅ Tranzaksiya aniqlandi!'
                
                # Buttons ni InlineKeyboardMarkup ga o'girish
                if buttons:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text=btn['text'], callback_data=btn['callback_data'])] 
                        for row in buttons for btn in row
                    ])
                    await message.answer(
                                response_message,
                                reply_markup=keyboard,
                                parse_mode='Markdown'
                            )
                else:
                    await message.answer(
                        response_message,
                        parse_mode='Markdown'
                    )
            else:
                # Tranzaksiya aniqlanmadi
                await message.answer(
                    result.get('message', '❓ Xabar tushunilmadi. Iltimos, aniqroq yozing.'),
                    parse_mode='Markdown'
                )
        except Exception as e:
            logging.error(f"FREE tarif xatolik: {e}")
            try:
                await processing_msg.delete()
            except:
                pass
            await message.answer(
                "❌ Xatolik yuz berdi. Qaytadan urinib ko'ring.",
                parse_mode="Markdown"
            )
            return
        
    # PLUS tarif uchun financial_module ishlaydi (oylik obuna - cheksiz)
    if user_tariff == 'PLUS':
        # "Bajarilyapti..." xabari
        processing_msg = await message.answer("🔄 Bajarilyapti...")
        
        # PLUS uchun financial_module orqali qayta ishlaymiz
        text = message.text
        
        # 1. Tranzaksiya va eslatma parallel tekshiriladi (ikkalasi ham bir vaqtda)
        import asyncio
        
        # Parallel ishlash uchun task'lar yaratamiz
        transaction_task = asyncio.create_task(financial_module.process_ai_input_advanced(text, user_id))
        # Qarzlar uchun eslatma avtomatik yaratilmaydi (faqat qaytarish sanasi bo'lsa save_confirmed_transactions da yaratiladi)
        # Shuning uchun reminder_task ni o'chirib tashlaymiz
        reminder_task = None
        
        # Faqat tranzaksiyani kutamiz
        result = await transaction_task
        reminder_result = None
        
        # Exception handling
        if isinstance(result, Exception):
            logging.error(f"Tranzaksiya aniqlashda xatolik: {result}")
            result = {'success': False}
        
        # Debug logging
        logging.info(f"Transaction result: {result}")
        logging.info(f"Reminder result: {reminder_result}")
        
        # Processing xabarni o'chirish
        try:
            await processing_msg.delete()
        except:
            pass
        
        # 3. Natijalarni qayta ishlash
        has_transaction = result.get('success') and 'transaction_data' in result and result['transaction_data'].get('transactions')
        # Eslatma aniqlanganmi tekshirish - 'id' yoki 'message' bor bo'lsa, eslatma aniqlangan
        has_reminder = reminder_result is not None and (reminder_result.get('id') or reminder_result.get('message'))
        
        # Plus tarifda cheksiz - usage tracking olib tashlandi
        usage_note = ""
        
        if has_transaction and has_reminder:
            # Ikkalasi ham bo'lsa - tranzaksiya va eslatma
            transaction_type = result.get('type', '')
            buttons = financial_module.generate_transaction_buttons({
                'transactions': result['transaction_data'].get('transactions', []),
                'type': transaction_type
            })
            
            reminder_msg = reminder_result.get('message', '')
            base_msg = result.get('message', '')
            # "Tarif sotib oling" xabarini tozalash
            if 'Tarif sotib oling' in base_msg or 'tarifni sotib oling' in base_msg.lower():
                base_msg = '✅ Tranzaksiya aniqlandi!'
            response_message = f"{base_msg}\n\n{reminder_msg}" + usage_note
            
            if buttons:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=btn['text'], callback_data=btn['callback_data'])] 
                    for row in buttons for btn in row
                ])
                await message.answer(response_message, parse_mode='Markdown', reply_markup=keyboard)
            else:
                await message.answer(response_message, parse_mode='Markdown')
        elif has_transaction:
            # Faqat tranzaksiya - AVTOMATIK SAQLASH
            transactions = result['transaction_data'].get('transactions', [])
            
            # Avtomatik saqlash
            save_result = await financial_module.save_confirmed_transactions(transactions, user_id)
            
            if save_result.get('success'):
                # Saqlangan - faqat O'chirish/Tahrirlash tugmalari
                base_msg = result.get('message') or ''
                # "Tarif sotib oling" xabarini tozalash
                if 'Tarif sotib oling' in base_msg or 'tarifni sotib oling' in base_msg.lower():
                    base_msg = '✅ Tranzaksiya aniqlandi!'
                response_message = base_msg + "\n\n✅ **Avtomatik saqlandi!**"
                
                # Eslatma ma'lumotlarini qo'shish
                saved_transactions = save_result.get('transactions', [])
                if saved_transactions:
                    for trans in saved_transactions:
                        if trans.get('reminder_created') and trans.get('reminder_date'):
                            from datetime import datetime
                            try:
                                reminder_date = datetime.strptime(trans['reminder_date'], '%Y-%m-%d').date()
                                reminder_date_formatted = reminder_date.strftime('%d-%m-%Y')
                                response_message += f"\n\n📌 **Eslatma qo'shildi!**\nQaytarish sanasida ({reminder_date_formatted}) eslatiladi."
                            except:
                                response_message += f"\n\n📌 **Eslatma qo'shildi!**\nQaytarish sanasida eslatiladi."
                
                response_message += usage_note
                
                # O'chirish va Tahrirlash tugmalarini yaratish
                keyboard = InlineKeyboardMarkup(inline_keyboard=[])
                
                if len(saved_transactions) == 1:
                    # Bitta tranzaksiya
                    trans = saved_transactions[0]
                    trans_type = trans.get('type', '')
                    # Qarz uchun missing_fields ni aniqlash
                    missing_fields = []
                    if trans_type in ('debt_lent', 'debt_borrowed'):
                        if not trans.get('person_name'):
                            missing_fields.append('person_name')
                        if not trans.get('due_date'):
                            missing_fields.append('due_date')
                    
                    # Qarz uchun qo'shimcha tugmalar
                    if trans_type in ('debt_lent', 'debt_borrowed') and missing_fields:
                        additional_buttons = []
                        if 'person_name' in missing_fields:
                            additional_buttons.append(InlineKeyboardButton(text="👤 Ism qo'shish", callback_data="debt_add_name_1"))
                        if 'due_date' in missing_fields:
                            additional_buttons.append(InlineKeyboardButton(text="📅 Qaytarish sanasi", callback_data="debt_add_date_1"))
                        
                        if additional_buttons:
                            keyboard.inline_keyboard.append(additional_buttons)
                    
                    keyboard.inline_keyboard.append([
                        InlineKeyboardButton(text="✏️ Tahrirlash", callback_data="trans_edit_1"),
                        InlineKeyboardButton(text="🗑️ O'chirish", callback_data="trans_delete_1")
                    ])
                else:
                    # Ko'p tranzaksiya
                    for i, trans in enumerate(saved_transactions, 1):
                        keyboard.inline_keyboard.append([
                            InlineKeyboardButton(text=f"✏️ #{i}", callback_data=f"trans_edit_{i}"),
                            InlineKeyboardButton(text=f"🗑️ #{i}", callback_data=f"trans_delete_{i}")
                        ])
                
                # Tugmalarni yuborish (agar bo'sh bo'lsa ham - minimal tugmalar bo'lishi kerak)
                if keyboard.inline_keyboard:
                    await message.answer(response_message, parse_mode='Markdown', reply_markup=keyboard)
                else:
                    # Minimal tugmalar - har doim O'chirish va Tahrirlash bo'lishi kerak
                    minimal_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✏️ Tahrirlash", callback_data="trans_edit_1"),
                         InlineKeyboardButton(text="🗑️ O'chirish", callback_data="trans_delete_1")]
                    ])
                    await message.answer(response_message, parse_mode='Markdown', reply_markup=minimal_keyboard)
                
                # State ga saqlangan tranzaksiya ID larini saqlash (o'chirish uchun)
                await state.update_data(saved_transaction_ids=saved_transactions)
            else:
                # Saqlashda xatolik - eski usul
                response_message = (result.get('message') or '') + usage_note
                await message.answer(response_message, parse_mode='Markdown')
        elif has_reminder:
            # Faqat eslatma
            reminder_msg = reminder_result.get('message', '')
            reminder_id = reminder_result.get('id')
            response_message = reminder_msg + usage_note
            
            # Eslatma uchun tugmalar (avtomatik saqlash, tahrirlash, o'chirish)
            keyboard = InlineKeyboardMarkup(inline_keyboard=[])
            if reminder_id:
                keyboard.inline_keyboard.append([
                    InlineKeyboardButton(text="✏️ Tahrirlash", callback_data=f"reminder_edit_{reminder_id}"),
                    InlineKeyboardButton(text="🗑️ O'chirish", callback_data=f"reminder_delete_{reminder_id}")
                ])
            
            await message.answer(response_message, parse_mode='Markdown', reply_markup=keyboard if keyboard.inline_keyboard else None)
        else:
            # Hech narsa aniqlanmadi - aniq xabar
            await message.answer(
                "❌ **Eslatma ham, tranzaksiya ham aniqlanmadi.**\n\n"
                "Iltimos, quyidagilardan birini aniq ko'rsating:\n"
                "• 💰 **Moliyaviy ma'lumot** (kirim/chiqim/qarz)\n"
                "• 📅 **Eslatma** (uchrashuv, tadbir, vazifa)\n\n"
                "Masalan:\n"
                "• \"100 000 so'mga non oldim\" - tranzaksiya\n"
                "• \"Ertaga 12:00 da meeting bor\" - eslatma" + usage_note,
                parse_mode='Markdown'
            )
        
        return
    
    # Agar tarif bo'lmasa, faqat "Tarif sotib oling" xabari va tugma
    if user_tariff in ('NONE', None):
        await message.answer(
            "❌ Tarif sotib oling\n\nBotdan foydalanish uchun Plus paket yoki Pro tarifni sotib oling.",
            reply_markup=get_plus_purchase_keyboard()
        )
        return
    
    # Faqat PRO va MAX tariflar uchun
    if user_tariff not in ['PRO', 'MAX']:
        return
    
    # State'lar tekshiruvi
    if await state.get_state() in [UserStates.waiting_for_phone, UserStates.waiting_for_name, 
                                   UserStates.waiting_for_source, UserStates.waiting_for_tariff,
                                   UserStates.waiting_for_amount, 
                                   UserStates.waiting_for_category, UserStates.waiting_for_debt_type,
                                   UserStates.waiting_for_debt_person]:
        return
    
    text = message.text
    
    # AI ishlash ko'rsatkich
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    try:
        if user_tariff in ['PRO', 'MAX']:
            # 1. Avval tranzaksiyani aniqlashga harakat qilamiz (financial_module orqali)
            financial_result = await financial_module.process_ai_input_advanced(text, user_id)
            has_transaction = financial_result.get('success') and 'transaction_data' in financial_result
            
            # 2. Eslatmani aniqlashga harakat qilamiz (har doim tekshiramiz, hatto tranzaksiya aniqlangan bo'lsa ham)
            reminder_result = await ai_chat.detect_and_save_reminder(user_id, text)
            has_reminder = reminder_result is not None
            
            # Agar eslatma aniqlangan bo'lsa va tranzaksiya ham aniqlangan bo'lsa, eslatma ustunlik qiladi
            if has_reminder and has_transaction:
                # Eslatma kalit so'zlari bor bo'lsa, tranzaksiyani bekor qilamiz
                reminder_keywords = ['eslatasan', 'eslat', 'kerak', 'borishim', 'ketishim', 'uchrashuv', 'meeting', 'dars']
                text_lower = text.lower()
                if any(keyword in text_lower for keyword in reminder_keywords):
                    # Eslatma ustunlik qiladi - tranzaksiyani bekor qilamiz
                    has_transaction = False
                    financial_result = {'success': False}
            
            # 3. Agar tranzaksiya yoki eslatma aniqlangan bo'lsa, ularni ko'rsatamiz
            if has_transaction:
                # Tranzaksiya aniqlangan
                transaction_type = financial_result.get('type', '')
                transaction_data_to_save = financial_result['transaction_data']
                
                # State ga saqlash va state ni o'rnatish
                await state.set_state(UserStates.waiting_for_transaction_confirmation)
                await state.update_data(transaction_data=transaction_data_to_save)
                
                buttons = financial_module.generate_transaction_buttons({
                    'transactions': transaction_data_to_save.get('transactions', []),
                    'type': transaction_type
                })
                
                response_message = financial_result.get('message', '')
                if has_reminder:
                    reminder_msg = reminder_result.get('message', '')
                    response_message += f"\n\n{reminder_msg}"
                
                if buttons:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text=btn['text'], callback_data=btn['callback_data'])] 
                        for row in buttons for btn in row
                    ])
                    await message.answer(response_message, parse_mode='Markdown', reply_markup=keyboard)
                else:
                    await message.answer(response_message, parse_mode='Markdown')
                return
            elif has_reminder:
                # Faqat eslatma aniqlangan
                reminder_msg = reminder_result.get('message', '')
                reminder_id = reminder_result.get('id')
                
                # Eslatma uchun tugmalar (avtomatik saqlash, tahrirlash, o'chirish)
                keyboard = InlineKeyboardMarkup(inline_keyboard=[])
                if reminder_id:
                    keyboard.inline_keyboard.append([
                        InlineKeyboardButton(text="✏️ Tahrirlash", callback_data=f"reminder_edit_{reminder_id}"),
                        InlineKeyboardButton(text="🗑️ O'chirish", callback_data=f"reminder_delete_{reminder_id}")
                    ])
                
                await message.answer(reminder_msg, parse_mode='Markdown', reply_markup=keyboard if keyboard.inline_keyboard else None)
                return
            
            # 4. Agar hech narsa aniqlanmagan bo'lsa, AI chat javob beradi
            # PRO/MAX tariflar uchun HAR QANDAY mavzu uchun AI chat - 100% AI Generate
            # (ai_chat.generate_response ichida detect_and_save_reminder ham chaqiriladi)
            ai_messages = await ai_chat.generate_response(user_id, text)
            
            # Pro userlar uchun emoji reaksiya (moliyadan yiroq mavzular uchun)
            if user_tariff == 'PRO' and ai_messages:
                # Xabarni tahlil qilish - moliyadan yiroq bo'lsa emoji reaksiya berish
                financial_keywords = ['pul', 'xarajat', 'daromad', 'qarz', 'to\'lov', 'balans', 'hisobot', 
                                     'tranzaksiya', 'chiqim', 'kirim', 'tejash', 'byudjet', 'oylik', 'haftalik',
                                     'tahlil', 'statistika', 'maqsad', 'optimallash', 'qarz',
                                     'sotib oldim', 'sotib oldi', 'xarid qildim', 'xarid qildi', 'to\'ladim', 'to\'ladi',
                                     'oldim', 'oldi', 'sotdim', 'sotdi', 'berdim', 'berdi', 'oldi', 'tushdi', 'tushdi',
                                     'so\'m', 'dollar', 'dollor', 'sum', 'usd', 'uzs', 'ming', 'million', 'mln',
                                     'narx', 'narxi', 'qiymat', 'qiymati', 'summa', 'summasi']
                is_financial = any(keyword in text.lower() for keyword in financial_keywords)
                
                if not is_financial:
                    # Moliyadan yiroq mavzu - emoji reaksiya berish
                    reaction_emoji = None
                    text_lower = text.lower()
                    
                    # G'alaba/kulgu so'zlari
                    if any(word in text_lower for word in ['1-o\'rinni', 'g\'olib', 'yutdim', 'yutdik', 'yutdi', 'yutish', 
                                                           'muvaffaqiyat', 'tabriklayman', 'tabriklay', 'alhamdulillah']):
                        reaction_emoji = "🥳"  # G'alaba/kulgu
                    # Kulgu so'zlari
                    elif any(word in text_lower for word in ['kulgi', 'qiziq', 'ajoyib', 'zo\'r', 'a\'lo', 'juda yaxshi']):
                        reaction_emoji = "😂"  # Kulgu
                    # Xursandlik so'zlari
                    elif any(word in text_lower for word in ['yaxshi', 'mazali', 'yoqimli', 'qiziqarli', 'mukammal']):
                        reaction_emoji = "😊"  # Xursandlik
                    # Hayrat so'zlari
                    elif any(word in text_lower for word in ['hayrat', 'ajoyib', 'qiziq', 'vay', 'qanday']):
                        reaction_emoji = "😮"  # Hayrat
                    else:
                        # Default - moliyaga burish
                        reaction_emoji = "💡"
                    
                    # Emoji reaksiya berish (Telegram Bot API 6.7+)
                    if reaction_emoji:
                        try:
                            # set_message_reaction - yangi API
                            await bot.set_message_reaction(
                                chat_id=message.chat.id,
                                message_id=message.message_id,
                                reaction=[{"type": "emoji", "emoji": reaction_emoji}]
                            )
                        except AttributeError:
                            # Eski API versiyasi - reaction yo'q
                            try:
                                # setMessageReaction - boshqa usul
                                await bot.request("setMessageReaction", {
                                    "chat_id": message.chat.id,
                                    "message_id": message.message_id,
                                    "reaction": [{"type": "emoji", "emoji": reaction_emoji}]
                                })
                            except Exception as e:
                                logging.debug(f"Reaction API not available: {e}")
                            pass
                        except Exception as e:
                            logging.debug(f"Error adding reaction: {e}")
                            pass
            
            # Har bir xabarni 1-3 soniya orasida yuborish (HAR QANDAY mavzu uchun AI javobi)
            for msg in ai_messages:
                await message.answer(msg)  # parse_mode olib tashlandi - emoji ishlatiladi
                await asyncio.sleep(1.5)
        
    except Exception as e:
        logging.error(f"AI chat xatolik: {e}")
        await message.answer("Kechirasiz, xatolik yuz berdi. Iltimos, qayta urinib ko'ring.")

async def process_audio_with_financial_module(
    message: types.Message,
    state: FSMContext,
    audio_path: str,
    user_id: int,
    processing_msg=None
):
    try:
        audio_result = await financial_module.process_audio_input(audio_path, user_id)
        
        if processing_msg:
            try:
                await processing_msg.delete()
            except:
                pass
        
        logging.info(
            f"DEBUG audio_result: success={audio_result.get('success')}, keys={audio_result.keys()}"
        )

        # ===== SUCCESS YO‘LI =====
        if audio_result.get('success'):

            if 'transaction_data' not in audio_result:
                logging.warning("DEBUG: transaction_data yo‘q")
                await message.answer(
                    audio_result.get('message', '❌ Tranzaksiya topilmadi.'),
                    parse_mode='Markdown'
                )
                return audio_result

            transactions = audio_result['transaction_data'].get('transactions', [])
            logging.info(f"DEBUG transactions found: {len(transactions)} ta")

            if not transactions:
                logging.warning("DEBUG: transactions bo‘sh")
                await message.answer(
                    audio_result.get('message', '❌ Tranzaksiya topilmadi.'),
                    parse_mode='Markdown'
                )
                return audio_result

            # ===== SAQLASH =====
            save_result = await financial_module.save_confirmed_transactions(
                transactions, user_id
            )

            if not save_result.get('success'):
                await message.answer(
                    '❌ Saqlashda xatolik yuz berdi.',
                    parse_mode='Markdown'
                )
                return audio_result

            response_message = (
                (audio_result.get('message') or '') +
                "\n\n✅ **Avtomatik saqlandi!**"
            )

            saved_transactions = save_result.get('transactions', [])
                
            for trans in saved_transactions:
                if trans.get('reminder_created') and trans.get('reminder_date'):
                    from datetime import datetime
                    try:
                        d = datetime.strptime(trans['reminder_date'], '%Y-%m-%d')
                        response_message += (
                            f"\n\n📌 **Eslatma qo'shildi!**\n"
                            f"Qaytarish sanasi: {d.strftime('%d-%m-%Y')}"
                        )
                    except:
                        response_message += (
                            "\n\n📌 **Eslatma qo'shildi!**\n"
                            "Qaytarish sanasida eslatiladi."
                        )
            
            # Keyboard yaratish - for loopdan tashqarida
            keyboard_buttons = []
            if len(saved_transactions) == 1:
                keyboard_buttons.append([
                    InlineKeyboardButton(text="✏️ Tahrirlash", callback_data="trans_edit_1"),
                    InlineKeyboardButton(text="🗑️ O'chirish", callback_data="trans_delete_1")
                        ])
            else:
                for i in range(len(saved_transactions)):
                    keyboard_buttons.append([
                        InlineKeyboardButton(text=f"✏️ #{i+1}", callback_data=f"trans_edit_{i+1}"),
                        InlineKeyboardButton(text=f"🗑️ #{i+1}", callback_data=f"trans_delete_{i+1}")
                ])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
                
            await message.answer(
                response_message,
                parse_mode='Markdown',
                reply_markup=keyboard
            )

            await state.update_data(
                saved_transaction_ids=saved_transactions
            )

        # ===== FAIL YO‘LI =====
        else:
            await message.answer(
                audio_result.get('message', '❌ Xatolik yuz berdi.'),
                parse_mode='Markdown'
            )

        return audio_result
    
    except Exception as e:
        logging.error(f"Audio qayta ishlashda xatolik: {e}")
        await message.answer(
            "❌ Texnik xatolik yuz berdi. Iltimos, qayta urinib ko‘ring.",
            parse_mode='Markdown'
        )
        return None

# Audio xabarlarni qayta ishlash (Premium)
@dp.message(lambda message: message.voice or message.audio)
async def process_audio_message(message: types.Message, state: FSMContext):
    """Audio xabarlarni qayta ishlash (Premium)"""
    user_id = message.from_user.id
    # Avtomatik tarif muddatini tekshirish
    await ensure_tariff_valid(user_id)
    user_tariff = await get_user_tariff(user_id)
    
    # Tarif mavjud bo'lmasa audio qo'llab-quvvatlash yo'q
    if user_tariff in ('NONE', None):
        await message.answer(
            "🎵 **Audio qo'llab-quvvatlash**\n\n"
            "Audio xabarlarni qayta ishlash faqat tarif xarid qilgan foydalanuvchilar uchun mavjud.\n"
            "Tarif tanlash uchun mini-ilovani oching.",
            parse_mode='Markdown'
        )
        return
    
    # Faqat pullik tarif uchun audio qo'llab-quvvatlash
    if user_tariff not in PREMIUM_TARIFFS:
        await message.answer(
            "🎵 **Audio qo'llab-quvvatlash**\n\n"
            "Audio xabarlarni qayta ishlash faqat pullik tarifda mavjud.\n"
            "Tarifni yangilash uchun Profil > Tarif bo'limiga o'ting.",
            parse_mode='Markdown'
        )
        return
    
    # Agar foydalanuvchi boshqa holatda bo'lsa (onboarding yoki boshqa state'lar)
    if await state.get_state() in [UserStates.waiting_for_phone, UserStates.waiting_for_name, 
                                   UserStates.waiting_for_source, UserStates.waiting_for_tariff,
                                   UserStates.waiting_for_amount, 
                                   UserStates.waiting_for_category, UserStates.waiting_for_debt_type,
                                   UserStates.waiting_for_debt_person, UserStates.waiting_for_income_type,
                                   UserStates.waiting_for_income_frequency, UserStates.waiting_for_income_amount,
                                   UserStates.waiting_for_income_date, UserStates.waiting_for_income_weekday,
                                   UserStates.waiting_for_income_month, UserStates.waiting_for_income_day]:
        return
    
    # Plus tarifda cheksiz foydalanish mumkin (oylik obuna)
    
    try:
        # Audio faylni yuklab olish
        file_id = message.voice.file_id if message.voice else message.audio.file_id
        file = await bot.get_file(file_id)
        
        # Audio faylni saqlash
        import os
        audio_dir = "temp_audio"
        os.makedirs(audio_dir, exist_ok=True)
        
        audio_path = f"{audio_dir}/audio_{user_id}_{datetime.now().timestamp()}.ogg"
        await bot.download_file(file.file_path, audio_path)
        
        # AI ishlayotganini ko'rsatish
        await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
        
        # Bajarilmoqda xabarini yuborish
        processing_msg = await message.answer("🔄 Bajarilmoqda...", parse_mode='Markdown')
        
        # Faqat bitta model tanlab ishlatish uchun tekshirish
        if not ACTIVE_SPEECH_MODELS.get('GOOGLE', False) and not ACTIVE_SPEECH_MODELS.get('ELEVENLABS', False):
            await processing_msg.delete()
            await message.answer(
                "❌ Hozircha speech model yoqilmagan. Admin bilan bog'laning.",
                parse_mode='Markdown'
            )
            return
        
        # Pro tarifida limit tekshiruvi
        month_year = None
        if user_tariff == 'PRO':
            from datetime import datetime as dt
            month_year = dt.now().strftime('%Y-%m')
            usage = await db.get_or_create_pro_usage(user_id, month_year)
            
            if usage['total_cost'] >= 40000:
                await processing_msg.delete()
                await message.answer(
                    f"⚠️ **Xarajat limiti tugadi!**\n\n"
                    f"Hozirgi oyda API xarajatlari 40,000 so'mdan oshdi.\n"
                    f"Keyingi oyni kutishingiz kerak. Yoki Plus paketga o'ting.",
                    parse_mode='Markdown'
                )
                return
        
        # Financial module audio qayta ishlash (GOOGLE yoki ELEVENLABS tanlaydi)
        audio_result = await process_audio_with_financial_module(message, state, audio_path, user_id, processing_msg)
        
        # Pro tarifida ovozli xarajatni tracking qilish
        if user_tariff == 'PRO' and audio_result and audio_result.get('success'):
            if not month_year:
                from datetime import datetime as dt
                month_year = dt.now().strftime('%Y-%m')
            # Ovozli xabar uchun xarajat (taxminan 20-30 so'm - speech-to-text va AI)
            estimated_voice_cost = 25.0
            await db.increment_pro_usage(user_id, 'voice', estimated_voice_cost, month_year)
            
            # Limit tekshiruvi keyin
            updated_usage = await db.get_or_create_pro_usage(user_id, month_year)
            if updated_usage['total_cost'] >= 40000:
                await message.answer(
                    f"⚠️ Xarajat limiti tugadi! Keyingi oyni kutishingiz kerak.",
                    parse_mode='Markdown'
                )
        
        if user_tariff == 'PLUS':
            # Paket qoldig'i haqida ogohlantirish o'chirildi
            if audio_result and audio_result.get('success'):
                await db.increment_plus_usage(user_id, 'voice')
        
    except Exception as e:
        logging.error(f"Audio xabarni qayta ishlashda xatolik: {e}")
        # Faqat haqiqiy texnik xatoliklar uchun xabar yuborish
        await message.answer(
            "❌ Texnik xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring.",
            parse_mode='Markdown'
        )

# Balans buyrug'i
# /balance buyrug'i olib tashlandi - endi 📊 Hisobotlar tugmasi orqali ko'rish mumkin

# ==================== ONBOARDING FINAL STEP HANDLERS ====================

@dp.callback_query(lambda c: c.data == "start_income_setup")
async def start_income_setup(callback_query: CallbackQuery, state: FSMContext):
    """Daromad sozlamalarini boshlash"""
    await callback_query.message.edit_text(
        "💰 *Asosiy daromad manbaini tanlang:*\n\n"
        "Qaysi turdagi daromad olasiz?",
        parse_mode="Markdown"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏢 Biznes(lar)im bor", callback_data="income_type_business")],
        [InlineKeyboardButton(text="📅 Oylik ish haqi olaman", callback_data="income_type_monthly")],
        [InlineKeyboardButton(text="📆 Haftalik ish haqi olaman", callback_data="income_type_weekly")],
        [InlineKeyboardButton(text="📝 Kunlik ish haqi olaman", callback_data="income_type_daily")],
        [InlineKeyboardButton(text="🗓 Yillik daromad olaman", callback_data="income_type_yearly")]
    ])
    await callback_query.message.answer(
        "Tanlang:",
        reply_markup=keyboard
    )
    await state.set_state(UserStates.waiting_for_income_type)
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "skip_income_setup")
async def skip_income_setup(callback_query: CallbackQuery):
    """Daromad sozlamalarini o'tkazib yuborish"""
    await callback_query.message.edit_text(
        "✅ *Sozlash o'tkazib yuborildi.*\n\n"
        "Siz bu sozlamalarni istalgan vaqtda Profil > Sozlamalar > Daromad sozlamalari bo'limidan o'zgartirishingiz mumkin.",
        parse_mode="Markdown"
    )
    
    await callback_query.message.answer(
        "Pro tarif menyusi:",
        reply_markup=get_premium_menu()
    )
    await callback_query.answer()

@dp.callback_query(lambda c: c.data.startswith("income_type_"), UserStates.waiting_for_income_type)
async def process_income_type(callback_query: CallbackQuery, state: FSMContext):
    """Daromad turini qabul qilish"""
    income_type = callback_query.data.replace("income_type_", "")
    user_id = callback_query.from_user.id
    
    # Daromad turini saqlash
    await state.update_data(income_type=income_type)
    
    if income_type == "business":
        # Biznes uchun hech narsa so'ralmaydi
        await callback_query.message.edit_text(
            "✅ *Biznes daromadi tanlandi.*\n\n"
            "Siz daromadlaringizni qo'lda kiritishingiz mumkin. "
            "AI sizga yordam beradi va avtomatik tahlil qiladi.",
            parse_mode="Markdown"
        )
        
        # Daromad sozlamalarini saqlash
        await db.save_income_settings(user_id, income_type)
        
        await callback_query.message.answer(
            "✅ *Daromad sozlamalari muvaffaqiyatli o'rnatildi.*\n\n"
            "Siz bu sozlamalarni istalgan vaqtda Profil > Sozlamalar > Daromad sozlamalari bo'limidan o'zgartirishingiz mumkin.",
            parse_mode="Markdown"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Asosiy menyuga qaytish", callback_data="back_to_main")]
        ])
        await callback_query.message.answer(
            "Davom etish uchun tugmani bosing:",
            reply_markup=keyboard
        )
        
    elif income_type == "monthly":
        await callback_query.message.edit_text(
            "📅 *Oylik ish haqi tanlandi.*\n\n"
            "Qaysi sanada oylik olasiz? (masalan: har oyning 10-sanasida)",
            parse_mode="Markdown"
        )
        await state.set_state(UserStates.waiting_for_income_date)
        await callback_query.message.answer("DEBUG: State o'rnatildi: waiting_for_income_date")
        
    elif income_type == "weekly":
        await callback_query.message.edit_text(
            "📆 *Haftalik ish haqi tanlandi.*\n\n"
            "Haftaning qaysi kuni olasiz?",
            parse_mode="Markdown"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Dushanba", callback_data="weekday_1")],
            [InlineKeyboardButton(text="Seshanba", callback_data="weekday_2")],
            [InlineKeyboardButton(text="Chorshanba", callback_data="weekday_3")],
            [InlineKeyboardButton(text="Payshanba", callback_data="weekday_4")],
            [InlineKeyboardButton(text="Juma", callback_data="weekday_5")],
            [InlineKeyboardButton(text="Shanba", callback_data="weekday_6")],
            [InlineKeyboardButton(text="Yakshanba", callback_data="weekday_7")]
        ])
        await callback_query.message.answer(
            "Tanlang:",
            reply_markup=keyboard
        )
        await state.set_state(UserStates.waiting_for_income_weekday)
        
    elif income_type == "daily":
        await callback_query.message.edit_text(
            "📝 *Kunlik ish haqi tanlandi.*\n\n"
            "Har kuni qancha olasiz? (masalan: 500 000 so'm)",
            parse_mode="Markdown"
        )
        await state.set_state(UserStates.waiting_for_income_amount)
        
    elif income_type == "yearly":
        await callback_query.message.edit_text(
            "🗓 *Yillik daromad tanlandi.*\n\n"
            "Qaysi oy/kuni olasiz? (masalan: Yanvar oyining 15-sanasida)",
            parse_mode="Markdown"
        )
        await state.set_state(UserStates.waiting_for_income_month)
    
    await callback_query.answer()

# Bu handler'ni o'chirib tashlaymiz va fayl oxiriga qo'yamiz

@dp.callback_query(lambda c: c.data.startswith("weekday_"), UserStates.waiting_for_income_weekday)
async def process_income_weekday(callback_query: CallbackQuery, state: FSMContext):
    """Haftalik daromad kunini qabul qilish"""
    weekday = int(callback_query.data.replace("weekday_", ""))
    weekday_names = ["", "Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
    
    await state.update_data(income_weekday=weekday)
    
    await callback_query.message.edit_text(
        f"📆 *{weekday_names[weekday]} tanlandi.*\n\n"
        f"Qancha haftalik olasiz? (masalan: 2 500 000 so'm)",
        parse_mode="Markdown"
    )
    await state.set_state(UserStates.waiting_for_income_amount)
    await callback_query.answer()

@dp.message(UserStates.waiting_for_income_month)
async def process_income_month(message: types.Message, state: FSMContext):
    """Yillik daromad oyini qabul qilish"""
    await state.update_data(income_month=message.text)
    await message.answer(
        f"🗓 *{message.text} tanlandi.*\n\n"
        f"Qaysi sanada olasiz? (masalan: 15)",
        parse_mode="Markdown"
    )
    await state.set_state(UserStates.waiting_for_income_day)

@dp.message(UserStates.waiting_for_income_day)
async def process_income_day(message: types.Message, state: FSMContext):
    """Yillik daromad kunini qabul qilish"""
    try:
        day = int(message.text)
        if 1 <= day <= 31:
            await state.update_data(income_day=day)
            await message.answer(
                f"📅 *{day}-sana tanlandi.*\n\n"
                f"Qancha yillik olasiz? (masalan: 120 000 000 so'm)",
                parse_mode="Markdown"
            )
            await state.set_state(UserStates.waiting_for_income_amount)
        else:
            await message.answer(
                "❌ Noto'g'ri sana! 1-31 orasida kiriting.",
                parse_mode="Markdown"
            )
    except ValueError:
        await message.answer(
            "❌ Faqat raqam kiriting! (masalan: 15)",
            parse_mode="Markdown"
        )

@dp.message(UserStates.waiting_for_income_amount)
async def process_income_amount(message: types.Message, state: FSMContext):
    """Daromad miqdorini qabul qilish - AI yordamida"""
    text = message.text
    
    # AI yordamida matnni tahlil qilish
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    # Bajarilmoqda xabarini yuborish
    processing_msg = await message.answer("🔄 Bajarilmoqda...", parse_mode='Markdown')
    
    try:
        # OpenAI API yordamida matnni tahlil qilish
        import openai
        from config import OPENAI_API_KEY
        
        openai.api_key = OPENAI_API_KEY
        
        response = await openai.ChatCompletion.acreate(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "Siz matndan faqat raqamni ajratib olishingiz kerak. Foydalanuvchi oylik maosh miqdorini aytdi. Faqat raqamni qaytaring (faqat raqam, hech qanday matn yo'q). Agar raqam topilmasa, 'ERROR' yozing."
                },
                {
                    "role": "user", 
                    "content": f"Matn: '{text}'\n\nBu matndan maosh miqdorini aniqlang. Faqat raqamni qaytaring."
                }
            ],
            max_tokens=20,
            temperature=0.1
        )
        
        ai_response = response.choices[0].message.content.strip()
        
        # Bajarilmoqda xabarini o'chirish
        try:
            await processing_msg.delete()
        except:
            pass
        
        # AI javobini tekshirish
        if ai_response == "ERROR":
            await message.answer(
                "❌ Miqdor tushunilmadi! Raqam bilan yozing (masalan: 1000000)",
                parse_mode="Markdown"
            )
            return
        
        # Matndan faqat raqamlarni ajratib olish
        import re
        numbers = re.findall(r'\d+', ai_response)
        if not numbers:
            await message.answer(
                "❌ Miqdor tushunilmadi! Raqam bilan yozing (masalan: 1000000)",
                parse_mode="Markdown"
            )
            return
        
        amount = float(numbers[0])
        
        if amount <= 0:
            await message.answer(
                "❌ Miqdor 0 dan katta bo'lishi kerak!",
                parse_mode="Markdown"
            )
            return
        
        # State ma'lumotlarini olish
        data = await state.get_data()
        income_type = data.get('income_type')
        user_id = message.from_user.id
        
        # Daromad sozlamalarini saqlash
        if income_type == "monthly":
            await db.save_income_settings(
                user_id, income_type, amount, 
                frequency_day=data.get('income_day')
            )
        elif income_type == "weekly":
            await db.save_income_settings(
                user_id, income_type, amount,
                frequency_weekday=data.get('income_weekday')
            )
        elif income_type == "daily":
            await db.save_income_settings(user_id, income_type, amount)
        elif income_type == "yearly":
            await db.save_income_settings(
                user_id, income_type, amount,
                frequency_month=data.get('income_month'),
                frequency_day=data.get('income_day')
            )
        
        await message.answer(
            "✅ *Daromad sozlamalari muvaffaqiyatli o'rnatildi.*\n\n"
            "Siz bu sozlamalarni istalgan vaqtda Profil > Sozlamalar > Daromad sozlamalari bo'limidan o'zgartirishingiz mumkin.",
            parse_mode="Markdown"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Asosiy menyuga qaytish", callback_data="back_to_main")]
        ])
        await message.answer(
            "Davom etish uchun tugmani bosing:",
            reply_markup=keyboard
        )
        
        await state.clear()
        
    except Exception as e:
        # Bajarilmoqda xabarini o'chirish
        try:
            await processing_msg.delete()
        except:
            pass
            
        logging.error(f"AI tahlil xatoligi: {e}")
        await message.answer(
            "❌ Xatolik yuz berdi. Raqam bilan yozing (masalan: 1000000)",
            parse_mode="Markdown"
        )

@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main_menu(callback_query: CallbackQuery):
    """Asosiy menyuga qaytish"""
    await callback_query.message.edit_text(
        "🏠 *Asosiy menyuga qaytildi.*\n\n"
        "Pro tarif menyusi:",
        parse_mode="Markdown"
    )
    
    await callback_query.message.answer(
        "Tanlang:",
        reply_markup=get_premium_menu()
    )
    await callback_query.answer()

# ==================== INCOME DATE HANDLER ====================

@dp.message(UserStates.waiting_for_income_date)
async def process_income_date(message: types.Message, state: FSMContext):
    """Oylik daromad sanasini qabul qilish - AI yordamida"""
    text = message.text
    
    # Debug uchun
    await message.answer(f"DEBUG: Handler ishga tushdi! Sana qabul qilindi: {text}")
    await message.answer(f"DEBUG: Current state: {await state.get_state()}")
    
    # AI yordamida matnni tahlil qilish
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    # Bajarilmoqda xabarini yuborish
    processing_msg = await message.answer("🔄 Bajarilmoqda...", parse_mode='Markdown')
    
    try:
        # Oddiy regex bilan test qilish
        import re
        numbers = re.findall(r'\d+', text)
        
        if numbers:
            day = int(numbers[0])
            if 1 <= day <= 31:
                # Bajarilmoqda xabarini o'chirish
                try:
                    await processing_msg.delete()
                except:
                    pass
                    
                await state.update_data(income_day=day)
                await message.answer(
                    f"📅 *{day}-sana tanlandi.*\n\n"
                    f"Qancha oylik olasiz? (masalan: 10 000 000 so'm)",
                    parse_mode="Markdown"
                )
                await state.set_state(UserStates.waiting_for_income_amount)
            else:
                # Bajarilmoqda xabarini o'chirish
                try:
                    await processing_msg.delete()
                except:
                    pass
                    
                await message.answer(
                    "❌ Noto'g'ri sana! 1-31 orasida kiriting.",
                    parse_mode="Markdown"
                )
        else:
            # Bajarilmoqda xabarini o'chirish
            try:
                await processing_msg.delete()
            except:
                pass
                
            await message.answer(
                "❌ Sana tushunilmadi! Raqam bilan yozing (masalan: 10)",
                parse_mode="Markdown"
            )
            
    except Exception as e:
        # Bajarilmoqda xabarini o'chirish
        try:
            await processing_msg.delete()
        except:
            pass
            
        logging.error(f"Xatolik: {e}")
        await message.answer(
            f"❌ Xatolik yuz berdi: {str(e)}",
            parse_mode="Markdown"
        )

# ==================== TRANSACTION CONFIRMATION HANDLERS ====================

@dp.callback_query(lambda c: c.data.startswith("debt_add_date_") or c.data.startswith("debt_add_name_"))
async def handle_debt_add_callback(callback_query: CallbackQuery, state: FSMContext):
    """Qarz qo'shimcha tugmalar uchun handler (debt_add_date_, debt_add_name_)"""
    user_id = callback_query.from_user.id
    callback_data = callback_query.data
    
    try:
        # saved_transactions dan trans_id ni topish
        data = await state.get_data()
        saved_transactions = data.get('saved_transaction_ids', [])
        
        if not saved_transactions or len(saved_transactions) == 0:
            await callback_query.answer("❌ Tranzaksiya topilmadi", show_alert=True)
            return
        
        trans = saved_transactions[0]  # Bitta tranzaksiya bo'lgani uchun
        trans_id = trans.get('id')
        
        if not trans_id:
            await callback_query.answer("❌ Tranzaksiya ID topilmadi", show_alert=True)
            return
        
        if callback_data.startswith("debt_add_date_"):
            await state.update_data(editing_transaction_id=trans_id, editing_field='due_date', date_step='year')
            
            # Yil tanlash tugmalari
            from datetime import datetime
            current_year = datetime.now().year
            year_buttons = []
            for year in range(current_year, current_year + 3):
                year_buttons.append(InlineKeyboardButton(text=str(year), callback_data=f"debt_date_year_{year}_{trans_id}"))
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                year_buttons,
                [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_to_transaction")]
            ])
            
            await callback_query.message.edit_text(
                "📅 **Qaytarish sanasi qo'shish**\n\nYilni tanlang:",
                parse_mode='Markdown',
                reply_markup=keyboard
            )
            await callback_query.answer()
        elif callback_data.startswith("debt_add_name_"):
            await state.update_data(editing_transaction_id=trans_id, editing_field='person_name')
            await callback_query.message.edit_text(
                "👤 **Ism qo'shish**\n\nQarz olgan/bergan odamning ismini kiriting:",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_to_transaction")]
                ])
            )
            await state.set_state(UserStates.waiting_for_debt_edit_name)
            await callback_query.answer()
    except Exception as e:
        logging.error(f"debt_add callback handler xatolik: {e}")
        await callback_query.answer("❌ Xatolik yuz berdi", show_alert=True)

@dp.callback_query(lambda c: c.data.startswith("debt_date_"))
async def handle_debt_date_callback(callback_query: CallbackQuery, state: FSMContext):
    """Qarz sana tanlash tugmalari uchun handler"""
    callback_data = callback_query.data
    
    try:
        # Yil tanlash (debt_date_year_2025_123)
        if callback_data.startswith("debt_date_year_"):
            parts = callback_data.split("_")
            year = int(parts[3])
            trans_id = int(parts[4])
            await state.update_data(editing_transaction_id=trans_id, editing_field='due_date', selected_year=year, date_step='month')
            
            # Oy tanlash tugmalari - faqat kelajak oylarni ko'rsatish
            from datetime import datetime
            current_date = datetime.now()
            current_year = current_date.year
            current_month = current_date.month
            
            month_names = ['Yanvar', 'Fevral', 'Mart', 'Aprel', 'May', 'Iyun', 'Iyul', 'Avgust', 'Sentabr', 'Oktabr', 'Noyabr', 'Dekabr']
            month_buttons = []
            
            # Agar hozirgi yil bo'lsa, hozirgi oyni ham ko'rsatish (hozirgi oyning oxirigacha kunlar bor)
            start_month = 1
            if year == current_year:
                start_month = current_month  # Hozirgi oyni ham ko'rsatish (chunki hozirgi oyning oxirigacha kunlar bor)
            
            # Oylarni qatorlarga bo'lish
            for i in range(start_month - 1, 12, 3):
                row = []
                for j in range(3):
                    month_num = i + j + 1
                    if month_num <= 12:
                        row.append(InlineKeyboardButton(text=month_names[i+j], callback_data=f"debt_date_month_{year}_{month_num}_{trans_id}"))
                if row:
                    month_buttons.append(row)
            
            if not month_buttons:
                await callback_query.answer("❌ Bu yilda barcha oylar o'tgan!", show_alert=True)
                return
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=month_buttons + [
                [InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"debt_edit_date_{trans_id}"),
                 InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_to_transaction")]
            ])
            
            await callback_query.message.edit_text(
                f"📅 **Qaytarish sanasi qo'shish**\n\nYil: {year}\n\nOyni tanlang:",
                parse_mode='Markdown',
                reply_markup=keyboard
            )
            await callback_query.answer()
            return
        
        # Oy tanlash (debt_date_month_2025_12_123)
        if callback_data.startswith("debt_date_month_"):
            parts = callback_data.split("_")
            year = int(parts[3])
            month = int(parts[4])
            trans_id = int(parts[5])
            await state.update_data(editing_transaction_id=trans_id, editing_field='due_date', selected_year=year, selected_month=month, date_step='day')
            
            # Sana tanlash tugmalari - faqat kelajak kunlarni ko'rsatish
            from datetime import datetime, date
            from calendar import monthrange
            current_date = datetime.now().date()
            
            days_in_month = monthrange(year, month)[1]
            day_buttons = []
            
            # Agar hozirgi yil va oy bo'lsa, faqat bugundan keyingi kunlarni ko'rsatish
            start_day = 1
            if year == current_date.year and month == current_date.month:
                start_day = current_date.day + 1
            
            # Kunlarni qatorlarga bo'lish
            for i in range(start_day - 1, days_in_month, 7):
                row = []
                for j in range(7):
                    day_num = i + j + 1
                    if day_num <= days_in_month:
                        row.append(InlineKeyboardButton(text=str(day_num), callback_data=f"debt_date_day_{year}_{month}_{day_num}_{trans_id}"))
                if row:
                    day_buttons.append(row)
            
            if not day_buttons:
                await callback_query.answer("❌ Bu oyda barcha kunlar o'tgan!", show_alert=True)
                return
            
            month_names = ['Yanvar', 'Fevral', 'Mart', 'Aprel', 'May', 'Iyun', 'Iyul', 'Avgust', 'Sentabr', 'Oktabr', 'Noyabr', 'Dekabr']
            keyboard = InlineKeyboardMarkup(inline_keyboard=day_buttons + [
                [InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"debt_date_year_{year}_{trans_id}"),
                 InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_to_transaction")]
            ])
            
            await callback_query.message.edit_text(
                f"📅 **Qaytarish sanasi qo'shish**\n\nYil: {year}\nOy: {month_names[month-1]}\n\nSanani tanlang:",
                parse_mode='Markdown',
                reply_markup=keyboard
            )
            await callback_query.answer()
            return
        
        # Sana tanlash (debt_date_day_2025_12_31_123)
        if callback_data.startswith("debt_date_day_"):
            parts = callback_data.split("_")
            year = int(parts[3])
            month = int(parts[4])
            day = int(parts[5])
            trans_id = int(parts[6])
            
            # Sana yaratish va saqlash
            from datetime import date
            due_date = date(year, month, day)
            due_date_str = due_date.strftime('%Y-%m-%d')
            
            # Tranzaksiyani yangilash
            update_result = await db.update_transaction(trans_id, callback_query.from_user.id, due_date=due_date_str)
            
            if update_result.get('success'):
                # Eslatma yaratish
                try:
                    await db.execute_insert(
                        "INSERT INTO debt_reminders (user_id, transaction_id, reminder_date) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE reminder_date = %s",
                        (callback_query.from_user.id, trans_id, due_date_str, due_date_str)
                    )
                except Exception as e:
                    logging.error(f"Eslatma yaratishda xatolik: {e}")
                
                # Tranzaksiya ma'lumotlarini olish
                trans_query = """
                    SELECT t.*, d.person_name as debt_person_name
                    FROM transactions t
                    LEFT JOIN debts d ON d.user_id = t.user_id 
                        AND ABS(d.amount - t.amount) < 0.01 
                        AND d.debt_type = t.debt_direction
                        AND ABS(TIMESTAMPDIFF(SECOND, d.created_at, t.created_at)) < 60
                    WHERE t.id = %s AND t.user_id = %s
                    LIMIT 1
                """
                trans = await db.execute_one(trans_query, (trans_id, callback_query.from_user.id))
                
                if trans:
                    # Qarz xabarini yaratish
                    month_names = ['Yanvar', 'Fevral', 'Mart', 'Aprel', 'May', 'Iyun', 'Iyul', 'Avgust', 'Sentabr', 'Oktabr', 'Noyabr', 'Dekabr']
                    due_date_formatted = f"{day}-{month_names[month-1]}, {year}"
                    
                    trans_type = trans.get('transaction_type', '')
                    debt_direction = trans.get('debt_direction', '')
                    amount = float(trans.get('amount', 0))
                    currency = trans.get('currency', 'UZS')
                    person_name_raw = trans.get('description', '').split('ga')[0].strip() if 'ga' in trans.get('description', '') else trans.get('debt_person_name', '')
                    created_at = trans.get('created_at')
                    
                    # Markdown escape funksiyasi
                    def escape_markdown(text):
                        if not text:
                            return ''
                        text = str(text)
                        # Markdown special karakterlarni escape qilish
                        return text.replace('*', '\\*').replace('_', '\\_').replace('[', '\\[').replace(']', '\\]').replace('(', '\\(').replace(')', '\\)')
                    
                    person_name = escape_markdown(person_name_raw) if person_name_raw else ''
                    
                    # Created_at ni formatlash
                    if created_at:
                        if isinstance(created_at, str):
                            from datetime import datetime
                            created_at = datetime.strptime(created_at.split('.')[0], '%Y-%m-%d %H:%M:%S')
                        created_at_str = created_at.strftime('%d-%m-%Y')
                    else:
                        created_at_str = "Noma'lum"
                    
                    # Valyuta formatlash
                    currency_names = {'UZS': 'so\'m', 'USD': 'USD', 'EUR': 'EUR', 'RUB': 'RUB', 'TRY': 'TRY'}
                    currency_display = currency_names.get(currency, currency)
                    amount_formatted = f"{amount:,.0f} {currency_display}"
                    
                    # Xabar yaratish
                    if debt_direction == 'lent':
                        message = f"💳 **Qarz berish:**\n"
                        message += f"Berilgan vaqt: {created_at_str}\n\n"
                        if person_name:
                            message += f"👤 **{person_name}**\n"
                        message += f"Summasi: {amount_formatted}\n"
                        message += f"Qaytarish vaqti: {due_date_formatted}\n"
                        if trans.get('description'):
                            description = escape_markdown(trans.get('description', ''))
                            message += f"Izoh: {description}\n"
                    elif debt_direction == 'borrowed':
                        message = f"💳 **Qarz olish:**\n"
                        message += f"Olingan vaqt: {created_at_str}\n\n"
                        if person_name:
                            message += f"👤 **{person_name}**\n"
                        message += f"Summasi: {amount_formatted}\n"
                        message += f"Qaytarish vaqti: {due_date_formatted}\n"
                        if trans.get('description'):
                            description = escape_markdown(trans.get('description', ''))
                            message += f"Izoh: {description}\n"
                    else:
                        message = f"💳 **Qarz:**\n"
                        message += f"Vaqt: {created_at_str}\n\n"
                        if person_name:
                            message += f"👤 **{person_name}**\n"
                        message += f"Summasi: {amount_formatted}\n"
                        message += f"Qaytarish vaqti: {due_date_formatted}\n"
                    
                    message += f"\n📌 **Eslatma qo'shildi!**\nQaytarish sanasida ({due_date_formatted}) eslatiladi."
                    
                    # Tugmalar - O'chirish va Tahrirlash
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [
                            InlineKeyboardButton(text="✏️ Tahrirlash", callback_data=f"trans_edit_{trans_id}"),
                            InlineKeyboardButton(text="🗑️ O'chirish", callback_data=f"trans_delete_{trans_id}")
                        ]
                    ])
                    
                    await callback_query.message.edit_text(
                        message,
                        parse_mode='Markdown',
                        reply_markup=keyboard
                    )
                    await callback_query.answer("✅ Sana qo'shildi!")
                else:
                    month_names = ['Yanvar', 'Fevral', 'Mart', 'Aprel', 'May', 'Iyun', 'Iyul', 'Avgust', 'Sentabr', 'Oktabr', 'Noyabr', 'Dekabr']
                    due_date_formatted = f"{day}-{month_names[month-1]}, {year}"
                    await callback_query.message.edit_text(
                        f"✅ **Qaytarish sanasi qo'shildi!**\n\n📅 Sana: {due_date_formatted}\n\n📌 **Eslatma qo'shildi!**\nQaytarish sanasida ({due_date_formatted}) eslatiladi.",
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_transaction")]
                        ])
                    )
                    await callback_query.answer("✅ Sana qo'shildi!")
            else:
                await callback_query.answer("❌ Xatolik yuz berdi!", show_alert=True)
            return
            
    except Exception as e:
        logging.error(f"debt_date callback handler xatolik: {e}")
        await callback_query.answer("❌ Xatolik yuz berdi", show_alert=True)

@dp.callback_query(lambda c: c.data.startswith("trans_"))
async def handle_transaction_callback(callback_query: CallbackQuery, state: FSMContext):
    """Tranzaksiya tugmalari uchun umumiy handler"""
    print(f"DEBUG: Transaction callback received: {callback_query.data}")
    user_id = callback_query.from_user.id
    callback_data = callback_query.data
    
    try:
        # O'chirish tugmasi - avtomatik saqlangan tranzaksiya uchun
        if callback_data.startswith("trans_delete_"):
            index = int(callback_data.split("_")[2])
            data = await state.get_data()
            saved_transactions = data.get('saved_transaction_ids', [])
            
            # Tranzaksiyani o'chirish
            if saved_transactions:
                for trans in saved_transactions:
                    if trans.get('index') == index or (len(saved_transactions) == 1 and index == 1):
                        trans_id = trans.get('id')
                        if trans_id:
                            try:
                                # Database funksiyasidan foydalanish (debts va balansni ham yangilaydi)
                                delete_result = await db.delete_transaction(trans_id, user_id)
                                
                                if delete_result.get('success'):
                                    trans_type = delete_result.get('transaction_type')
                                    amount = delete_result.get('amount', 0)
                                    currency = delete_result.get('currency', 'UZS')
                                    
                                    # Valyuta formatlash
                                    currency_names = {'UZS': "so'm", 'USD': "dollar", 'EUR': "evro", 'RUB': "rubl", 'TRY': "lira"}
                                    currency_symbols = {'UZS': "", 'USD': "🇺🇸", 'EUR': "🇪🇺", 'RUB': "🇷🇺", 'TRY': "🇹🇷"}
                                    currency_name = currency_names.get(currency, currency)
                                    currency_symbol = currency_symbols.get(currency, "💰")
                                    
                                    if currency != 'UZS':
                                        amount_text = f"{currency_symbol} {amount:,.2f} {currency_name}"
                                    else:
                                        amount_text = f"{amount:,.0f} so'm"
                                    
                                    type_names = {
                                        'income': 'Kirim',
                                        'expense': 'Chiqim',
                                        'debt': 'Qarz'
                                    }
                                    type_name = type_names.get(trans_type, 'Tranzaksiya')
                                    
                                    await callback_query.message.edit_text(
                                        f"🗑️ **{type_name} o'chirildi!**\n\n"
                                        f"Summa: {amount_text}\n\n"
                                        f"Balans yangilandi.",
                                        parse_mode='Markdown'
                                    )
                                    await callback_query.answer("✅ O'chirildi va balans yangilandi!")
                                    await state.clear()
                                    return
                                else:
                                    await callback_query.answer(f"❌ {delete_result.get('message', 'Xatolik')}", show_alert=True)
                                    return
                            except Exception as e:
                                logging.error(f"Tranzaksiya o'chirishda xatolik: {e}")
                                await callback_query.answer("❌ O'chirishda xatolik yuz berdi", show_alert=True)
                                return
            
            await callback_query.answer("❌ Tranzaksiya topilmadi", show_alert=True)
            return
        
        # Tahrirlash tugmasi
        if callback_data.startswith("trans_edit_"):
            # Callback data format: trans_edit_{index} yoki trans_edit_{trans_id}
            parts = callback_data.split("_")
            if len(parts) >= 3:
                try:
                    trans_id_or_index = int(parts[2])
                    trans_id = None
                    
                    # Avval database dan to'g'ridan-to'g'ri tekshiramiz (trans_id bo'lishi mumkin)
                    trans_query = """
                        SELECT * FROM transactions WHERE id = %s AND user_id = %s
                    """
                    trans = await db.execute_one(trans_query, (trans_id_or_index, user_id))
                    
                    if trans:
                        # Database da topildi - bu trans_id
                        trans_id = trans_id_or_index
                    else:
                        # Database da topilmadi - saved_transactions dan qidiramiz (index bo'lishi mumkin)
                        data = await state.get_data()
                        saved_transactions = data.get('saved_transaction_ids', [])
                        for trans_item in saved_transactions:
                            if trans_item.get('index') == trans_id_or_index or (len(saved_transactions) == 1 and trans_id_or_index == 1):
                                trans_id = trans_item.get('id')
                                break
                        
                        if trans_id:
                            # saved_transactions dan topildi - endi database dan olamiz
                            trans = await db.execute_one(trans_query, (trans_id, user_id))
                        else:
                            await callback_query.answer("❌ Tranzaksiya topilmadi", show_alert=True)
                            return
                    
                    if not trans:
                        await callback_query.answer("❌ Tranzaksiya topilmadi", show_alert=True)
                        return
                        
                except ValueError:
                    await callback_query.answer("❌ Noto'g'ri tranzaksiya ID", show_alert=True)
                    return
            else:
                await callback_query.answer("❌ Noto'g'ri format", show_alert=True)
                return
            
            trans_type = trans.get('transaction_type', '')
            debt_direction = trans.get('debt_direction', '')
            
            # Tahrirlash menyusini yaratish
            keyboard = InlineKeyboardMarkup(inline_keyboard=[])
            
            if trans_type == 'debt' or debt_direction:
                # Qarz uchun tahrirlash imkoniyatlari
                keyboard.inline_keyboard.append([InlineKeyboardButton(text="👤 Ismni tahrirlash", callback_data=f"debt_edit_name_{trans_id}")])
                keyboard.inline_keyboard.append([InlineKeyboardButton(text="📅 Qaytarish sanasini tahrirlash", callback_data=f"debt_edit_date_{trans_id}")])
            elif trans_type in ('income', 'expense'):
                # Kirim/Chiqim uchun tahrirlash imkoniyatlari
                keyboard.inline_keyboard.append([InlineKeyboardButton(text="💰 Summani tahrirlash", callback_data=f"trans_edit_amount_{trans_id}")])
                keyboard.inline_keyboard.append([InlineKeyboardButton(text="📝 Izohni tahrirlash", callback_data=f"trans_edit_description_{trans_id}")])
            
            keyboard.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_transaction")])
            
            trans_type_names = {
                'income': 'Kirim',
                'expense': 'Chiqim',
                'debt': 'Qarz'
            }
            trans_type_name = trans_type_names.get(trans_type, trans_type)
            
            await callback_query.message.edit_text(
                "🚧 **Tez orada**\n\nBu funksiya tez orada qo'shiladi.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_transaction")]
                ])
            )
            await callback_query.answer()
            return
        
        # Qarz ism qo'shish
        if callback_data.startswith("debt_edit_name_"):
            trans_id = int(callback_data.split("_")[3])
            await state.update_data(editing_transaction_id=trans_id, editing_field='person_name')
            await callback_query.message.edit_text(
                "👤 **Ism qo'shish**\n\nQarz olgan/bergan odamning ismini kiriting:",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_to_transaction")]
                ])
            )
            await state.set_state(UserStates.waiting_for_debt_edit_name)
            await callback_query.answer()
            return
        
        # Qarz qaytarish sanasi tahrirlash
        if callback_data.startswith("debt_edit_date_"):
            trans_id = int(callback_data.split("_")[3])
            await state.update_data(editing_transaction_id=trans_id, editing_field='due_date', date_step='year')
            
            # Yil tanlash tugmalari
            from datetime import datetime
            current_year = datetime.now().year
            year_buttons = []
            for year in range(current_year, current_year + 3):
                year_buttons.append(InlineKeyboardButton(text=str(year), callback_data=f"debt_date_year_{year}_{trans_id}"))
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                year_buttons,
                [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_to_transaction")]
            ])
            
            await callback_query.message.edit_text(
                "📅 **Qaytarish sanasini tahrirlash**\n\nYilni tanlang:",
                parse_mode='Markdown',
                reply_markup=keyboard
            )
            await callback_query.answer()
            return
        
        # Summa tahrirlash
        if callback_data.startswith("trans_edit_amount_"):
            trans_id = int(callback_data.split("_")[3])
            await state.update_data(editing_transaction_id=trans_id, editing_field='amount')
            await callback_query.message.edit_text(
                "💰 **Summani tahrirlash**\n\nYangi summani kiriting:",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_to_transaction")]
                ])
            )
            await state.set_state(UserStates.waiting_for_trans_edit_amount)
            await callback_query.answer()
            return
        
        # Izoh tahrirlash
        if callback_data.startswith("trans_edit_description_"):
            trans_id = int(callback_data.split("_")[3])
            await state.update_data(editing_transaction_id=trans_id, editing_field='description')
            await callback_query.message.edit_text(
                "📝 **Izohni tahrirlash**\n\nYangi izohni kiriting:",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_to_transaction")]
                ])
            )
            await state.set_state(UserStates.waiting_for_trans_edit_description)
            await callback_query.answer()
            return
        
        # Eslatma tahrirlash
        if callback_data.startswith("reminder_edit_"):
            reminder_id = int(callback_data.split("_")[2])
            await callback_query.message.edit_text(
                "🚧 **Tez orada**\n\nBu funksiya tez orada qo'shiladi.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_transaction")]
                ])
            )
            await callback_query.answer()
            return
        
        # Eslatma o'chirish
        if callback_data.startswith("reminder_delete_"):
            reminder_id = int(callback_data.split("_")[2])
            # Database dan eslatmani o'chirish
            try:
                await db.execute_query(
                    "DELETE FROM reminders WHERE id = %s AND user_id = %s",
                    (reminder_id, user_id)
                )
                await callback_query.message.edit_text(
                    "✅ **Eslatma o'chirildi!**",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logging.error(f"Eslatma o'chirishda xatolik: {e}")
                await callback_query.answer("❌ Eslatma o'chirishda xatolik yuz berdi", show_alert=True)
            await callback_query.answer()
            return
        
        # Qarz qo'shimcha tugmalar (debt_add_date_1, debt_add_name_1 formatlari)
        if callback_data.startswith("debt_add_date_"):
            # saved_transactions dan trans_id ni topish
            data = await state.get_data()
            saved_transactions = data.get('saved_transaction_ids', [])
            
            if saved_transactions and len(saved_transactions) >= 1:
                trans = saved_transactions[0]  # Bitta tranzaksiya bo'lgani uchun
                trans_id = trans.get('id')
                
                if trans_id:
                    await state.update_data(editing_transaction_id=trans_id, editing_field='due_date', date_step='year')
                    
                    # Yil tanlash tugmalari
                    from datetime import datetime
                    current_year = datetime.now().year
                    year_buttons = []
                    for year in range(current_year, current_year + 3):
                        year_buttons.append(InlineKeyboardButton(text=str(year), callback_data=f"debt_date_year_{year}_{trans_id}"))
                    
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        year_buttons,
                        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_to_transaction")]
                    ])
                    
                    await callback_query.message.edit_text(
                        "📅 **Qaytarish sanasi qo'shish**\n\nYilni tanlang:",
                        parse_mode='Markdown',
                        reply_markup=keyboard
                    )
                    await callback_query.answer()
                    return
            
            await callback_query.answer("❌ Tranzaksiya topilmadi", show_alert=True)
            return
        
        if callback_data.startswith("debt_add_name_"):
            # saved_transactions dan trans_id ni topish
            data = await state.get_data()
            saved_transactions = data.get('saved_transaction_ids', [])
            
            if saved_transactions and len(saved_transactions) >= 1:
                trans = saved_transactions[0]  # Bitta tranzaksiya bo'lgani uchun
                trans_id = trans.get('id')
                
                if trans_id:
                    await state.update_data(editing_transaction_id=trans_id, editing_field='person_name')
                    await callback_query.message.edit_text(
                        "👤 **Ism qo'shish**\n\nQarz olgan/bergan odamning ismini kiriting:",
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_to_transaction")]
                        ])
                    )
                    await state.set_state(UserStates.waiting_for_debt_edit_name)
                    await callback_query.answer()
                    return
            
            await callback_query.answer("❌ Tranzaksiya topilmadi", show_alert=True)
            return
        
        # State ni tekshirish
        current_state = await state.get_state()
        print(f"DEBUG: Current state: {current_state}")
        
        data = await state.get_data()
        transaction_data = data.get('transaction_data', {})
        print(f"DEBUG: Transaction data from state: {transaction_data}")
        
        # Agar state bo'sh bo'lsa yoki transaction_data yo'q bo'lsa
        if not transaction_data or not data.get('transaction_data'):
            print("DEBUG: No transaction data found in state, trying to recreate from message")
            
            # Callback query message text dan tranzaksiya ma'lumotlarini qayta parse qilish
            message_text = callback_query.message.text or callback_query.message.caption or ""
            
            # Financial module dan qaytadan parse qilish
            if message_text and "Tranzaksiya aniqlandi" in message_text:
                # Message text dan tranzaksiyani qayta parse qilish - original text ni topish
                # Message text dan "Izoh:" qismidan keyin original text bor
                original_text = ""
                if "Izoh:" in message_text:
                    izoh_part = message_text.split("Izoh:")[-1].split("\n")[0].strip().strip('"')
                    original_text = izoh_part
                
                if original_text:
                    # Original text dan qaytadan parse qilish
                    financial_result = await financial_module.process_ai_input_advanced(original_text, user_id)
                    
                    if financial_result.get('success') and financial_result.get('transaction_data'):
                        transaction_data = financial_result['transaction_data']
                        await state.set_state(UserStates.waiting_for_transaction_confirmation)
                        await state.update_data(transaction_data=transaction_data)
                        print(f"DEBUG: Recreated transaction_data from original text: {transaction_data}")
                    else:
                        await callback_query.answer("❌ Tranzaksiya ma'lumotlari topilmadi! Iltimos, qaytadan yuboring.", show_alert=True)
                        return
                else:
                    await callback_query.answer("❌ Tranzaksiya ma'lumotlari topilmadi! Iltimos, qaytadan yuboring.", show_alert=True)
                    return
            else:
                await callback_query.answer("❌ Tranzaksiya ma'lumotlari topilmadi! Iltimos, qaytadan yuboring.", show_alert=True)
                return
        
        # Financial module orqali ishlov berish
        print(f"DEBUG: Calling financial_module.handle_transaction_action with data: {callback_query.data}")
        result = await financial_module.handle_transaction_action(
            callback_query.data, 
            callback_query.from_user.id, 
            transaction_data
        )
        print(f"DEBUG: Financial module result: {result}")
        
        if result['success']:
            print(f"DEBUG: Transaction action successful: {result}")
            if result.get('type') == 'completed':
                # Barcha ish tugadi
                print("DEBUG: Clearing state and showing completion message")
                await state.clear()
                await callback_query.message.edit_text(
                    result['message'], 
                    parse_mode='Markdown',
                    reply_markup=None
                )
                await callback_query.answer()
            elif result.get('type') == 'updated_preview':
                # Yangi preview ko'rsatish
                buttons_data = result['buttons_data']
                transactions = buttons_data.get('transactions', [])
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[])
                
                # Har bir tranzaksiya uchun tugmalar - 2 qator bo'lib
                delete_buttons = []
                for item in transactions:
                    index = item['index']
                    delete_buttons.append(InlineKeyboardButton(text=f"🗑️ #{index}", callback_data=f"trans_delete_{index}"))
                    
                    # Har 2 ta tugma bo'lganda yangi qatorga o'tamiz
                    if len(delete_buttons) == 2:
                        keyboard.inline_keyboard.append(delete_buttons)
                        delete_buttons = []
                
                # Qolgan tugmalarni qo'shamiz
                if delete_buttons:
                    keyboard.inline_keyboard.append(delete_buttons)
                
                # Umumiy tugmalar
                keyboard.inline_keyboard.append([
                    InlineKeyboardButton(text="✅ Hammasini saqlash", callback_data="trans_all"),
                    InlineKeyboardButton(text="❌ Hammasini o'chirish", callback_data="trans_cancel")
                ])
                
                await callback_query.message.edit_text(
                    result['message'], 
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
            else:
                # Oddiy xabar
                print(f"DEBUG: Showing simple message: {result['message']}")
                await callback_query.message.edit_text(
                    result['message'], 
                    parse_mode='Markdown',
                    reply_markup=None
                )
        else:
            print(f"DEBUG: Transaction action failed: {result['message']}")
            await callback_query.answer(result['message'])
        
        await callback_query.answer()
        
    except Exception as e:
        print(f"DEBUG: Exception in transaction callback: {e}")
        logging.error(f"Tranzaksiya callback ishlov berishda xatolik: {e}")
        await callback_query.answer("❌ Xatolik yuz berdi!")

# ==================== PAYMENTS HANDLERS (Telegram Payments / CLICK) ====================

@dp.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_q: types.PreCheckoutQuery):
    """To'lovdan oldingi tekshiruvni tasdiqlash"""
    try:
        user_id = pre_checkout_q.from_user.id
        # Faqat bir xil tarifni qayta sotib olishni bloklaymiz
        try:
            user_data = await db.get_user_data(user_id)
            current = user_data.get('tariff') if user_data else 'NONE'
            payload = pre_checkout_q.invoice_payload or ""
            
            # Faqat bir xil tarifni qayta sotib olishni bloklaymiz
            if current == 'PLUS' and payload.startswith("plus:") and await is_paid_active(user_id):
                await bot.answer_pre_checkout_query(pre_checkout_q.id, ok=False, error_message="Sizda Plus obuna allaqachon aktiv. Qayta to'lov kerak emas.")
                return
            
            if current == 'BUSINESS' and payload.startswith("business:") and await is_paid_active(user_id):
                await bot.answer_pre_checkout_query(pre_checkout_q.id, ok=False, error_message="Sizda Business obuna allaqachon aktiv. Qayta to'lov kerak emas.")
                return
        except Exception as _e:
            logging.error(f"pre_checkout guard error: {_e}")
        await bot.answer_pre_checkout_query(pre_checkout_q.id, ok=True)
    except Exception as e:
        logging.error(f"PreCheckout xato: {e}")
        await bot.answer_pre_checkout_query(
            pre_checkout_q.id,
            ok=False,
            error_message="To'lovni tasdiqlashda xatolik yuz berdi. Keyinroq urinib ko'ring."
        )


@dp.message(lambda m: m.successful_payment is not None)
async def process_successful_payment(message: types.Message, state: FSMContext):
    """To'lov muvaffaqiyatli yakunlangach ishlov berish"""
    try:
        user_id = message.from_user.id
        
        # To'lov tugmasini o'chirish
        try:
            if user_id in LAST_INVOICE_MESSAGE_ID:
                invoice_msg_id = LAST_INVOICE_MESSAGE_ID[user_id]
                await message.bot.delete_message(chat_id=user_id, message_id=invoice_msg_id)
                del LAST_INVOICE_MESSAGE_ID[user_id]
            # Tanlangan to'lov usuli haqida yuqoridagi xabarni ham o'chiramiz
            if user_id in LAST_PAYMENT_INFO_MESSAGE_ID:
                info_msg_id = LAST_PAYMENT_INFO_MESSAGE_ID[user_id]
                try:
                    await message.bot.delete_message(chat_id=user_id, message_id=info_msg_id)
                except Exception:
                    pass
                LAST_PAYMENT_INFO_MESSAGE_ID.pop(user_id, None)
        except:
            pass
        
        payload = message.successful_payment.invoice_payload or ""
        if payload.startswith("plus:"):
            # Payload format (legacy): plus:user_id:timestamp:extra...
            parts = payload.split(":")
            raw_package_code = parts[4] if len(parts) > 4 else None

            sp = message.successful_payment
            total_amount = sp.total_amount
            currency = sp.currency
            telegram_charge_id = sp.telegram_payment_charge_id
            provider_charge_id = sp.provider_payment_charge_id

            package_code = resolve_plus_package_code(raw_package_code, total_amount)
            package_info = PLUS_PACKAGES.get(package_code) if package_code else None

            if package_info:
                await db.create_plus_package_purchase(
                    user_id,
                    package_code,
                    package_info['text_limit'],
                    package_info['voice_limit']
                )
                await db.set_active_tariff(user_id, "PLUS", None)
                package_name = package_info.get('name', package_code)
                usage_line = f"📦 Paket: {package_name}\n✉️ Matn limit: {package_info['text_limit']}\n🎙 Ovoz limit: {package_info['voice_limit']}"
            else:
                # Fallback legacy monthly subscription
                months = int(parts[3]) if len(parts) > 3 else 1
                expires_at = datetime.now() + timedelta(days=30 * months)
                await db.add_user_subscription(user_id, "PLUS", expires_at)
                await db.set_active_tariff(user_id, "PLUS", expires_at)
                usage_line = f"⏰ Muddati: {expires_at.strftime('%d.%m.%Y')}"

            await db.execute_insert(
                """
                INSERT INTO payments (user_id, tariff, total_amount, currency, payload, telegram_charge_id, provider_charge_id, merchant_trans_id, status, paid_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, 'paid', NOW())
                """,
                (user_id, 'PLUS', total_amount, currency, payload, telegram_charge_id, provider_charge_id)
            )

            try:
                balance_query = """
                SELECT COUNT(*) as count FROM transactions 
                WHERE user_id = %s AND category IN ('boshlang_ich_naqd', 'boshlang_ich_karta')
                """
                result = await db.execute_one(balance_query, (user_id,))
                has_initial_balance = result and result.get('count', 0) > 0
            except Exception:
                has_initial_balance = True

            user_name = await get_user_name(user_id)
            caption_lines = [
                "🎉 **To'lov muvaffaqiyatli!**",
                f"Raxmat, {user_name}!",
                "",
                "✨ **Plus paket aktivlashtirildi**" if package_info else "✨ **Plus tarif aktivlashtirildi**",
                "",
            ]
            if package_info:
                caption_lines.append(usage_line)
            else:
                caption_lines.extend([
                    "Endi siz quyidagi imkoniyatlardan foydalanishingiz mumkin:",
                    "• AI yordamida ovozli va matnli kiritish",
                    "• Tezkor moliyaviy tahlillar",
                    "• Shaxsiy byudjetni kuzatish",
                    "• Cheksiz tranzaksiyalar",
                    "",
                    usage_line
                ])
            caption_lines.append("\nBoshlash tugmasini bosing yoki /start buyrug'ini yuboring")

            await message.answer_photo(
                photo=FSInputFile('welcome.png'),
                caption="\n".join(caption_lines),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🚀 Boshlash", callback_data="start_onboarding")]
                ]),
                parse_mode='Markdown'
            )
            
            if not has_initial_balance:
                await state.set_state(UserStates.waiting_for_initial_cash)
            else:
                try:
                    await ensure_tariff_valid(user_id)
                except Exception:
                    pass
                current_tariff = await get_user_tariff(user_id)
                if current_tariff == 'BUSINESS':
                    await message.answer(
                        "Business tarif menyusi:",
                        reply_markup=get_business_menu()
                    )
                elif current_tariff in ('PLUS', 'PRO', 'MAX'):
                    await message.answer(
                        "Pro tarif menyusi:" if current_tariff == 'PRO' else "Plus paket menyusi:",
                        reply_markup=get_premium_menu()
                    )
                else:
                    await message.answer(
                        "Balans AI bilan davom etish uchun paket tanlang:",
                        reply_markup=get_plus_purchase_keyboard()
                    )
            # Pending holatini tozalash
            try:
                _pending_clear(PENDING_PLUS_PAYMENTS, user_id)
            except Exception:
                pass
            # Oxirgi invoice xabarini o'chirishga urinamiz
            try:
                msg_id = LAST_INVOICE_MESSAGE_ID.get(user_id)
                if msg_id:
                    await bot.delete_message(chat_id=user_id, message_id=msg_id)
                    LAST_INVOICE_MESSAGE_ID.pop(user_id, None)
                # To'lov ma'lumotlari xabarini ham o'chiramiz
                info_msg_id = LAST_PAYMENT_INFO_MESSAGE_ID.get(user_id)
                if info_msg_id:
                    try:
                        await bot.delete_message(chat_id=user_id, message_id=info_msg_id)
                    except Exception:
                        pass
                    LAST_PAYMENT_INFO_MESSAGE_ID.pop(user_id, None)
            except Exception as _e:
                logging.error(f"delete invoice message error: {_e}")
        elif payload.startswith("business:"):
            # Payload format: business:user_id:timestamp:months
            parts = payload.split(":")
            months = int(parts[3]) if len(parts) > 3 else 1
            
            from datetime import datetime, timedelta
            expires_at = datetime.now() + timedelta(days=30 * months)
            await db.add_user_subscription(user_id, "BUSINESS", expires_at)
            await db.set_active_tariff(user_id, "BUSINESS", expires_at)

            sp = message.successful_payment
            await db.execute_insert(
                """
                INSERT INTO payments (user_id, tariff, total_amount, currency, payload, telegram_charge_id, provider_charge_id, merchant_trans_id, status, paid_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, 'paid', NOW())
                """,
                (
                    user_id,
                    'BUSINESS',
                    sp.total_amount,
                    sp.currency,
                    payload,
                    sp.telegram_payment_charge_id,
                    sp.provider_payment_charge_id
                )
            )

            # To'lovdan so'ng onboarding holatini tekshiramiz
            try:
                balance_query = """
                SELECT COUNT(*) as count FROM transactions 
                WHERE user_id = %s AND category IN ('boshlang_ich_naqd', 'boshlang_ich_karta')
                """
                result = await db.execute_one(balance_query, (user_id,))
                has_initial_balance = result and result.get('count', 0) > 0
            except Exception:
                has_initial_balance = True

            # To'lov muvaffaqiyatli bo'lgach rasmli xabar
            user_name = await get_user_name(user_id)
            await message.answer_photo(
                photo=FSInputFile('welcome.png'),
                caption=(
                    f"🎉 **To'lov muvaffaqiyatli!**\n\n"
                    f"Raxmat, {user_name}!\n\n"
                    f"✨ **Business tarif aktivlashtirildi**\n\n"
                    f"Endi siz quyidagi imkoniyatlardan foydalanishingiz mumkin:\n"
                    f"• Kichik biznes uchun maxsus funksiyalar\n"
                    f"• 1 boshliq + 1 xodim\n"
                    f"• Moliyaviy boshqaruvni avtomatlashtirish\n"
                    f"• AI yordamida biznes tahlillari\n\n"
                    f"Boshlash tugmasini bosing yoki /start buyrug'ini yuboring"
                ),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🚀 Boshlash", callback_data="start_onboarding")]
                ]),
                parse_mode='Markdown'
            )
            
            if not has_initial_balance:
                await state.set_state(UserStates.waiting_for_initial_cash)
            else:
                # Foydalanuvchining amaldagi tarifiga mos menyuni ko'rsatamiz
                try:
                    await ensure_tariff_valid(user_id)
                except Exception:
                    pass
                current_tariff = await get_user_tariff(user_id)
                if current_tariff == 'BUSINESS':
                    await message.answer(
                        "Business tarif menyusi:",
                        reply_markup=get_business_menu()
                    )
                elif current_tariff in ('PLUS', 'PRO', 'MAX'):
                    await message.answer(
                        "Plus tarif menyusi:",
                        reply_markup=get_premium_menu()
                    )
                else:
                    await message.answer(
                        "Balans AI bilan davom etish uchun paket tanlang:",
                        reply_markup=get_plus_purchase_keyboard()
                    )

            try:
                _pending_clear(PENDING_BUSINESS_PAYMENTS, user_id)
            except Exception:
                pass
            try:
                msg_id = LAST_INVOICE_MESSAGE_ID.get(user_id)
                if msg_id:
                    await bot.delete_message(chat_id=user_id, message_id=msg_id)
                    LAST_INVOICE_MESSAGE_ID.pop(user_id, None)
                # To'lov ma'lumotlari xabarini ham o'chiramiz
                info_msg_id = LAST_PAYMENT_INFO_MESSAGE_ID.get(user_id)
                if info_msg_id:
                    try:
                        await bot.delete_message(chat_id=user_id, message_id=info_msg_id)
                    except Exception:
                        pass
                    LAST_PAYMENT_INFO_MESSAGE_ID.pop(user_id, None)
            except Exception as _e:
                logging.error(f"delete invoice message error: {_e}")
    except Exception as e:
        logging.error(f"Successful payment processing error: {e}")
        await message.answer("❌ To'lovdan keyin tarifni faollashtirishda xatolik yuz berdi. Admin bilan bog'laning.")



async def load_config_from_db():
    """Bazadan sozlamalarni yuklab olish"""
    try:
        # Speech models - Google Cloud Speech-to-Text ni default True qilamiz
        result = await db.execute_one("SELECT value FROM config WHERE key_name = 'active_speech_google'")
        if result:
            ACTIVE_SPEECH_MODELS['GOOGLE'] = result.get('value', 'true').lower() == 'true'
        else:
            # Agar bazada yo'q bo'lsa, default True va bazaga qo'shamiz
            ACTIVE_SPEECH_MODELS['GOOGLE'] = True
            await db.execute_query(
                "INSERT INTO config (key_name, value) VALUES ('active_speech_google', 'true')"
            )
        
        # Agar Google False bo'lsa, uni True qilamiz (Google Cloud Speech-to-Text ishlatish uchun)
        if not ACTIVE_SPEECH_MODELS['GOOGLE']:
            ACTIVE_SPEECH_MODELS['GOOGLE'] = True
            await db.execute_query(
                "UPDATE config SET value = 'true' WHERE key_name = 'active_speech_google'"
            )
        
        result = await db.execute_one("SELECT value FROM config WHERE key_name = 'active_speech_elevenlabs'")
        if result:
            ACTIVE_SPEECH_MODELS['ELEVENLABS'] = result.get('value', 'false').lower() == 'true'
        else:
            # Agar bazada yo'q bo'lsa, default False (Google ishlatiladi)
            ACTIVE_SPEECH_MODELS['ELEVENLABS'] = False
        
        # Free trials
        result = await db.execute_one("SELECT value FROM config WHERE key_name = 'free_trial_plus'")
        if result:
            FREE_TRIAL_ENABLED['PLUS'] = result.get('value', 'false').lower() == 'true'
        
        result = await db.execute_one("SELECT value FROM config WHERE key_name = 'free_trial_pro'")
        if not result:
            # Eski nomdagi kalitdan fallback
            result = await db.execute_one("SELECT value FROM config WHERE key_name = 'free_trial_max'")
        if result:
            FREE_TRIAL_ENABLED['PRO'] = result.get('value', 'false').lower() == 'true'
        
        result = await db.execute_one("SELECT value FROM config WHERE key_name = 'free_trial_business'")
        if result:
            FREE_TRIAL_ENABLED['BUSINESS'] = result.get('value', 'false').lower() == 'true'
        
        print("✅ Sozlamalar bazadan yuklandi!")
    except Exception as e:
        logging.error(f"Config yuklash xatolik: {e}")
        print("⚠️ Sozlamalar yuklashda xatolik, default qiymatlar ishlatiladi")

async def start_bot():
    """Bot ishga tushirish"""
    try:
        print("📊 Ma'lumotlar bazasini ulash...")
        # Ma'lumotlar bazasini ulash
        await db.create_pool()
        print("✅ Ma'lumotlar bazasi ulandi!")
        
        print("📋 Jadvallarni yaratish...")
        # Jadvallarni yaratish
        await db.create_tables()
        print("✅ Jadvallar yaratildi!")
        
        print("⚙️ Sozlamalarni yuklash...")
        # Bazadan sozlamalarni yuklash
        await load_config_from_db()
        
        print("🤖 Bot polling ni boshlash...")
        # Bot ishga tushirish
        await dp.start_polling(bot)
    except Exception as e:
        print(f"❌ Bot ishga tushishda xatolik: {e}")
        logging.error(f"Bot start xatolik: {e}")
        raise
    finally:
        if hasattr(bot, 'session'):
            await bot.session.close()

# ==================== ONBOARDING HANDLERS (SINOVCHILAR UCHUN) ====================

@dp.message(OnboardingState.waiting_for_income)
async def onboarding_income_handler(message: types.Message, state: FSMContext):
    """Onboarding: Oylik daromad qabul qilish"""
    user_id = message.from_user.id
    
    try:
        income = float(message.text.replace(',', '').replace(' ', ''))
        if income < 0:
            await message.answer("❌ Daromad manfiy bo'lishi mumkin emas. Qaytadan kiriting:")
            return
    except ValueError:
        await message.answer("❌ Noto'g'ri format. Faqat raqam kiriting (masalan: 5000000):")
        return
    
    # Daromadni saqlash
    await state.update_data(monthly_income=income)
    
    # Eski xabarlarni o'chirish
    try:
        await message.delete()
    except:
        pass
    
    # 2-bosqich: Balans (rasmli xabar)
    await message.answer_photo(
        photo=FSInputFile('welcome.png'),
        caption=(
            "💰 **1-qadam: Boshlang'ich balans**\n\n"
            "Qancha pulingiz bor? (naqd pul + karta)\n\n"
            "Masalan: 500000 (agar 500,000 so'm bo'lsa)"
        ),
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='Markdown'
    )
    
    await state.set_state(UserStates.onboarding_balance)

# ==================== USER STEPS FUNCTIONS ====================
    """Onboarding: Balans qabul qilish"""
    user_id = message.from_user.id
    
    try:
        balance = float(message.text.replace(',', '').replace(' ', ''))
        if balance < 0:
            await message.answer("❌ Balans manfiy bo'lishi mumkin emas. Qaytadan kiriting:")
            return
    except ValueError:
        await message.answer("❌ Noto'g'ri format. Faqat raqam kiriting (masalan: 2000000):")
        return
    
    # Balansni saqlash
    await state.update_data(current_balance=balance)
    
    # Eski xabarlarni o'chirish
    try:
        await message.delete()
    except:
        pass
    
    # 3-bosqich: Qarzlar
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Qarz berganman", callback_data="onboarding_debt_lent")],
        [InlineKeyboardButton(text="➖ Qarz olganman", callback_data="onboarding_debt_borrowed")],
        [InlineKeyboardButton(text="❌ Qarzlar yo'q", callback_data="onboarding_no_debts")]
    ])
    
    await message.answer(
        "💳 **Onboarding bosqichi 3/3**\n\n"
        "Qarzlar holatingizni belgilang:",
        parse_mode='Markdown',
        reply_markup=keyboard
    )
    
    await state.set_state(OnboardingState.waiting_for_debts)

@dp.callback_query(lambda c: c.data == "onboarding_no_debts")
async def onboarding_no_debts_handler(callback_query: CallbackQuery, state: FSMContext):
    """Onboarding: Qarzlar yo'q"""
    user_id = callback_query.from_user.id
    
    # Ma'lumotlarni olish
    data = await state.get_data()
    monthly_income = data.get('monthly_income', 0)
    current_balance = data.get('current_balance', 0)
    
    # Balansni saqlash (agar 0 dan katta bo'lsa)
    if current_balance > 0:
        await db.add_transaction(user_id, 'income', int(current_balance), 'boshlang_ich_balans', 'Onboarding: boshlang\'ich balans')
    
    # Tarifni aktiv qilish
    data = await state.get_data()
    tariff = data.get('onboarding_tariff', 'NONE')
    await db.execute_query("UPDATE users SET tariff = %s WHERE user_id = %s", (tariff, user_id))
    
    # Onboarding yakunlash
    await callback_query.message.edit_text(
        "🎉 **Onboarding yakunlandi!**\n\n"
        f"📊 Oylik daromad: {monthly_income:,.0f} so'm\n"
        f"💰 Balans: {current_balance:,.0f} so'm\n"
        f"💳 Qarzlar: Yo'q\n\n"
        "✅ Endi barcha funksiyalardan foydalanishingiz mumkin!",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu")]
        ])
    )
    
    # State ni tozalash
    await state.clear()
    await callback_query.answer("✅ Onboarding yakunlandi!")

@dp.callback_query(lambda c: c.data == "onboarding_debt_lent")
async def onboarding_debt_lent_handler(callback_query: CallbackQuery, state: FSMContext):
    """Onboarding: Qarz bergan"""
    await callback_query.message.edit_text(
        "💳 **Qarz bergan odamlar**\n\n"
        "Kimga qarz berganmisiz va qancha?\n\n"
        "Format: Ism - Summa\n"
        "Misol: Ahmad - 500000",
        parse_mode='Markdown'
    )
    
    await state.set_state(OnboardingState.waiting_for_debts)
    await callback_query.answer("Qarz ma'lumotlarini kiriting")

@dp.callback_query(lambda c: c.data == "onboarding_debt_borrowed")
async def onboarding_debt_borrowed_handler(callback_query: CallbackQuery, state: FSMContext):
    """Onboarding: Qarz olgan"""
    await callback_query.message.edit_text(
        "💳 **Qarz olgan odamlar**\n\n"
        "Kimdan qarz olganmisiz va qancha?\n\n"
        "Format: Ism - Summa\n"
        "Misol: Karim - 300000",
        parse_mode='Markdown'
    )
    
    await state.set_state(OnboardingState.waiting_for_debts)
    await callback_query.answer("Qarz ma'lumotlarini kiriting")

@dp.message(OnboardingState.waiting_for_debts)
async def onboarding_debts_handler(message: types.Message, state: FSMContext):
    """Onboarding: Qarz ma'lumotlarini qabul qilish"""
    user_id = message.from_user.id
    text = message.text.strip()
    
    # Ma'lumotlarni olish
    data = await state.get_data()
    monthly_income = data.get('monthly_income', 0)
    current_balance = data.get('current_balance', 0)
    
    # Balansni saqlash (agar 0 dan katta bo'lsa)
    if current_balance > 0:
        await db.add_transaction(user_id, 'income', int(current_balance), 'boshlang_ich_balans', 'Onboarding: boshlang\'ich balans')
    
    # Qarz ma'lumotlarini saqlash (oddiy format)
    try:
        if ' - ' in text:
            name, amount = text.split(' - ', 1)
            amount = float(amount.replace(',', '').replace(' ', ''))
            
            # Qarz ma'lumotlarini saqlash (oddiy tranzaksiya sifatida)
            await db.add_transaction(user_id, 'expense', int(amount), 'qarz_berish', f'Qarz berilgan: {name.strip()}')
            
            debt_info = f"Qarz berilgan: {name.strip()} - {amount:,.0f} so'm"
        else:
            debt_info = f"Qarz ma'lumoti: {text}"
    except:
        debt_info = f"Qarz ma'lumoti: {text}"
    
    # Tarifni aktiv qilish
    tariff = data.get('onboarding_tariff', 'NONE')
    await db.execute_query("UPDATE users SET tariff = %s WHERE user_id = %s", (tariff, user_id))
    
    # Onboarding yakunlash
    await message.answer(
        "🎉 **Onboarding yakunlandi!**\n\n"
        f"📊 Oylik daromad: {monthly_income:,.0f} so'm\n"
        f"💰 Balans: {current_balance:,.0f} so'm\n"
        f"💳 {debt_info}\n\n"
        "✅ Endi barcha funksiyalardan foydalanishingiz mumkin!",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu")]
        ])
    )
    
    # State ni tozalash
    await state.clear()

# ==================== USER STEPS FUNCTIONS ====================

# ==================== BACKGROUND TASKS ====================

async def send_daily_reports():
    """Kunlik hisobotlarni yuborish - kechki 9 da (faqat Pro)"""
    while True:
        try:
            from datetime import datetime
            now = datetime.now()
            
            # Kechki 21:00 da ishlash
            target_hour = 21
            target_minute = 0
            
            # Keyingi 21:00 ni hisoblash
            next_run = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
            if now.hour >= target_hour or (now.hour == target_hour and now.minute >= target_minute):
                next_run += timedelta(days=1)
            
            # Keyingi ishlash vaqtigacha kutish
            wait_seconds = (next_run - now).total_seconds()
            await asyncio.sleep(wait_seconds)
            
            # Pro userlarni olish
            pro_users = await db.execute_query("""
                SELECT DISTINCT user_id FROM users 
                WHERE tariff = 'PRO' 
                OR user_id IN (
                    SELECT user_id FROM user_subscriptions 
                    WHERE tariff = 'PRO' AND is_active = TRUE AND expires_at > NOW()
                )
            """)
            
            for user_row in pro_users:
                try:
                    user_id = user_row[0] if isinstance(user_row, tuple) else user_row.get('user_id')
                    if not user_id:
                        continue
                    
                    # Bugungi tranzaksiyalarni tekshirish
                    today_transactions = await db.execute_query("""
                        SELECT COUNT(*) as count FROM transactions 
                        WHERE user_id = %s AND DATE(created_at) = CURDATE()
                    """, (user_id,))
                    
                    has_transactions = today_transactions[0].get('count', 0) > 0 if today_transactions else False
                    
                    if not has_transactions:
                        # Tranzaksiya yo'q bo'lsa
                        await bot.send_message(
                            user_id,
                            "📋 Bugun xarajat yoki daromad qo'shmadingiz.\n\n"
                            "Agar qo'shgan bo'lsangiz, ularni hozir ayting, men yozib qo'yaman 😊"
                        )
                    else:
                        # Bugungi statistikalar
                        today_stats = await db.execute_query("""
                            SELECT 
                                SUM(CASE WHEN transaction_type = 'income' THEN amount ELSE 0 END) as income,
                                SUM(CASE WHEN transaction_type = 'expense' THEN amount ELSE 0 END) as expense
                            FROM transactions 
                            WHERE user_id = %s AND DATE(created_at) = CURDATE()
                        """, (user_id,))
                        
                        income = float(today_stats[0].get('income', 0)) if today_stats and today_stats[0].get('income') else 0
                        expense = float(today_stats[0].get('expense', 0)) if today_stats and today_stats[0].get('expense') else 0
                        
                        # Qarzlar
                        debts = await db.execute_query("""
                            SELECT 
                                SUM(CASE WHEN debt_type = 'lent' THEN amount ELSE 0 END) as lent,
                                SUM(CASE WHEN debt_type = 'borrowed' THEN amount ELSE 0 END) as borrowed
                            FROM debts 
                            WHERE user_id = %s AND status != 'paid'
                        """, (user_id,))
                        
                        lent = float(debts[0].get('lent', 0)) if debts and debts[0].get('lent') else 0
                        borrowed = float(debts[0].get('borrowed', 0)) if debts and debts[0].get('borrowed') else 0
                        
                        # Hisobot xabari
                        report = f"📊 **Bugungi kun oxiri hisoboti:**\n\n"
                        report += f"💰 Kirim: {income:,.0f} so'm\n"
                        report += f"💸 Chiqim: {expense:,.0f} so'm\n"
                        report += f"📈 Qoldiq: {income - expense:,.0f} so'm\n\n"
                        
                        if lent > 0 or borrowed > 0:
                            report += f"💳 Qarzlar:\n"
                            if lent > 0:
                                report += f"  • Berilgan: {lent:,.0f} so'm\n"
                            if borrowed > 0:
                                report += f"  • Olingan: {borrowed:,.0f} so'm\n"
                            report += "\n"
                        
                        # AI tahlil
                        try:
                            context = await ai_chat.get_user_financial_context(user_id)
                            analysis_prompt = f"Bugungi kun oxiri hisoboti:\nKirim: {income:,.0f}, Chiqim: {expense:,.0f}\nQarzlar: Berilgan {lent:,.0f}, Olingan {borrowed:,.0f}\n\nTahlil qiling va qisqa tavsiya bering (max 2 gap)."
                            analysis = await ai_chat.generate_response(user_id, analysis_prompt)
                            if analysis and len(analysis) > 0:
                                report += f"{analysis[0]}\n"
                        except Exception as e:
                            logging.error(f"Error generating daily analysis: {e}")
                        
                        await bot.send_message(user_id, report, parse_mode='Markdown')
                    
                    # Kichik delay
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    logging.error(f"Error sending daily report to user {user_id}: {e}")
                    continue
            
        except Exception as e:
            logging.error(f"Error in daily reports task: {e}")
            await asyncio.sleep(3600)  # 1 soat kutish va qayta urinish

async def send_reminders():
    """DONA AI Eslatmalar tizimi - har minutda tekshirish
    
    2 ta bildirishnoma yuboriladi:
    1. Tadbirdan 30 minut oldin
    2. Tadbir vaqtida
    """
    while True:
        try:
            from datetime import datetime, time as dt_time
            
            # 30 minut oldin bildirishnomalar
            reminders_30min = await db.get_reminders_for_30min_notification()
            
            for reminder_row in reminders_30min:
                try:
                    # Reminder ma'lumotlarini olish
                    if isinstance(reminder_row, tuple):
                        reminder_id = reminder_row[0]
                        user_id = reminder_row[1]
                        reminder_type = reminder_row[2]
                        title = reminder_row[3]
                        description = reminder_row[4]
                        reminder_date = reminder_row[5]
                        reminder_time = reminder_row[6]
                        amount = reminder_row[7]
                        currency = reminder_row[8]
                        person_name = reminder_row[9]
                        location = reminder_row[10] if len(reminder_row) > 10 else None
                        user_name = reminder_row[-1] if len(reminder_row) > 15 else None
                    else:
                        reminder_id = reminder_row.get('id')
                        user_id = reminder_row.get('user_id')
                        reminder_type = reminder_row.get('reminder_type')
                        title = reminder_row.get('title')
                        description = reminder_row.get('description')
                        reminder_date = reminder_row.get('reminder_date')
                        reminder_time = reminder_row.get('reminder_time')
                        amount = reminder_row.get('amount')
                        currency = reminder_row.get('currency')
                        person_name = reminder_row.get('person_name')
                        location = reminder_row.get('location')
                        user_name = reminder_row.get('user_name')
                    
                    # Vaqtni formatlash
                    time_str = str(reminder_time)[:5] if reminder_time else "09:00"
                    
                    # 30 minut oldin eslatma xabari
                    message = f"⏰ **30 daqiqa qoldi!**\n\n"
                    message += f"📌 {title}\n"
                    if person_name:
                        message += f"👤 {person_name} bilan\n"
                    if location:
                        message += f"📍 {location}\n"
                    message += f"🕐 Soat {time_str} da\n"
                    if description:
                        message += f"\n📝 {description[:200]}\n"
                    if amount and float(amount) > 0:
                        message += f"\n💰 {float(amount):,.0f} {currency or 'UZS'}\n"
                    
                    await bot.send_message(user_id, message, parse_mode='Markdown')
                    
                    # Bildirishnoma yuborilganini belgilash
                    await db.mark_notification_30min_sent(reminder_id)
                    
                    await asyncio.sleep(0.3)
                    
                except Exception as e:
                    logging.error(f"Error sending 30min reminder {reminder_id}: {e}")
                    continue
            
            # Aniq vaqtda bildirishnomalar
            reminders_exact = await db.get_reminders_for_exact_notification()
            
            for reminder_row in reminders_exact:
                try:
                    # Reminder ma'lumotlarini olish
                    if isinstance(reminder_row, tuple):
                        reminder_id = reminder_row[0]
                        user_id = reminder_row[1]
                        reminder_type = reminder_row[2]
                        title = reminder_row[3]
                        description = reminder_row[4]
                        reminder_date = reminder_row[5]
                        reminder_time = reminder_row[6]
                        amount = reminder_row[7]
                        currency = reminder_row[8]
                        person_name = reminder_row[9]
                        location = reminder_row[10] if len(reminder_row) > 10 else None
                        is_recurring = reminder_row[11] if len(reminder_row) > 11 else False
                        recurrence_pattern = reminder_row[12] if len(reminder_row) > 12 else None
                    else:
                        reminder_id = reminder_row.get('id')
                        user_id = reminder_row.get('user_id')
                        reminder_type = reminder_row.get('reminder_type')
                        title = reminder_row.get('title')
                        description = reminder_row.get('description')
                        reminder_date = reminder_row.get('reminder_date')
                        reminder_time = reminder_row.get('reminder_time')
                        amount = reminder_row.get('amount')
                        currency = reminder_row.get('currency')
                        person_name = reminder_row.get('person_name')
                        location = reminder_row.get('location')
                        is_recurring = reminder_row.get('is_recurring', False)
                        recurrence_pattern = reminder_row.get('recurrence_pattern')
                    
                    # Eslatma turiga qarab emoji
                    type_emojis = {
                        'meeting': '🤝',
                        'event': '🎉',
                        'task': '📋',
                        'debt_give': '💸',
                        'debt_receive': '💰',
                        'payment': '💳',
                        'other': '🔔'
                    }
                    emoji = type_emojis.get(reminder_type, '🔔')
                    
                    # Eslatma turiga qarab xabar
                    type_messages = {
                        'meeting': 'Uchrashuv vaqti keldi',
                        'event': 'Tadbir vaqti keldi',
                        'task': 'Vazifa vaqti keldi',
                        'debt_give': 'Qarz berish vaqti',
                        'debt_receive': 'Qarz olish vaqti',
                        'payment': 'To\'lov vaqti',
                        'other': 'Eslatma vaqti'
                    }
                    
                    # Aniq vaqtda eslatma xabari
                    message = f"{emoji} **{type_messages.get(reminder_type, 'Eslatma vaqti')}!**\n\n"
                    message += f"📌 {title}\n"
                    if person_name:
                        message += f"👤 {person_name} bilan\n"
                    if location:
                        message += f"📍 {location}\n"
                    if description:
                        message += f"\n📝 {description[:200]}\n"
                    if amount and float(amount) > 0:
                        message += f"\n💰 {float(amount):,.0f} {currency or 'UZS'}\n"
                    
                    # Takrorlanadigan eslatma uchun
                    if is_recurring:
                        message += "\n🔄 Takrorlanadigan eslatma"
                    
                    await bot.send_message(user_id, message, parse_mode='Markdown')
                    
                    # Bildirishnoma yuborilganini belgilash
                    await db.mark_notification_exact_sent(reminder_id)
                    
                    # Agar takrorlanadigan eslatma bo'lsa, keyingi eslatmani yaratish
                    if is_recurring:
                        try:
                            await db.create_next_recurring_reminder(reminder_id)
                        except Exception as e:
                            logging.error(f"Error creating next recurring reminder: {e}")
                    
                    await asyncio.sleep(0.3)
                    
                except Exception as e:
                    logging.error(f"Error sending exact reminder {reminder_id}: {e}")
                    continue
            
            # Har minutda tekshirish
            await asyncio.sleep(60)
                    
        except Exception as e:
            logging.error(f"Error in reminders task: {e}")
            await asyncio.sleep(60)

async def send_daily_reminder_9am():
    """Har kuni 9:00 da barcha userlar uchun tranzaksiya eslatmasi"""
    while True:
        try:
            from datetime import datetime
            now = datetime.now()
            
            # Ertalab 09:00 da ishlash
            target_hour = 9
            target_minute = 0
            
            # Keyingi 09:00 ni hisoblash
            next_run = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
            if now.hour >= target_hour or (now.hour == target_hour and now.minute >= target_minute):
                next_run += timedelta(days=1)
            
            # Keyingi ishlash vaqtigacha kutish
            wait_seconds = (next_run - now).total_seconds()
            await asyncio.sleep(wait_seconds)
            
            # Barcha aktiv userlarni olish (tarif bo'lganlar)
            active_users = await db.execute_query("""
                SELECT DISTINCT user_id FROM users 
                WHERE tariff NOT IN ('NONE', 'FREE', NULL)
                OR user_id IN (
                    SELECT user_id FROM user_subscriptions 
                    WHERE is_active = TRUE AND expires_at > NOW()
                )
                OR user_id IN (
                    SELECT user_id FROM plus_package_purchases 
                    WHERE status = 'active' 
                    AND (text_used < text_limit OR voice_used < voice_limit)
                )
            """)
            
            for user_row in active_users:
                try:
                    user_id = user_row[0] if isinstance(user_row, tuple) else user_row.get('user_id')
                    if not user_id:
                        continue
                    
                    # Bugungi tranzaksiyalarni tekshirish
                    today_transactions = await db.execute_one("""
                        SELECT COUNT(*) FROM transactions 
                        WHERE user_id = %s AND DATE(created_at) = CURDATE()
                    """, (user_id,))
                    
                    has_transactions = today_transactions[0] > 0 if today_transactions else False
                    
                    if not has_transactions:
                        # Tranzaksiya yo'q bo'lsa
                        await bot.send_message(
                            user_id,
                            "📋 Bugun hali tranzaksiya qo'shmadingiz.\n\n"
                            "Xarajat yoki daromad qo'shing, men yozib qo'yaman 😊"
                        )
                    else:
                        # Tranzaksiya bo'lsa ham eslatma
                        await bot.send_message(
                            user_id,
                            "💡 Esingizdan birortasi chiqib qolmadimi?\n\n"
                            "Agar qo'shgan bo'lsangiz, ularni hozir ayting, men yozib qo'yaman 😊"
                        )
                    
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    logging.error(f"Error sending daily reminder to user {user_id}: {e}")
                    continue
                    
        except Exception as e:
            logging.error(f"Error in daily reminder task: {e}")
            await asyncio.sleep(3600)

async def send_daily_analysis_midnight():
    """Har kuni 00:00 da kun tahlili yuborish"""
    while True:
        try:
            from datetime import datetime
            now = datetime.now()
            
            # 00:00 da ishlash
            target_hour = 0
            target_minute = 0
            
            # Keyingi 00:00 ni hisoblash
            next_run = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
            if now.hour >= target_hour or (now.hour == target_hour and now.minute >= target_minute):
                next_run += timedelta(days=1)
            
            # Keyingi ishlash vaqtigacha kutish
            wait_seconds = (next_run - now).total_seconds()
            await asyncio.sleep(wait_seconds)
            
            # Barcha aktiv userlarni olish
            active_users = await db.execute_query("""
                SELECT DISTINCT user_id FROM users 
                WHERE tariff NOT IN ('NONE', 'FREE', NULL)
                OR user_id IN (
                    SELECT user_id FROM user_subscriptions 
                    WHERE is_active = TRUE AND expires_at > NOW()
                )
                OR user_id IN (
                    SELECT user_id FROM plus_package_purchases 
                    WHERE status = 'active' 
                    AND (text_used < text_limit OR voice_used < voice_limit)
                )
            """)
            
            for user_row in active_users:
                try:
                    user_id = user_row[0] if isinstance(user_row, tuple) else user_row.get('user_id')
                    if not user_id:
                        continue
                    
                    # O'tgan kun (00:00 da ishlaydi, demak o'tgan kun) tranzaksiyalarni olish
                    now = datetime.now()
                    yesterday = (now - timedelta(days=1)).date()
                    
                    # O'tgan kun statistikasi
                    yesterday_stats = await db.execute_one("""
                        SELECT 
                            COUNT(*) as count,
                            SUM(CASE WHEN transaction_type = 'income' THEN amount ELSE 0 END) as income,
                            SUM(CASE WHEN transaction_type = 'expense' THEN amount ELSE 0 END) as expense,
                            SUM(CASE WHEN transaction_type = 'debt' THEN amount ELSE 0 END) as debt
                        FROM transactions 
                        WHERE user_id = %s AND DATE(created_at) = %s
                    """, (user_id, yesterday))
                    
                    if not yesterday_stats or yesterday_stats.get('count', 0) == 0:
                        # Hech nima bo'lmagan bo'lsa, yuborilmaydi
                        continue
                    
                    tx_count = yesterday_stats.get('count', 0) if yesterday_stats.get('count') else 0
                    income = float(yesterday_stats.get('income', 0)) if yesterday_stats.get('income') else 0
                    expense = float(yesterday_stats.get('expense', 0)) if yesterday_stats.get('expense') else 0
                    debt = float(yesterday_stats.get('debt', 0)) if yesterday_stats.get('debt') else 0
                    
                    # Qarzlar (debt_reminders jadvalidan)
                    debts_info = await db.execute_query("""
                        SELECT 
                            SUM(CASE WHEN debt_direction = 'lent' THEN amount ELSE 0 END) as lent,
                            SUM(CASE WHEN debt_direction = 'borrowed' THEN amount ELSE 0 END) as borrowed
                        FROM transactions 
                        WHERE user_id = %s AND transaction_type = 'debt' AND DATE(created_at) = %s
                    """, (user_id, yesterday))
                    
                    lent = float(debts_info[0].get('lent', 0)) if debts_info and debts_info[0].get('lent') else 0
                    borrowed = float(debts_info[0].get('borrowed', 0)) if debts_info and debts_info[0].get('borrowed') else 0
                    
                    # Kategoriyalar bo'yicha xarajatlar (keraksiz xarajatlarni aniqlash uchun)
                    category_expenses = await db.execute_query("""
                        SELECT category, SUM(amount) as total, COUNT(*) as count
                        FROM transactions
                        WHERE user_id = %s AND transaction_type = 'expense' AND DATE(created_at) = %s
                        GROUP BY category
                        ORDER BY total DESC
                    """, (user_id, yesterday))
                    
                    # Tahlil xabari
                    analysis = f"📊 **Kun tahlili** ({yesterday.strftime('%d.%m.%Y')})\n\n"
                    analysis += f"📈 Tranzaksiyalar: {tx_count} ta\n"
                    analysis += f"💰 Kirimlar: {income:,.0f} so'm\n"
                    analysis += f"💸 Chiqimlar: {expense:,.0f} so'm\n"
                    analysis += f"📊 Qoldiq: {income - expense:,.0f} so'm\n"
                    
                    if lent > 0 or borrowed > 0:
                        analysis += f"\n💳 Qarzlar:\n"
                        if lent > 0:
                            analysis += f"  • Berilgan: {lent:,.0f} so'm\n"
                        if borrowed > 0:
                            analysis += f"  • Olingan: {borrowed:,.0f} so'm\n"
                    
                    # AI tahlil
                    try:
                        # Keraksiz xarajatlarni aniqlash
                        unnecessary_categories = []
                        if category_expenses:
                            for cat_row in category_expenses:
                                cat_name = cat_row.get('category')
                                cat_total = float(cat_row.get('total', 0))
                                cat_count = int(cat_row.get('count', 0))
                                
                                # Agar bir kategoriyada ko'p marta yoki katta summa bo'lsa
                                if cat_count >= 3 or cat_total > expense * 0.3:  # 30% dan ko'p
                                    unnecessary_categories.append(f"{cat_name} ({cat_count} marta, {cat_total:,.0f} so'm)")
                        
                        # AI prompt
                        ai_prompt = f"Kun tahlili:\n"
                        ai_prompt += f"Tranzaksiyalar: {tx_count} ta\n"
                        ai_prompt += f"Kirim: {income:,.0f} so'm\n"
                        ai_prompt += f"Chiqim: {expense:,.0f} so'm\n"
                        if unnecessary_categories:
                            ai_prompt += f"Keraksiz xarajatlar: {', '.join(unnecessary_categories)}\n"
                        ai_prompt += f"\nQisqa tahlil qiling va keraksiz xarajatlar bo'lsa, ularni aytib, tejash tavsiyalari bering (max 3 gap)."
                        
                        ai_response = await ai_chat.generate_response(user_id, ai_prompt)
                        if ai_response and len(ai_response) > 0:
                            analysis += f"\n🤖 **AI Tahlili:**\n{ai_response[0]}"
                    except Exception as e:
                        logging.error(f"Error generating AI analysis for user {user_id}: {e}")
                    
                    await bot.send_message(user_id, analysis, parse_mode='Markdown')
                    
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    logging.error(f"Error sending daily analysis to user {user_id}: {e}")
                    continue
                    
        except Exception as e:
            logging.error(f"Error in daily analysis task: {e}")
            await asyncio.sleep(3600)

async def main():
    """Asosiy dastur - bot va background tasklarni ishga tushirish"""
    try:
        print("🚀 Bot ishga tushmoqda...")
        
        # Avval database pool yaratish
        print("📊 Ma'lumotlar bazasini ulash...")
        await db.create_pool()
        print("✅ Ma'lumotlar bazasi ulandi!")
        
        print("📋 Jadvallarni yaratish...")
        await db.create_tables()
        print("✅ Jadvallar yaratildi!")
        
        # Business modulga OpenAI client ulash
        print("🤖 Business AI parser sozlanmoqda...")
        business_module.set_openai_client(ai_chat.openai_client)
        print("✅ Business AI parser sozlandi!")
        
        print("⚙️ Sozlamalarni yuklash...")
        await load_config_from_db()
        print("✅ Sozlamalar bazadan yuklandi!")
        
        # Database pool yaratilgandan keyin background tasklarni ishga tushirish
        asyncio.create_task(send_daily_reports())  # Pro userlar uchun kechki 21:00
        asyncio.create_task(send_reminders())  # Eslatmalar 09:00
        asyncio.create_task(send_daily_reminder_9am())  # Har kuni 9:00 da tranzaksiya eslatmasi
        asyncio.create_task(send_daily_analysis_midnight())  # Har kuni 00:00 da kun tahlili
        
        # Botni ishga tushirish (blocking)
        print("🤖 Bot polling ni boshlash...")
        await dp.start_polling(bot)
    except Exception as e:
        print(f"❌ Bot ishga tushishda xatolik: {e}")
        logging.error(f"Bot startup xatolik: {e}")
    finally:
        if hasattr(bot, 'session'):
            await bot.session.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Botni ishga tushirish
    asyncio.run(main())