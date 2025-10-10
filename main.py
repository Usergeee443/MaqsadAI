#!/usr/bin/env python3
"""
Balans AI Bot - Moliyaviy yordamchi
Faqat moliyaviy funksiyalar
"""

import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, Contact, WebAppInfo
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, TARIFFS, CATEGORIES, TARIFF_PRICES, DISCOUNT_RATES, PAYMENT_METHODS, TELEGRAM_PAYMENT_PROVIDER_TOKEN
from database import db
from financial_module import FinancialModule
from reports_module import ReportsModule

# Bot va dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Modullar
financial_module = FinancialModule()
reports_module = ReportsModule()

PREMIUM_TARIFFS = {
    'PLUS', 'MAX', 'FAMILY', 'FAMILY_PLUS', 'FAMILY_MAX',
    'BUSINESS', 'BUSINESS_PLUS', 'BUSINESS_MAX', 'PREMIUM'
}

# To'lov jarayonida ikki marta invoice yuborilishini bloklash uchun oddiy in-memory holat
from time import time as _now
PENDING_PLUS_PAYMENTS = {}      # user_id -> ts
PENDING_BUSINESS_PAYMENTS = {}  # user_id -> ts
LAST_INVOICE_MESSAGE_ID = {}   # user_id -> message_id (oxirgi yuborilgan invoice)

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

# Tarif muddatini tekshirish va avtomatik Freega o‘tkazish
async def ensure_tariff_valid(user_id: int) -> None:
    try:
        user_data = await db.get_user_data(user_id)
        if not user_data:
            return
        current = user_data.get('tariff', 'FREE')
        expires = user_data.get('tariff_expires_at')
        if current != 'FREE' and expires:
            # Agar muddat tugagan bo‘lsa, FREE ga o‘tkazamiz
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
                    "UPDATE users SET tariff = 'FREE', tariff_expires_at = NULL WHERE user_id = %s",
                    (user_id,)
                )
    except Exception as _e:
        logging.error(f"ensure_tariff_valid error: {_e}")

async def is_paid_active(user_id: int) -> bool:
    """Foydalanuvchi pullik tarifda va muddati tugamaganmi?"""
    try:
        user_data = await db.get_user_data(user_id)
        if not user_data:
            return False
        current = user_data.get('tariff', 'FREE')
        if current == 'FREE':
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
        "Zo‘r yo‘nalishda ketyapsiz, xo‘jayin!\n\n"
        "Balans AI sizga mos keladigan turli xil tariflarni taklif etadi. "
        "Shaxsiy byudjetingizni nazorat qilmoqchimisiz, oilaviy xarajatlarni boshqarmoqchimisiz yoki "
        "biznesingizni avtomatlashtirmoqchimisiz — bu yerda albatta sizga mos yechim bor.\n\n"
        "Quyidagi bo‘limlardan birini tanlang va imkoniyatlar bilan tanishing:\n"
        "• Bepul — yoshlar yoki test qilishni xohlovchilar uchun\n"
        "• Plus — AI yordamida shaxsiy boshqaruv\n"
        "• Max — ko‘p tranzaksiyali foydalanuvchilar uchun\n"
        "• Oila tariflari — butun oila uchun maxsus imkoniyatlar\n"
        "• Biznes tariflari — kichik va yirik bizneslar uchun yechimlar"
    )

def build_tariff_detail_keyboard(tariff_code: str, back_callback: str) -> InlineKeyboardMarkup:
    async def keyboard_for_user(user_id: int) -> InlineKeyboardMarkup:
        current = await get_user_tariff(user_id)
        if current == tariff_code and current != 'FREE':
            # Aktiv tarif: faqat orqaga tugmasi
            return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back_callback)]])
        # Aks holda aktivlashtirish ko'rsatiladi
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back_callback), InlineKeyboardButton(text="🚀 Aktivlashtirish", callback_data=f"activate_{tariff_code}")]])

    # Fallback sync qurilishi (agar user_id konteksti yo'q bo'lsa)
    # FREE uchun Aktivlashtirish ko'rsatmaslik siyosati pullikdan FREEga qaytishni cheklamaydi,
    # lekin bu sinxron qurilishdan odatda foydalanmaymiz.
    if tariff_code == 'FREE':
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back_callback)]])
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back_callback), InlineKeyboardButton(text="🚀 Aktivlashtirish", callback_data=f"activate_{tariff_code}")]])

def build_main_tariff_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🆓 Bepul", callback_data="tariff_FREE"),
            InlineKeyboardButton(text="✨ Plus", callback_data="tariff_PLUS"),
            InlineKeyboardButton(text="💎 Max", callback_data="tariff_MAX")
        ],
        [InlineKeyboardButton(text="👨‍👩‍👧‍👦 Oila tariflari", callback_data="tariff_FAMILY_MENU")],
        [InlineKeyboardButton(text="🏢 Biznes tariflari", callback_data="tariff_BUSINESS_MENU")]
    ])

def get_family_tariff_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨‍👩‍👧‍👦 Oila", callback_data="tariff_FAMILY")],
        [InlineKeyboardButton(text="👪 Oila Plus", callback_data="tariff_FAMILY_PLUS")],
        [InlineKeyboardButton(text="🏡 Oila Max", callback_data="tariff_FAMILY_MAX")],
        [InlineKeyboardButton(text="⬅️ Asosiy tariflar", callback_data="tariff_BACK_MAIN")]
    ])

def get_business_tariff_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏢 Biznes", callback_data="tariff_BUSINESS")],
        [InlineKeyboardButton(text="🏬 Biznes Plus (tez orada)", callback_data="tariff_BUSINESS_PLUS_INFO")],
        [InlineKeyboardButton(text="🏦 Biznes Max (tez orada)", callback_data="tariff_BUSINESS_MAX_INFO")],
        [InlineKeyboardButton(text="⬅️ Asosiy tariflar", callback_data="tariff_BACK_MAIN")]
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
            "✨ **Plus tarif**\n\n"
            "Tarif nomi va narxi: Plus — 29 990 so'm/oy\n\n"
            "Funksiyalar:\n"
            "• AI yordamida ovozli va matnli kiritish\n"
            "• Tezkor moliyaviy tahlillar\n"
            "• Shaxsiy byudjetni kuzatish\n\n"
            "Kim uchun: 5–10 mln so'm aylanmaga ega foydalanuvchilar"
        )
    if tariff_code == "MAX":
        return (
            "💎 **Max tarif**\n\n"
            "Tarif nomi va narxi: Max — 49 990 so'm/oy\n\n"
            "Funksiyalar:\n"
            "• Cheksiz tranzaksiyalar\n"
            "• Premium AI tahlillari\n"
            "• Kengaytirilgan hisobotlar\n\n"
            "Kim uchun: katta oila yoki yuqori daromad/harajatga ega foydalanuvchilar"
        )
    if tariff_code == "FAMILY":
        return (
            "👨‍👩‍👧‍👦 **Family tarif**\n\n"
            "Tarif nomi va narxi: Family — 99 990 so'm/oy\n\n"
            "Funksiyalar:\n"
            "• Oila bo'lib foydalanish (ota-ona + bolalar)\n"
            "• Ota-onalar bolalarning xarajatlarini ko'ra oladi\n"
            "• Oila byudjetini yagona joyda boshqarish"
        )
    if tariff_code == "FAMILY_PLUS":
        return (
            "👪 **Family Plus tarif**\n\n"
            "Tarif nomi va narxi: Family Plus — 179 990 so'm/oy\n\n"
            "Funksiyalar:\n"
            "• Family'dagi barcha imkoniyatlar\n"
            "• Ko'proq a'zolarni qo'shish\n"
            "• Katta oilalar uchun kengaytirilgan imkoniyatlar"
        )
    if tariff_code == "FAMILY_MAX":
        return (
            "🏡 **Family Max tarif**\n\n"
            "Tarif nomi va narxi: Family Max — 249 990 so'm/oy\n\n"
            "Funksiyalar:\n"
            "• Family Plus'dagi barcha imkoniyatlar\n"
            "• Cheksiz oila a'zolarini qo'shish\n"
            "• Mukammal AI yordamchi"
        )
    if tariff_code == "BUSINESS":
        return (
            "🏢 **Business tarif**\n\n"
            "Tarif nomi va narxi: Business — 99 990 so'm/oy\n\n"
            "Funksiyalar:\n"
            "• Kichik biznes uchun\n"
            "• 1 boshliq + 1 xodim\n"
            "• Moliyaviy boshqaruvni avtomatlashtirish"
        )
    if tariff_code == "BUSINESS_PLUS":
        return (
            "🏬 **Business Plus tarif**\n\n"
            "Tarif nomi va narxi: Business Plus — 249 990 so'm/oy\n\n"
            "Funksiyalar:\n"
            "• Filiallarni qo'shish imkoniyati\n"
            "• Juda ko'p xodim qo'shish\n"
            "• Kengaytirilgan boshqaruv funksiyalari"
        )
    if tariff_code == "BUSINESS_MAX":
        return (
            "🏦 **Business Max tarif**\n\n"
            "Tarif nomi va narxi: Business Max — 499 990 so'm/oy\n\n"
            "Funksiyalar:\n"
            "• Business Plus'dagi barcha imkoniyatlar\n"
            "• Cheksiz xodim va filial\n"
            "• To'liq AI tahlil va prognozlar"
        )
    return f"❌ Tarif '{tariff_code}' topilmadi"

# Foydalanuvchi holatlari
class UserStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_name = State()
    waiting_for_source = State()
    waiting_for_tariff = State()
    waiting_for_amount = State()
    waiting_for_description = State()
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

# Bepul tarif menyusi
def get_free_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Kirim"), KeyboardButton(text="➖ Chiqim")],
            [KeyboardButton(text="💳 Qarzlar"), KeyboardButton(text="📊 Hisobotlar")],
            [KeyboardButton(text="💰 Balans")],
            [KeyboardButton(text="👤 Profil")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

# Premium tarif menyusi
def get_premium_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Hisobotlar", web_app=WebAppInfo(url="https://pulbot-mini-app.onrender.com/")), KeyboardButton(text="👤 Profil")],
            [KeyboardButton(text="💰 Balans")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

# Business menyusi
def get_business_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Xodim qo'shish"), KeyboardButton(text="💳 Qarzlar")],
            [KeyboardButton(text="📊 Hisobotlar", web_app=WebAppInfo(url="https://pulbot-mini-app.onrender.com/"))],
            [KeyboardButton(text="💰 Balans"), KeyboardButton(text="👤 Profil")]
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
def get_profile_menu():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data="settings")],
            [InlineKeyboardButton(text="💳 Tarif", callback_data="tariff_info")],
            [InlineKeyboardButton(text="🔄 Tarifni o'zgartirish", callback_data="switch_tariff")]
        ]
    )
    return keyboard

# Sozlamalar menyusi
def get_settings_menu():
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
            [InlineKeyboardButton(text="📱 Telegram", callback_data="source_telegram")],
            [InlineKeyboardButton(text="📷 Instagram", callback_data="source_instagram")],
            [InlineKeyboardButton(text="📺 YouTube", callback_data="source_youtube")],
            [InlineKeyboardButton(text="👥 Tanishimdan eshitdim", callback_data="source_friend")]
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
        return await db.get_active_tariff(user_id)
    except:
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
        [InlineKeyboardButton(text="1 oy", callback_data="duration_1")],
        [InlineKeyboardButton(text="2 oy (5% chegirma)", callback_data="duration_2")],
        [InlineKeyboardButton(text="3 oy (10% chegirma)", callback_data="duration_3")],
        [InlineKeyboardButton(text="6 oy (15% chegirma)", callback_data="duration_6")],
        [InlineKeyboardButton(text="12 oy (25% chegirma)", callback_data="duration_12")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_tariff_selection")]
    ])
    return keyboard

def get_payment_method_keyboard() -> InlineKeyboardMarkup:
    """To'lov usuli tanlash tugmalari"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Telegram (Click)", callback_data="payment_telegram_click")],
        [InlineKeyboardButton(text="🔵 Click", callback_data="payment_click")],
        [InlineKeyboardButton(text="🟢 Payme", callback_data="payment_payme")],
        [InlineKeyboardButton(text="🟡 Uzum Pay", callback_data="payment_uzum_pay")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_duration_selection")]
    ])
    return keyboard

async def get_user_name(user_id: int) -> str:
    """Foydalanuvchi ismini olish"""
    try:
        query = "SELECT name FROM users WHERE user_id = %s"
        result = await db.execute_one(query, (user_id,))
        return result[0] if result else "Xojayin"
    except:
        return "Xojayin"

# Start komandasi
@dp.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext):
    """Start komandasi"""
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    
    # Foydalanuvchini ma'lumotlar bazasiga qo'shish
    try:
        await db.execute_query(
            "INSERT INTO users (user_id, username, first_name, last_name, tariff, name) VALUES (%s, %s, %s, %s, 'FREE', 'Xojayin') ON DUPLICATE KEY UPDATE username = %s, first_name = %s, last_name = %s",
            (user_id, username, first_name, last_name, username, first_name, last_name)
        )
    except Exception as e:
        logging.error(f"Foydalanuvchi qo'shishda xatolik: {e}")
    
    # Foydalanuvchi yangi yoki eski ekanligini tekshirish
    user_data = await db.get_user_data(user_id)
    if user_data and user_data.get('phone') and (await state.get_state()) != UserStates.waiting_for_tariff.state:
        # Eski foydalanuvchi - asosiy menyuni ko'rsatish
        user_tariff = await get_user_tariff(user_id)
        user_name = await get_user_name(user_id)
        
        if user_tariff == "FREE":
            await message.answer(
                f"👋 Salom, {user_name}!\n\n"
                "Balans AI ga xush kelibsiz!\n\n"
                "Quyidagi tugmalardan foydalaning:",
                reply_markup=get_free_menu(),
                parse_mode="Markdown"
            )
        elif user_tariff == "BUSINESS":
            await message.answer(
                f"👋 Salom, {user_name}!\n\n"
                "Balans AI Business ga xush kelibsiz!\n\n"
                "Matn yoki ovozli xabar yuboring va AI avtomatik qayta ishlaydi:",
                reply_markup=get_business_menu(),
                parse_mode="Markdown"
            )
        else:
            await message.answer(
                f"👋 Salom, {user_name}!\n\n"
                "Balans AI ga xush kelibsiz!\n\n"
                "Matn yoki ovozli xabar yuboring va AI avtomatik qayta ishlaydi:",
                reply_markup=get_premium_menu(),
                parse_mode="Markdown"
            )
    else:
        # Yangi foydalanuvchi - onboarding
        # Yangi foydalanuvchi uchun xush kelibsiz xabari
        await message.answer(
            "👋 Salom, men – Balans AI.\n\n"
            "💼 Shaxsiy moliyaviy yordamchingiz:\n"
            "• Kirim-chiqimlaringizni avtomatik tahlil qilaman\n"
            "• Xarajatlaringizni aniq toifalarga ajrataman\n"
            "• Moliyaviy nazorat va tejamkorlikni shakllantiraman\n\n"
            "⚡ Bepul va Premium tariflar mavjud\n"
            "🌟 Premium foydalanuvchilar uchun cheklanmagan imkoniyatlar va shaxsiy maslahatlar\n"
            "…va buning ustiga yana ko'plab maxsus funksiyalar mavjud, faqat bot ichida ochiladi.\n\n"
            "⏩ Boshlash uchun pastdagi tugma orqali telefon raqamingizni yuboring.",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)]],
                resize_keyboard=True
            ),
            parse_mode="Markdown"
        )
        await state.set_state(UserStates.waiting_for_phone)
        return

    # Agar foydalanuvchi telefon bergan bo'lsa-yu, hali tarif tanlamagan bo'lsa, tarif menyusiga yo'naltiramiz
    if (await state.get_state()) == UserStates.waiting_for_tariff.state:
        await message.answer(
            get_tariff_overview_text(),
            reply_markup=build_main_tariff_keyboard()
        )
        return

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
    
    await message.answer(
        "✅ *Telefon raqam qabul qilindi!*\n\n"
        "Sizni nima deb chaqiray? (Ismingizni kiriting yoki 'Xojayin' deb chaqishim mumkin)",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Xojayin deb chaqir")]],
            resize_keyboard=True
        ),
        parse_mode="Markdown"
    )
    await state.set_state(UserStates.waiting_for_name)

# Ism qabul qilish
@dp.message(UserStates.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    """Ismni qabul qilish"""
    user_id = message.from_user.id
    name = message.text.strip()
    
    if not name or name.lower() in ['skip', 'otkazib yuborish', 'otkazib', ''] or name == "Xojayin deb chaqir":
        name = "Xojayin"
    
    # Ismni saqlash
    await db.execute_query(
        "UPDATE users SET name = %s WHERE user_id = %s",
        (name, user_id)
    )
    
    await message.answer(
        f"✅ *Ism saqlandi: {name}*\n\n"
        "Bizni qayerda eshitdingiz?",
        reply_markup=get_source_menu(),
        parse_mode="Markdown"
    )
    await state.set_state(UserStates.waiting_for_source)

# Manba tanlash
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
    
    # Foydalanuvchi ismini olish
    user_data = await db.get_user_data(user_id)
    user_name = user_data.get('name', 'Xojayin')
    
    await callback_query.message.edit_text(
        f"✅ Raxmat {user_name}\n\n"
        "Endi tarifini tanlang:",
        reply_markup=get_tariff_menu(),
        parse_mode="Markdown"
    )
    await state.set_state(UserStates.waiting_for_tariff)


# Help komandasi
@dp.message(Command("help"))
async def help_command(message: types.Message):
    """Yordam komandasi"""
    help_text = """
🤖 *Balans AI - Moliyaviy yordamchi*

📊 *Asosiy funksiyalar:*
• Moliyaviy ma'lumotlarni kiritish
• Hisobotlar va tahlillar
• AI yordamchi maslahatlari (Premium)

💰 *Moliyaviy ma'lumotlar:*
• Bepul: Qo'lda kiritish
• Premium: AI yordamida avtomatik

📊 *Hisobotlar:*
• Balans ma'lumotlari
• Kategoriyalar bo'yicha tahlil
• Oylik tendensiya
• So'nggi tranzaksiyalar

*Buyruqlar:*
/start - Botni qayta ishga tushirish
/help - Yordam
    """
    await message.answer(help_text, parse_mode="Markdown")

# Tezkor balans komandasi va tugma handleri
@dp.message(Command("balans"))
@dp.message(lambda message: message.text == "💰 Balans")
async def quick_balance(message: types.Message):
    user_id = message.from_user.id
    balances = await db.get_balances(user_id)
    text = (
        "💰 *Tezkor balans*\n\n"
        f"Naqd balans: {balances['cash_balance']:,.0f} so'm\n"
        f"Sof balans: {balances['net_balance']:,.0f} so'm\n"
        f"Jami kirim: {balances['income']:,.0f} so'm\n"
        f"Jami chiqim: {balances['expense']:,.0f} so'm\n"
        f"Olingan qarz: {balances['borrowed']:,.0f} so'm\n"
        f"Berilgan qarz: {balances['lent']:,.0f} so'm"
    )
    await message.answer(text, parse_mode='Markdown')

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

# Bepul tarif - Qarz qo'shish
@dp.message(lambda message: message.text == "💳 Qarzlar")
async def add_debt(message: types.Message, state: FSMContext):
    """Qarz qo'shish"""
    user_tariff = await get_user_tariff(message.from_user.id)
    if user_tariff != "FREE":
        return
    
    await message.answer(
        "💳 *Qarz qo'shish*\n\n"
        "Qarz olingan yoki berilgan?",
        reply_markup=get_debt_type_menu(),
        parse_mode="Markdown"
    )
    await state.set_state(UserStates.waiting_for_debt_type)

# Qarz turini qabul qilish
@dp.callback_query(UserStates.waiting_for_debt_type, lambda c: c.data.startswith("debt_type_"))
async def process_debt_type(callback_query: CallbackQuery, state: FSMContext):
    """Qarz turini qabul qilish"""
    debt_type = callback_query.data.replace("debt_type_", "")
    
    # Qarz turini saqlash
    await state.update_data(debt_type=debt_type)
    
    if debt_type == "lent":  # Qarz berish
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

# Bekor qilish funksiyasi
@dp.message(lambda message: message.text == "❌ Bekor qilish")
async def cancel_operation(message: types.Message, state: FSMContext):
    """Amalni bekor qilish"""
    user_tariff = await get_user_tariff(message.from_user.id)
    
    await message.answer(
        "❌ *Amal bekor qilindi*\n\n"
        "Asosiy menyuga qaytildi.",
        reply_markup=get_free_menu() if user_tariff == "FREE" else get_premium_menu(),
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
        
        await state.update_data(amount=amount)
        data = await state.get_data()
        transaction_type = data.get('transaction_type')
        
        if transaction_type == "income":
            await message.answer(
                "📝 *Tavsif kiriting (ixtiyoriy):*",
                reply_markup=ReplyKeyboardMarkup(keyboard=[], resize_keyboard=True),
                parse_mode="Markdown"
            )
            await state.set_state(UserStates.waiting_for_description)
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

# Tavsif qabul qilish (faqat kirim uchun)
@dp.message(UserStates.waiting_for_description)
async def process_description(message: types.Message, state: FSMContext):
    """Tavsifni qabul qilish"""
    description = message.text.strip()
    await state.update_data(description=description)
    
    # Agar bu qarz emas — income oqimi: to'g'ridan-to'g'ri kategoriya
    data = await state.get_data()
    if data.get('transaction_type') == 'debt':
        await message.answer(
            "📅 Qachon qaytariladi? Sana formatida kiriting (YYYY-MM-DD) yoki 'skip' deb yozing:",
            reply_markup=get_cancel_keyboard(),
            parse_mode='Markdown'
        )
        await state.set_state(UserStates.waiting_for_debt_due_date)
    else:
        await message.answer(
            "📂 *Kategoriyani tanlang:*",
            reply_markup=get_income_category_menu(),
            parse_mode="Markdown"
        )
        await state.set_state(UserStates.waiting_for_category)

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
    
    # Qarzlar uchun transaction_type ni to'g'ri o'rnatish
    if not transaction_type:
        transaction_type = "debt"  # Default qarz
    
    # Tranzaksiyani saqlashdan oldin: chiqim uchun naqd balans tekshirish
    try:
        if transaction_type == 'expense':
            balances = await db.get_balances(user_id)
            if balances['cash_balance'] <= 0 or amount > balances['cash_balance']:
                await callback_query.answer("❌ Naqd balans yetarli emas. Avval kirim yoki qarz olish kiritib keyin chiqim kiriting.", show_alert=True)
                await state.clear()
                return
        due_date = data.get('due_date') if transaction_type == 'debt' else None
        debt_type = data.get('debt_type') if transaction_type == 'debt' else None
        insert_id = await db.execute_insert(
            "INSERT INTO transactions (user_id, transaction_type, amount, category, description, due_date, debt_direction) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (user_id, transaction_type, amount, category, description, due_date, debt_type)
        )
        
        type_emoji = {"income": "📈", "expense": "📉", "debt": "💳"}.get(transaction_type, "❓")
        type_name = {"income": "Kirim", "expense": "Chiqim", "debt": "Qarz"}.get(transaction_type, "Tranzaksiya")
        
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
            f"{type_emoji} {amount:,.0f} so'm\n"
            f"{debt_type_text}"
            f"📂 {category}\n"
            f"📝 {description if description else 'Tavsif yoq'}\n\n"
            "Boshqa amal bajarish uchun menyudan foydalaning:",
            parse_mode="Markdown"
        )
        # Qarzdorlik uchun eslatma yozuvi
        if transaction_type == 'debt' and due_date:
            try:
                await db.execute_insert(
                    "INSERT INTO debt_reminders (user_id, transaction_id, reminder_date) VALUES (%s, %s, %s)",
                    (user_id, insert_id, due_date)
                )
            except Exception as e:
                logging.error(f"Qarz eslatmasi yaratishda xatolik: {e}")
        await callback_query.message.answer(
            "Bepul tarif menyusi:",
            reply_markup=get_free_menu()
        )
        
    except Exception as e:
        logging.error(f"Tranzaksiya saqlashda xatolik: {e}")
        await callback_query.message.edit_text(
            "❌ Xatolik yuz berdi! Qaytadan urinib ko'ring.",
            parse_mode="Markdown"
        )
        await callback_query.message.answer(
            "Bepul tarif menyusi:",
            reply_markup=get_free_menu()
        )
    
    await state.clear()

# Hisobotlar menyusi
@dp.message(lambda message: message.text == "📊 Hisobotlar")
async def reports_menu(message: types.Message, state: FSMContext):
    """Hisobotlar menyusi"""
    user_id = message.from_user.id
    user_tariff = await get_user_tariff(user_id)
    
    # Faqat PRO va MAX tariflar uchun kengaytirilgan hisobot
    if user_tariff not in ['PRO', 'MAX', 'PREMIUM']:
        # Oddiy hisobot
        summary = await reports_module.get_financial_summary(user_id)
        balance = await reports_module.get_balance_report(user_id)
        
        message_text = f"{summary}\n\n"
        message_text += f"💰 *Balans:* {balance['balance']:,.0f} so'm\n"
        message_text += f"📈 *Kirim:* {balance['income']:,.0f} so'm\n"
        message_text += f"📉 *Chiqim:* {balance['expense']:,.0f} so'm\n\n"
        message_text += "📱 *Kengaytirilgan hisobotlar*\n"
        message_text += "Premium tarifga o'ting!\n"
        message_text += "Profil > Tarif bo'limiga o'ting."
        
        await message.answer(
            message_text,
            reply_markup=get_free_menu() if user_tariff == "FREE" else get_premium_menu()
        )
        return
    
    # Kengaytirilgan hisobot ko'rsatish
    summary = await reports_module.get_financial_summary(user_id)
    balance = await reports_module.get_balance_report(user_id)
    categories = await reports_module.get_category_report(user_id, 30)
    
    message_text = f"{summary}\n\n"
    message_text += f"💰 *Balans:* {balance['balance']:,.0f} so'm\n"
    message_text += f"📈 *Kirim:* {balance['income']:,.0f} so'm\n"
    message_text += f"📉 *Chiqim:* {balance['expense']:,.0f} so'm\n\n"
    
    # Eng ko'p chiqim kategoriyasi
    if categories['expense_categories']:
        top_category = max(categories['expense_categories'].items(), key=lambda x: x[1]['total'])
        message_text += f"🔥 *Eng ko'p chiqim:* {top_category[0]} ({top_category[1]['total']:,.0f} so'm)\n\n"
    
    # So'nggi tranzaksiyalar
    recent = await reports_module.get_recent_transactions(user_id, 10)
    if recent:
        message_text += "📋 *So'nggi tranzaksiyalar:*\n"
        for i, trans in enumerate(recent, 1):
            type_emoji = {"income": "📈", "expense": "📉", "debt": "💳"}.get(trans["type"], "❓")
            message_text += f"{i}. {type_emoji} {trans['amount']:,.0f} so'm - {trans['category']}\n"
            if trans.get('description'):
                message_text += f"   💬 {trans['description']}\n"
    
    # Kategoriyalar bo'yicha tafsilot
    if categories['expense_categories']:
        message_text += "\n📊 *Chiqimlar kategoriyalar bo'yicha:*\n"
        for category, data in sorted(categories['expense_categories'].items(), key=lambda x: x[1]['total'], reverse=True):
            percentage = (data['total'] / balance['expense'] * 100) if balance['expense'] > 0 else 0
            message_text += f"• {category}: {data['total']:,.0f} so'm ({percentage:.1f}%)\n"
    
    # Oylik tendensiya
    monthly_data = await reports_module.get_monthly_summary(user_id, 6)
    if monthly_data:
        message_text += "\n📈 *Oylik tendensiya (6 oy):*\n"
        for month_data in monthly_data[-3:]:  # So'nggi 3 oy
            message_text += f"• {month_data['month']}: +{month_data['income']:,.0f} -{month_data['expense']:,.0f} = {month_data['balance']:,.0f}\n"
    
    await message.answer(
        message_text,
        reply_markup=get_premium_menu(),
        parse_mode="Markdown"
    )

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
    
    # Profil ma'lumotlarini tayyorlash (qisqartirilgan)
    profile_text = f"👤 **Profil**\n\n"
    profile_text += f"🆔 ID: `{user_id}`\n"
    profile_text += f"📅 Ro'yxat: {user_data['created_at'].strftime('%d.%m.%Y')}\n"
    profile_text += f"👤 Ism: {user_data.get('name', 'Nomalum')}\n"
    if user_data.get('phone'):
        profile_text += f"📱 Tel: {user_data['phone']}\n\n"
    
    # Aktiv tarif
    profile_text += f"🎯 **Aktiv tarif:** {TARIFFS.get(user_tariff, 'Nomalum')}\n"
    
    # Barcha tariflar
    if all_subscriptions:
        profile_text += f"\n📋 **Sotib olingan tariflar:**\n"
        for sub in all_subscriptions:
            tariff_name = TARIFFS.get(sub[0], sub[0])
            status = "🟢 Aktiv" if sub[1] else "⚪ Mavjud"
            expires = sub[2].strftime('%d.%m.%Y') if sub[2] else "Cheksiz"
            profile_text += f"• {tariff_name} - {status} (tugash: {expires})\n"
    
    # Agar pullik tarif bo'lsa, muddatini ko'rsatish
    if user_tariff in ['PRO', 'MAX', 'PREMIUM', 'PLUS', 'BUSINESS'] and user_data.get('tariff_expires_at'):
        profile_text += f"\n⏰ **Aktiv tarif muddati:** {user_data['tariff_expires_at'].strftime('%d.%m.%Y %H:%M')}\n"
    elif user_tariff in ['PRO', 'MAX', 'PREMIUM']:
        profile_text += f"\n⏰ **Muddati:** Cheksiz\n"
    
    await message.answer(profile_text, reply_markup=get_profile_menu(), parse_mode='Markdown')

# Profil callback handlerlari
@dp.callback_query(lambda c: c.data == "settings")
async def settings_callback(callback_query: CallbackQuery):
    """Sozlamalar menyusini ko'rsatish"""
    text = "⚙️ **Sozlamalar**\n\nHozircha sozlamalar mavjud emas."
    keyboard = get_settings_menu()
    
    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode='Markdown')
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "back_to_profile")
async def back_to_profile_callback(callback_query: CallbackQuery):
    """Profil menyusiga qaytish"""
    user_id = callback_query.from_user.id
    user_data = await db.get_user_data(user_id)
    
    profile_text = f"👤 **Profil ma'lumotlari**\n\n"
    profile_text += f"🆔 **Telegram ID:** `{user_id}`\n"
    profile_text += f"📅 **Ro'yxatdan o'tgan sana:** {user_data['created_at'].strftime('%d.%m.%Y')}\n"
    profile_text += f"💳 **Tarif:** {TARIFFS.get(user_data['tariff'], 'Nomalum')}\n"
    profile_text += f"👤 **Ism:** {user_data.get('name', 'Nomalum')}\n"
    if user_data.get('phone'):
        profile_text += f"📱 **Telefon:** {user_data['phone']}\n"
    
    if user_data['tariff'] in ['PRO', 'MAX', 'PREMIUM'] and user_data.get('tariff_expires_at'):
        profile_text += f"⏰ **Faol bo'lish muddati:** {user_data['tariff_expires_at'].strftime('%d.%m.%Y %H:%M')}\n"
    elif user_data['tariff'] in ['PRO', 'MAX', 'PREMIUM']:
        profile_text += f"⏰ **Faol bo'lish muddati:** Cheksiz\n"
    
    keyboard = get_profile_menu()
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
    
    tariff_text = f"💳 **Tarif ma'lumotlari**\n\n"
    tariff_text += f"🎯 **Joriy aktiv tarif:** {TARIFFS.get(user_tariff, 'Nomalum')}\n"
    
    if all_subscriptions:
        tariff_text += f"\n📋 **Sotib olingan tariflar:**\n"
        for sub in all_subscriptions:
            tariff_name = TARIFFS.get(sub[0], sub[0])
            status = "🟢 Aktiv" if sub[1] else "⚪ Mavjud"
            expires = sub[2].strftime('%d.%m.%Y') if sub[2] else "Cheksiz"
            tariff_text += f"• {tariff_name} - {status} (tugash: {expires})\n"
    
    if user_tariff == "FREE":
        tariff_text += "\n🆓 **Bepul tarif imkoniyatlari:**\n"
        tariff_text += "• Asosiy moliyaviy funksiyalar\n"
        tariff_text += "• Qarzlar boshqaruvi\n"
        tariff_text += "• Balans ko'rish\n\n"
        tariff_text += "💡 **Premium tarifga o'tish uchun:**\n"
        tariff_text += "• AI yordamida avtomatik qayta ishlash\n"
        tariff_text += "• Kengaytirilgan hisobotlar\n"
        tariff_text += "• Shaxsiy maslahatlar"
    else:
        tariff_text += "\n⭐ **Premium tarif imkoniyatlari:**\n"
        tariff_text += "• AI yordamida avtomatik qayta ishlash\n"
        tariff_text += "• Kengaytirilgan hisobotlar\n"
        tariff_text += "• Shaxsiy maslahatlar\n"
        tariff_text += "• Cheksiz tranzaksiya qayta ishlash"
    
    # Yangi tarif sotib olish uchun tugma qo'shamiz
    keyboard_buttons = [
        [InlineKeyboardButton(text="🆕 Yangi tarif sotib olish", callback_data="buy_new_tariff")],
        [InlineKeyboardButton(text="🔄 Tarifni o'zgartirish", callback_data="switch_tariff")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_profile")]
    ]
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await callback_query.message.edit_text(tariff_text, reply_markup=keyboard, parse_mode='Markdown')
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "switch_tariff")
async def switch_tariff_callback(callback_query: CallbackQuery):
    """Tarifni o'zgartirish menyusini ko'rsatish"""
    user_id = callback_query.from_user.id
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
    
    keyboard_buttons.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_profile")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await callback_query.message.edit_text(
        "🔄 **Tarifni o'zgartirish**\n\n"
        "Qaysi tarifni aktiv qilmoqchisiz?",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )
    await callback_query.answer()

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
        if tariff == "FREE":
            await callback_query.message.answer("Bepul tarif menyusi:", reply_markup=get_free_menu())
        elif tariff == "BUSINESS":
            await callback_query.message.answer("Business tarif menyusi:", reply_markup=get_business_menu())
        else:
            await callback_query.message.answer("Premium tarif menyusi:", reply_markup=get_premium_menu())
            
    except Exception as e:
        logging.error(f"Tarif o'zgartirishda xatolik: {e}")
        await callback_query.answer("❌ Xatolik yuz berdi!", show_alert=True)
    
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "back_to_profile")
async def back_to_profile_callback(callback_query: CallbackQuery):
    """Profilga qaytish"""
    user_id = callback_query.from_user.id
    user_data = await db.get_user_data(user_id)
    user_tariff = await get_user_tariff(user_id)
    all_subscriptions = await get_user_all_subscriptions(user_id)
    
    profile_text = f"👤 **Profil**\n\n"
    profile_text += f"🆔 ID: `{user_id}`\n"
    profile_text += f"📅 Ro'yxat: {user_data['created_at'].strftime('%d.%m.%Y')}\n"
    profile_text += f"👤 Ism: {user_data.get('name', 'Nomalum')}\n"
    if user_data.get('phone'):
        profile_text += f"📱 Tel: {user_data['phone']}\n\n"
    
    profile_text += f"🎯 **Aktiv tarif:** {TARIFFS.get(user_tariff, 'Nomalum')}\n"
    
    if all_subscriptions:
        profile_text += f"\n📋 **Sotib olingan tariflar:**\n"
        for sub in all_subscriptions:
            tariff_name = TARIFFS.get(sub[0], sub[0])
            status = "🟢 Aktiv" if sub[1] else "⚪ Mavjud"
            expires = sub[2].strftime('%d.%m.%Y') if sub[2] else "Cheksiz"
            profile_text += f"• {tariff_name} - {status} (tugash: {expires})\n"
    
    await callback_query.message.edit_text(
        profile_text,
        reply_markup=get_profile_menu(),
        parse_mode='Markdown'
    )
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "buy_new_tariff")
async def buy_new_tariff_callback(callback_query: CallbackQuery):
    """Yangi tarif sotib olish menyusini ko'rsatish"""
    await callback_query.message.edit_text(
        get_tariff_overview_text(),
        reply_markup=build_main_tariff_keyboard()
    )
    await callback_query.answer()

# Muddat tanlash handleri
@dp.callback_query(lambda c: c.data.startswith("duration_"), UserStates.waiting_for_subscription_duration)
async def process_subscription_duration(callback_query: CallbackQuery, state: FSMContext):
    """Obuna muddatini qabul qilish"""
    user_id = callback_query.from_user.id
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
    text += f"💰 **Narx:** {price_info['final_price']:,} so'm\n"
    
    if price_info['discount_rate'] > 0:
        text += f"💸 **Chegirma:** {price_info['discount_amount']:,} so'm\n"
    
    await callback_query.message.edit_text(
        text,
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
    
    # Hozircha faqat Telegram Click qo'llab-quvvatlanadi
    if payment_method != "telegram_click":
        await callback_query.answer("🚧 Bu to'lov usuli tez orada qo'shiladi!", show_alert=True)
        return
    
    # Telegram Payments orqali to'lov
    try:
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
        
        await callback_query.message.edit_text(
            f"💳 **To'lov haqida**\n\n"
            f"📋 **Tarif:** {tariff_name}\n"
            f"⏰ **Muddat:** {months} oy\n"
            f"💰 **Jami:** {price_info['final_price']:,} so'm\n\n"
            f"To'lovni amalga oshirish uchun yuqoridagi tugmani bosing.",
            parse_mode='Markdown'
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
    await callback_query.message.edit_text(
        f"📅 **{tariff_name} tarifini tanladingiz**\n\n"
        f"Qancha oylik obuna olishni xohlaysiz?\n\n"
        f"Uzoq muddatli obunalar uchun chegirma mavjud:",
        reply_markup=get_subscription_duration_keyboard(),
        parse_mode='Markdown'
    )
    await state.set_state(UserStates.waiting_for_subscription_duration)
    await callback_query.answer()

@dp.callback_query(lambda c: not c.data.startswith("trans_"))
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
            await callback_query.message.edit_text(
                get_family_overview_text(),
                reply_markup=get_family_tariff_keyboard()
            )
            await callback_query.answer()
            return

        if code == "BUSINESS_MENU":
            await callback_query.message.edit_text(
                get_business_overview_text(),
                reply_markup=get_business_tariff_keyboard()
            )
            await callback_query.answer()
            return
        if code in ["BUSINESS_PLUS_INFO", "BUSINESS_MAX_INFO"]:
            await callback_query.answer("🚧 Tez orada: hozircha faqat ‘Biznes’ tarifini faollashtirish mumkin.", show_alert=True)
            return
        
        if code == "BACK_MAIN":
            await callback_query.message.edit_text(
                get_tariff_overview_text(),
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
        if (user_tariff == tariff_code and user_tariff != 'FREE'):
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
            await callback_query.message.edit_text(detail_text + expires_text, reply_markup=keyboard, parse_mode='Markdown')
        else:
            keyboard = build_tariff_detail_keyboard(tariff_code, back_callback)
            await callback_query.message.edit_text(detail_text, reply_markup=keyboard, parse_mode='Markdown')
        await callback_query.answer()
        return
    
    # Aktivlashtirish callbacklari
    if callback_query.data.startswith("activate_"):
        tariff_code = callback_query.data.replace("activate_", "")
        print(f"DEBUG: Activation callback received for tariff: {tariff_code}")
        
        if tariff_code == "FREE":
            print("DEBUG: Processing FREE activation")
            user_id = callback_query.from_user.id
            # Pullik aktiv obuna bo'lsa, Free'ga o'tishga ruxsat bermaymiz
            if await is_paid_active(user_id):
                await callback_query.answer("❗ Sizda aktiv pullik obuna bor. Muddat tugagach Bepulga o'tasiz.", show_alert=True)
                return
            user_name = await get_user_name(user_id)
            await db.execute_query(
                "UPDATE users SET tariff = %s WHERE user_id = %s",
                ("FREE", user_id)
            )
            await callback_query.message.edit_text(
                f"✅ *Bepul tarif aktivlashtirildi!*\n\n"
                f"Salom, {user_name}!\n\n"
                "Quyidagi tugmalardan foydalaning:",
                parse_mode="Markdown"
            )
            await callback_query.message.answer(
                "Bepul tarif menyusi:",
                reply_markup=get_free_menu()
            )
            await callback_query.answer()
            return

        if tariff_code in ("PLUS", "BUSINESS", "MAX", "FAMILY", "FAMILY_PLUS", "FAMILY_MAX", "BUSINESS_PLUS", "BUSINESS_MAX"):
            # Yangi tarif sotib olish jarayoni - muddat tanlash
            print(f"DEBUG: Processing paid tariff selection: {tariff_code}")
            user_id = callback_query.from_user.id
            
            # State ga tarifni saqlaymiz
            await state.update_data(selected_tariff=tariff_code)
            
            # Muddat tanlash menyusini ko'rsatamiz
            tariff_name = TARIFFS.get(tariff_code, tariff_code)
            await callback_query.message.edit_text(
                f"📅 **{tariff_name} tarifini tanladingiz**\n\n"
                f"Qancha oylik obuna olishni xohlaysiz?\n\n"
                f"Uzoq muddatli obunalar uchun chegirma mavjud:",
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
        # Plus tarifni aktiv qilish
        await db.execute_query(
            "UPDATE users SET tariff = %s WHERE user_id = %s",
            ("PLUS", user_id)
        )

        user_name = await get_user_name(user_id)
        await callback_query.message.edit_text(
            f"✅ *Plus tarif tanlandi!*\n\n"
            f"Salom, {user_name}!\n\n"
            "Matn yoki ovozli xabar yuboring va AI avtomatik qayta ishlaydi:",
            parse_mode="Markdown"
        )
        await callback_query.message.answer(
            "Plus tarif menyusi:",
            reply_markup=get_premium_menu()
        )

        await state.clear()
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
            current = user_data.get('tariff') if user_data else 'FREE'
            if current == tariff and current != 'FREE':
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

        keyboard = build_tariff_detail_keyboard(tariff, back_callback)
        await callback_query.message.edit_text(detail_text, reply_markup=keyboard, parse_mode='Markdown')
        await callback_query.answer()
        return

    # Faqat FREE tarifni aktiv qilish
    await db.execute_query(
        "UPDATE users SET tariff = %s WHERE user_id = %s",
        ("FREE", user_id)
    )

    user_name = await get_user_name(user_id)
    await callback_query.message.edit_text(
        f"✅ *Bepul tarif tanlandi!*\n\n"
        f"Salom, {user_name}!\n\n"
        "Quyidagi tugmalardan foydalaning:",
        parse_mode="Markdown"
    )
    await callback_query.message.answer(
        "Bepul tarif menyusi:",
        reply_markup=get_free_menu()
    )

    await state.clear()
    await callback_query.answer()

# Xodim qo'shish handler
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
    
    try:
        employee_id = int(employee_id)
    except ValueError:
        await message.answer("❌ Noto'g'ri ID! Faqat raqam kiriting.")
        return
    
    # Xodimning mavjudligini tekshirish
    employee_data = await db.get_user_data(employee_id)
    if not employee_data:
        await message.answer("❌ Bu ID da foydalanuvchi topilmadi. Xodim avval botda /start bosishi kerak.")
        return
    
    # Xodimga taklif yuborish
    try:
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
        
        username = employee_data.get('username', 'Noma\'lum')
        await message.answer(
            f"✅ Taklif yuborildi! Xodim @{username} ga xabar jo'natildi.\n"
            f"U taklifni qabul qilsa, sizning jamoangizga qo'shiladi."
        )
        
    except Exception as e:
        logging.error(f"Xodimga xabar yuborishda xatolik: {e}")
        await message.answer("❌ Xodimga xabar yuborishda xatolik yuz berdi.")
    
    await state.clear()

@dp.callback_query(lambda c: c.data.startswith("accept_employee_"))
async def accept_employee_invite(callback_query: CallbackQuery):
    """Xodim taklifini qabul qilish"""
    user_id = callback_query.from_user.id
    manager_id = int(callback_query.data.split("_")[2])
    
    try:
        # Xodimni jamoaga qo'shish (bu yerda oddiy tarifni o'zgartirish)
        await db.execute_query(
            "UPDATE users SET tariff = 'BUSINESS', manager_id = %s WHERE user_id = %s",
            (manager_id, user_id)
        )
        
        await callback_query.message.edit_text(
            "✅ *Taklif qabul qilindi!*\n\n"
            "Endi siz jamoaning bir qismisiz. Boshliq va siz tranzaksiyalar kiritishingiz mumkin.",
            parse_mode="Markdown"
        )
        
        # Boshliqga xabar yuborish
        try:
            await callback_query.bot.send_message(
                chat_id=manager_id,
                text=f"✅ @{callback_query.from_user.username} taklifingizni qabul qildi!\n"
                     f"Endi u jamoangizning bir qismi."
            )
        except Exception as e:
            logging.error(f"Boshliqga xabar yuborishda xatolik: {e}")
            
    except Exception as e:
        logging.error(f"Xodim qo'shishda xatolik: {e}")
        await callback_query.answer("❌ Xatolik yuz berdi!", show_alert=True)
    
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "reject_employee")
async def reject_employee_invite(callback_query: CallbackQuery):
    """Xodim taklifini rad etish"""
    await callback_query.message.edit_text(
        "❌ *Taklif rad etildi*",
        parse_mode="Markdown"
    )
    await callback_query.answer()

# Premium tarif - AI yordamida moliyaviy ma'lumotlarni qayta ishlash
@dp.message(lambda message: message.text and not message.text.startswith('/') and message.text not in ["📊 Hisobotlar", "👤 Profil", "➕ Kirim", "➖ Chiqim", "💳 Qarzlar", "➕ Xodim qo'shish"])
async def process_financial_message(message: types.Message, state: FSMContext):
    """Moliyaviy ma'lumotlarni qayta ishlash (Premium)"""
    user_id = message.from_user.id
    # Avtomatik tarif muddatini tekshirish
    await ensure_tariff_valid(user_id)
    user_tariff = await get_user_tariff(user_id)
    
    # Faqat Premium tarif uchun AI qayta ishlash
    if user_tariff not in PREMIUM_TARIFFS:
        return
    
    # Agar foydalanuvchi boshqa holatda bo'lsa (onboarding yoki boshqa state'lar)
    if await state.get_state() in [UserStates.waiting_for_phone, UserStates.waiting_for_name, 
                                   UserStates.waiting_for_source, UserStates.waiting_for_tariff,
                                   UserStates.waiting_for_amount, UserStates.waiting_for_description, 
                                   UserStates.waiting_for_category, UserStates.waiting_for_debt_type,
                                   UserStates.waiting_for_debt_person, UserStates.waiting_for_income_type,
                                   UserStates.waiting_for_income_frequency, UserStates.waiting_for_income_amount,
                                   UserStates.waiting_for_income_date, UserStates.waiting_for_income_weekday,
                                   UserStates.waiting_for_income_month, UserStates.waiting_for_income_day]:
        return
    
    text = message.text
    
    # AI ishlayotganini ko'rsatish
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    # Bajarilmoqda xabarini yuborish
    processing_msg = await message.answer("🔄 Bajarilmoqda...", parse_mode='Markdown')
    
    # AI yordamida moliyaviy ma'lumotni qayta ishlash
    result = await financial_module.process_ai_input(text, user_id)
    
    # Bajarilmoqda xabarini o'chirish
    try:
        await processing_msg.delete()
    except:
        pass
    
    if result['success']:
        if result.get('type') == 'single_confirmation':
            # Bitta tranzaksiya tasdiqlash
            await state.set_state(UserStates.waiting_for_transaction_confirmation)
            await state.update_data(transaction_data=result['transaction_data'])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💾 Saqlash", callback_data="trans_single")],
                [InlineKeyboardButton(text="🗑️ O'chirish", callback_data="trans_cancel_single")]
            ])
            
            await message.answer(result['message'], parse_mode='Markdown', reply_markup=keyboard)
            
        elif result.get('type') == 'multiple_preview':
            # Ko'p tranzaksiyalar oldindan ko'rinishi
            await state.set_state(UserStates.waiting_for_transaction_confirmation)
            await state.update_data(transaction_data=result['buttons_data'])
            
            # Tugmalarni yaratish
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
            
            await message.answer(result['message'], parse_mode='Markdown', reply_markup=keyboard)
        else:
            # Oddiy natija
            await message.answer(result['message'], parse_mode='Markdown')
    else:
        await message.answer(result['message'], parse_mode='Markdown')

# Audio xabarlarni qayta ishlash (Premium)
@dp.message(lambda message: message.voice or message.audio)
async def process_audio_message(message: types.Message, state: FSMContext):
    """Audio xabarlarni qayta ishlash (Premium)"""
    user_id = message.from_user.id
    # Avtomatik tarif muddatini tekshirish
    await ensure_tariff_valid(user_id)
    user_tariff = await get_user_tariff(user_id)
    
    # Faqat Premium tarif uchun audio qo'llab-quvvatlash
    if user_tariff not in PREMIUM_TARIFFS:
        await message.answer(
            "🎵 **Audio qo'llab-quvvatlash**\n\n"
            "Audio xabarlarni qayta ishlash faqat Premium tarifda mavjud.\n"
            "Tarifni yangilash uchun Profil > Tarif bo'limiga o'ting.",
            parse_mode='Markdown'
        )
        return
    
    # Agar foydalanuvchi boshqa holatda bo'lsa (onboarding yoki boshqa state'lar)
    if await state.get_state() in [UserStates.waiting_for_phone, UserStates.waiting_for_name, 
                                   UserStates.waiting_for_source, UserStates.waiting_for_tariff,
                                   UserStates.waiting_for_amount, UserStates.waiting_for_description, 
                                   UserStates.waiting_for_category, UserStates.waiting_for_debt_type,
                                   UserStates.waiting_for_debt_person, UserStates.waiting_for_income_type,
                                   UserStates.waiting_for_income_frequency, UserStates.waiting_for_income_amount,
                                   UserStates.waiting_for_income_date, UserStates.waiting_for_income_weekday,
                                   UserStates.waiting_for_income_month, UserStates.waiting_for_income_day]:
        return
    
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
        
        # Audio faylni qayta ishlash
        result = await financial_module.process_audio_input(audio_path, user_id)
        
        # Bajarilmoqda xabarini o'chirish
        try:
            await processing_msg.delete()
        except:
            pass
        
        # Natijani yuborish
        if result['success']:
            if result.get('type') == 'single_confirmation':
                # Bitta tranzaksiya tasdiqlash
                await state.set_state(UserStates.waiting_for_transaction_confirmation)
                await state.update_data(transaction_data=result['transaction_data'])
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💾 Saqlash", callback_data="trans_single")],
                    [InlineKeyboardButton(text="🗑️ O'chirish", callback_data="trans_cancel_single")]
                ])
                
                await message.answer(result['message'], parse_mode='Markdown', reply_markup=keyboard)
                
            elif result.get('type') == 'multiple_preview':
                # Ko'p tranzaksiyalar oldindan ko'rinishi
                await state.set_state(UserStates.waiting_for_transaction_confirmation)
                await state.update_data(transaction_data=result['buttons_data'])
                
                # Tugmalarni yaratish
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
                
                await message.answer(result['message'], parse_mode='Markdown', reply_markup=keyboard)
            else:
                # Oddiy natija
                await message.answer(result['message'], parse_mode='Markdown')
        else:
            await message.answer(result['message'], parse_mode='Markdown')
        
        # Audio faylni o'chirish
        try:
            os.remove(audio_path)
        except:
            pass
            
    except Exception as e:
        logging.error(f"Audio qayta ishlashda xatolik: {e}")
        await message.answer(
            "❌ Audio faylni qayta ishlashda xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring.",
            parse_mode='Markdown'
        )

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
        "Premium tarif menyusi:",
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
        "Premium tarif menyusi:",
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

@dp.callback_query(lambda c: c.data.startswith("trans_"))
async def handle_transaction_callback(callback_query: CallbackQuery, state: FSMContext):
    """Tranzaksiya tugmalari uchun umumiy handler"""
    print(f"DEBUG: Transaction callback received: {callback_query.data}")
    try:
        data = await state.get_data()
        transaction_data = data.get('transaction_data', {})
        print(f"DEBUG: Transaction data from state: {transaction_data}")
        
        if not transaction_data:
            print("DEBUG: No transaction data found in state")
            await callback_query.answer("❌ Tranzaksiya ma'lumotlari topilmadi!")
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
            current = user_data.get('tariff') if user_data else 'FREE'
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
async def process_successful_payment(message: types.Message):
    """To'lov muvaffaqiyatli yakunlangach ishlov berish"""
    try:
        user_id = message.from_user.id
        payload = message.successful_payment.invoice_payload or ""
        if payload.startswith("plus:"):
            # Payload format: plus:user_id:timestamp:months
            parts = payload.split(":")
            months = int(parts[3]) if len(parts) > 3 else 1
            
            from datetime import datetime, timedelta
            expires_at = datetime.now() + timedelta(days=30 * months)
            await db.add_user_subscription(user_id, "PLUS", expires_at)
            await db.set_active_tariff(user_id, "PLUS")

            # To'lov yozuvini saqlash
            sp = message.successful_payment
            total_amount = sp.total_amount
            currency = sp.currency
            telegram_charge_id = sp.telegram_payment_charge_id
            provider_charge_id = sp.provider_payment_charge_id

            await db.execute_insert(
                """
                INSERT INTO payments (user_id, tariff, total_amount, currency, payload, telegram_charge_id, provider_charge_id, status, paid_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'paid', NOW())
                """,
                (user_id, 'PLUS', total_amount, currency, payload, telegram_charge_id, provider_charge_id)
            )

            user_name = await get_user_name(user_id)
            await message.answer(
                f"✅ To'lov qabul qilindi va Plus tarif faollashtirildi!\n\n"
                f"Salom, {user_name}! Endi AI funksiyalaridan to'liq foydalana olasiz.",
                parse_mode="Markdown",
                reply_markup=get_premium_menu()
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
            except Exception as _e:
                logging.error(f"delete invoice message error: {_e}")
        elif payload.startswith("business:"):
            # Payload format: business:user_id:timestamp:months
            parts = payload.split(":")
            months = int(parts[3]) if len(parts) > 3 else 1
            
            from datetime import datetime, timedelta
            expires_at = datetime.now() + timedelta(days=30 * months)
            await db.add_user_subscription(user_id, "BUSINESS", expires_at)
            await db.set_active_tariff(user_id, "BUSINESS")

            sp = message.successful_payment
            await db.execute_insert(
                """
                INSERT INTO payments (user_id, tariff, total_amount, currency, payload, telegram_charge_id, provider_charge_id, status, paid_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'paid', NOW())
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

            user_name = await get_user_name(user_id)
            await message.answer(
                f"✅ To'lov qabul qilindi va Business tarif faollashtirildi!\n\n"
                f"Salom, {user_name}! Endi biznes menyusidan foydalanishingiz mumkin.",
                parse_mode="Markdown",
                reply_markup=get_business_menu()
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
            except Exception as _e:
                logging.error(f"delete invoice message error: {_e}")
    except Exception as e:
        logging.error(f"Successful payment processing error: {e}")
        await message.answer("❌ To'lovdan keyin tarifni faollashtirishda xatolik yuz berdi. Admin bilan bog'laning.")

async def main():
    """Asosiy dastur"""
    # Ma'lumotlar bazasini ulash
    await db.create_pool()
    
    # Jadvallarni yaratish
    await db.create_tables()
    
    try:
        # Bot ishga tushirish
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())