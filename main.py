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
from aiogram.types import ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, Contact, WebAppInfo, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from config import BOT_TOKEN, TARIFFS, CATEGORIES, TARIFF_PRICES, DISCOUNT_RATES, PAYMENT_METHODS, TELEGRAM_PAYMENT_PROVIDER_TOKEN, STARS_ENABLED, STARS_SOM_PER_STAR, SPEECH_MODELS, ACTIVE_SPEECH_MODELS, FREE_TRIAL_ENABLED
from database import db
from financial_module import FinancialModule
from reports_module import ReportsModule
from ai_chat import AIChat, AIChatFree

# Bot va dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Modullar
financial_module = FinancialModule()
reports_module = ReportsModule()
ai_chat = AIChat(db=db)
ai_chat_free = AIChatFree(db=db)

# Admin panelga ruxsat berilgan ID
ADMIN_USER_ID = 6429299277

# FastAPI app mini-app uchun
app = FastAPI(title="Balans AI Mini App API")

# CORS sozlamalari
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
        "Balans AI sizga mos keladigan turli xil tariflarni taklif etadi. "
        "Shaxsiy byudjetingizni nazorat qilmoqchimisiz, oilaviy xarajatlarni boshqarmoqchimisiz yoki "
        "biznesingizni avtomatlashtirmoqchimisiz — bu yerda albatta sizga mos yechim bor.\n\n"
        "Quyidagi tariflardan birini tanlang 👇\n"
    )

def build_tariff_detail_keyboard(tariff_code: str, back_callback: str) -> InlineKeyboardMarkup:
    async def keyboard_for_user(user_id: int) -> InlineKeyboardMarkup:
        current = await get_user_tariff(user_id)
        if current == tariff_code and current != 'FREE':
            # Aktiv tarif: faqat orqaga tugmasi
            return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back_callback)]])
        
        # 1 haftalik sinov holatini tekshirish
        if tariff_code in FREE_TRIAL_ENABLED and FREE_TRIAL_ENABLED[tariff_code]:
            # 1 haftalik sinov yoqilgan - sinov tugmasi
            return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back_callback), InlineKeyboardButton(text="🆓 1 Hafta bepul sinash", callback_data=f"free_trial_{tariff_code}")]])
        else:
            # 1 haftalik sinov o'chirilgan - aktivlashtirish tugmasi
            return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back_callback), InlineKeyboardButton(text="🚀 Aktivlashtirish", callback_data=f"activate_{tariff_code}")]])

    # Fallback sync qurilishi (agar user_id konteksti yo'q bo'lsa)
    if tariff_code in FREE_TRIAL_ENABLED and FREE_TRIAL_ENABLED[tariff_code]:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back_callback), InlineKeyboardButton(text="🆓 1 Hafta bepul sinash", callback_data=f"free_trial_{tariff_code}")]])
    else:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back_callback), InlineKeyboardButton(text="🚀 Aktivlashtirish", callback_data=f"activate_{tariff_code}")]])

def build_main_tariff_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Bepul", callback_data="tariff_FREE"),
            InlineKeyboardButton(text="Plus", callback_data="tariff_PLUS"),
            InlineKeyboardButton(text="Max", callback_data="tariff_MAX")
        ],
        [
            InlineKeyboardButton(text="Biznes tariflari", callback_data="tariff_BUSINESS_MENU"),
            InlineKeyboardButton(text="Oila tariflari", callback_data="tariff_FAMILY_MENU")
        ]
    ])

def get_family_tariff_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Oila", callback_data="tariff_FAMILY")],
        [InlineKeyboardButton(text="Oila Plus", callback_data="tariff_FAMILY_PLUS")],
        [InlineKeyboardButton(text="Oila Max", callback_data="tariff_FAMILY_MAX")],
        [InlineKeyboardButton(text="⬅️ Asosiy tariflar", callback_data="tariff_BACK_MAIN")]
    ])

def get_business_tariff_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Biznes", callback_data="tariff_BUSINESS")],
        [InlineKeyboardButton(text="Biznes Plus (tez orada)", callback_data="tariff_BUSINESS_PLUS_INFO")],
        [InlineKeyboardButton(text="Biznes Max (tez orada)", callback_data="tariff_BUSINESS_MAX_INFO")],
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
            "✔️ Kichik biznes uchun\n"
            "✔️ 1 boshliq + 1 xodim\n"
            "✔️ Moliyaviy boshqaruvni avtomatlashtirish"
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

# Business menyusi
def get_business_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Xodim qo'shish"), KeyboardButton(text="💳 Qarzlar")],
            [KeyboardButton(text="📊 Hisobotlar")],
            [KeyboardButton(text="👤 Profil")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

# Xodim menyusi
def get_employee_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Kirim"), KeyboardButton(text="➖ Chiqim")],
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
def get_profile_menu(user_tariff='FREE'):
    """Profil menyusini qaytaradi - FREE tarifda statistika yo'q"""
    if user_tariff == 'FREE':
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⚡ Kuchaytirish", web_app=WebAppInfo(url="https://balansai.onrender.com/payment"))],
                [InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data="settings"), InlineKeyboardButton(text="💳 Tarif", callback_data="tariff_info")]
            ]
        )
    elif user_tariff == 'PLUS':
        # PLUS tarif uchun - faqat Sozlamalar va Pro ga yangilash
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data="settings"), InlineKeyboardButton(text="💎 Pro ga yangilash", web_app=WebAppInfo(url="https://balansai.onrender.com/payment-pro"))]
            ]
        )
    else:
        # PRO va boshqa tariflar uchun - Sozlamalar va Tarif
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data="settings"), InlineKeyboardButton(text="💳 Tarif", callback_data="tariff_info")]
            ]
        )
    return keyboard

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
            [InlineKeyboardButton(text="🆓 1 Haftalik Sinov Boshqarish", callback_data="admin_free_trial")]
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
    google_status = "✅ Yoqilgan" if ACTIVE_SPEECH_MODELS['GOOGLE'] else "❌ O'chirilgan"
    
    text = f"""🎤 **Speech Model Boshqarish**

**Hozirgi holat:**
• Google Cloud Speech-to-Text: {google_status}

**Boshqarish:**
Quyidagi tugmadan foydalaning:"""
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Google: {google_status}", callback_data="admin_toggle_google")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin_back")]
        ]
    )
    
    await callback_query.message.edit_caption(caption=text, reply_markup=kb, parse_mode='Markdown')
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "admin_toggle_google")
async def admin_toggle_google_callback(callback_query: CallbackQuery):
    if callback_query.from_user.id != ADMIN_USER_ID:
        await callback_query.answer()
        return
    
    # Google ni toggle qilish
    ACTIVE_SPEECH_MODELS['GOOGLE'] = not ACTIVE_SPEECH_MODELS['GOOGLE']
    # Bazaga saqlash
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
            [InlineKeyboardButton(text="🆓 1 Haftalik Sinov Boshqarish", callback_data="admin_free_trial")]
        ]
    )
    
    await callback_query.message.edit_caption(caption="Admin panel", reply_markup=kb)
    await callback_query.answer()

# 1 haftalik sinov boshqarish
@dp.callback_query(lambda c: c.data == "admin_free_trial")
async def admin_free_trial_callback(callback_query: CallbackQuery):
    if callback_query.from_user.id != ADMIN_USER_ID:
        await callback_query.answer()
        return
    
    # Hozirgi holatni ko'rsatish
    text = "🆓 **1 Haftalik Sinov Boshqarish**\n\n**Hozirgi holat:**\n"
    
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
    
    await callback_query.message.edit_caption(caption=text, reply_markup=kb, parse_mode='Markdown')
    await callback_query.answer()

# 1 haftalik sinov toggle
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
            [InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data="settings")],
            [InlineKeyboardButton(text="💳 Tarif", callback_data="tariff_info")],
            [InlineKeyboardButton(text="🚪 Jamoadan chiqish", callback_data="leave_team")]
        ]
    )
    return keyboard

# Sozlamalar menyusi
def get_settings_menu(user_tariff='FREE'):
    """Sozlamalar menyusini qaytaradi - FREE tarifda statistika yo'q"""
    if user_tariff == 'FREE':
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_profile")]
            ]
        )
    else:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
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
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    # /start xabarini o'chirmaymiz - foydalanuvchi ko'rsin
    
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
    
    # Boshlang'ich balans mavjudligini tekshirish (onboarding yakunlanganmi)
    has_initial_balance = False
    has_any_transactions = False
    if user_data:
        balance_query = """
        SELECT COUNT(*) FROM transactions 
        WHERE user_id = %s AND category IN ('boshlang_ich_balans', 'boshlang_ich_naqd', 'boshlang_ich_karta')
        """
        result = await db.execute_one(balance_query, (user_id,))
        has_initial_balance = result[0] > 0 if result else False

        # Foydalanuvchida umuman tranzaksiya bormi (yangi foydalanuvchini ajratish uchun)
        tx_count_query = "SELECT COUNT(*) FROM transactions WHERE user_id = %s"
        tx_result = await db.execute_one(tx_count_query, (user_id,))
        has_any_transactions = (tx_result[0] > 0) if tx_result else False

    # Eski onboarding logikasini tekshirish
    # Agar foydalanuvchi onboarding jarayonida bo'lsa, qayerda to'xtagan bo'lsa o'sha yerdan davom etadi
    current_state = await state.get_state()
    
    # Onboarding holatlarini tekshirish
    if current_state in [UserStates.onboarding_balance, UserStates.onboarding_waiting_for_debt_action, 
                        UserStates.onboarding_debt_waiting_for_person, UserStates.onboarding_debt_waiting_for_amount]:
        # Foydalanuvchi onboarding jarayonida - qayerda to'xtagan bo'lsa o'sha yerdan davom etadi
        if current_state == UserStates.onboarding_balance:
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
        elif current_state == UserStates.onboarding_waiting_for_debt_action:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Qarz berganman", callback_data="onboarding_debt_lent")],
                [InlineKeyboardButton(text="❌ Qarzlar yo'q", callback_data="onboarding_no_debts")]
            ])
            await message.answer_photo(
                photo=FSInputFile('welcome.png'),
                caption=(
                    "💳 **2-qadam: Qarzlar holati**\n\n"
                    "Kimga qarz berganmisiz yoki kimdan qarzdormisiz?"
                ),
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        elif current_state == UserStates.onboarding_debt_waiting_for_person:
            await message.answer_photo(
                photo=FSInputFile('welcome.png'),
                caption=(
                    "💸 **Qarz bergan odam ismini kiriting:**\n\n"
                    "Masalan: Akmal, Oila, Do'st, va h.k."
                ),
                reply_markup=ReplyKeyboardRemove(),
                parse_mode='Markdown'
            )
        elif current_state == UserStates.onboarding_debt_waiting_for_amount:
            data = await state.get_data()
            person_name = data.get('debt_person', 'Noma\'lum')
            await message.answer_photo(
                photo=FSInputFile('welcome.png'),
                caption=(
                    f"💰 **{person_name}ga qancha qarz berganmisiz?**\n\n"
                    "Masalan: 100000 (agar 100,000 so'm bo'lsa)"
                ),
                reply_markup=ReplyKeyboardRemove(),
                parse_mode='Markdown'
            )
        return
    
    # Agar foydalanuvchi onboarding yakunlagan bo'lsa
    if has_initial_balance or has_any_transactions:
        # Eski foydalanuvchi - asosiy menyuni ko'rsatish
        user_name = await get_user_name(user_id)
        user_tariff = await get_user_tariff(user_id)
        
        if user_tariff == 'FREE':
            await message.answer_photo(
                photo=FSInputFile('welcome.png'),
                caption=f"👋 Salom, {user_name}!\n\nBalans AI ga xush kelibsiz!\n\nQuyidagi tugmalardan foydalaning:",
                reply_markup=get_free_menu(),
                parse_mode="Markdown"
            )
        elif user_tariff == 'BUSINESS':
            await message.answer_photo(
                photo=FSInputFile('welcome.png'),
                caption=f"👋 Salom, {user_name}!\n\nBalans AI Business ga xush kelibsiz!\n\nMatn yoki ovozli xabar yuboring va AI avtomatik qayta ishlaydi:",
                reply_markup=get_business_menu(),
                parse_mode="Markdown"
            )
        else:
            await message.answer_photo(
                photo=FSInputFile('welcome.png'),
                caption=f"👋 Salom, {user_name}!\n\nBalans AI ga xush kelibsiz!\n\nMatn yoki ovozli xabar yuboring va AI avtomatik qayta ishlaydi:",
                reply_markup=get_premium_menu(),
                parse_mode="Markdown"
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
                    "Balans AI'ga Xush kelibsiz!\n\n"
                    "• Moliyaviy holatingizni aniq va estetik hisobotlarda namoyish qilaman.\n"
                    "• Xarajatlaringizni oqilona tasniflab, tejash strategiyasini taklif qilaman.\n"
                    "• Premium'da — shaxsiy maslahatlar, cheklanmagan AI yordam va ustuvor xizmat.\n\n"
                    "🔐 Xavfsiz, shaffof va nafis. Moliyangizni boshqarish hech qachon bunday oson bo'lmagan.\n\n"
                    "⏩ Boshlash: telefoningizni pastdagi tugma orqali yuboring."
                ),
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[[KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)]],
                    resize_keyboard=True
                ),
                parse_mode="Markdown"
            )
            await state.update_data(phone_request_msg_id=_msg.message_id)
        except Exception as _e:
            logging.warning(f"Welcome rasm yuborilmadi: {_e}")
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

    # 2.2) Agar onboarding jarayonida bo'lsa -> faqat state qoldirish, xabar yubormasdan
    current_state = await state.get_state()
    
    # Onboarding state'larda /start tugma ishlatmaydi
    if current_state in [UserStates.waiting_for_phone.state, UserStates.waiting_for_name.state, 
                         UserStates.waiting_for_source.state, UserStates.waiting_for_account_type.state]:
        # State'ni qoldirish, lekin yaxlit xabar yubormasdan
        return
    
    # OnboardingState holatlari uchun
    if current_state == OnboardingState.waiting_for_income.state:
        await message.answer(
            "📊 **Onboarding bosqichi 1/3**\n\n"
            "Oylik daromadingizni kiriting (so'mda):\n\n"
            "Misol: 5000000",
            parse_mode='Markdown'
        )
        return
    elif current_state == OnboardingState.waiting_for_balance.state:
        await message.answer(
            "💰 **Onboarding bosqichi 2/3**\n\n"
            "Hozirgi balansingizni kiriting (so'mda):\n\n"
            "Misol: 2000000",
            parse_mode='Markdown'
        )
        return
    elif current_state == OnboardingState.waiting_for_debts.state:
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
        return
    
    # UserStates holatlari uchun
    if current_state == UserStates.waiting_for_name.state:
        _msg = await message.answer_photo(
            photo=FSInputFile('what_is_your_name.png'),
            caption=(
                "Sizni nima deb chaqiray? (Ismingizni kiriting yoki 'Xojayin' deb chaqishim mumkin)"
            ),
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="Xojayin deb chaqir")]],
                resize_keyboard=True
            ),
            parse_mode="Markdown"
        )
        try:
            await state.update_data(onboarding_last_prompt_id=_msg.message_id)
        except Exception:
            pass
        return
    if current_state == UserStates.waiting_for_source.state:
        _msg = await message.answer_photo(
            photo=FSInputFile('where_did_you_hear_us.png'),
            caption=("Bizni qayerda eshitdingiz?"),
            reply_markup=get_source_menu(),
            parse_mode="Markdown"
        )
        try:
            await state.update_data(onboarding_last_prompt_id=_msg.message_id)
        except Exception:
            pass
        return
    if current_state == UserStates.waiting_for_initial_card.state:
        await message.answer(
            "💳 2-qadam: Karta balansini kiriting.\nMasalan: 0 yoki 200000",
            parse_mode="Markdown"
        )
        return
    if current_state == UserStates.onboarding_waiting_for_debt_action.state:
        await message.answer(
            "📒 3-qadam: Mavjud qarzlaringizni kiriting yoki tugallang.",
            reply_markup=get_onboarding_debt_menu()
        )
        return
    if current_state == UserStates.waiting_for_debt_type.state:
        await message.answer(
            "Qarz turini tanlang:",
            reply_markup=get_debt_type_menu()
        )
        return
    if current_state == UserStates.onboarding_debt_waiting_for_person.state:
        await message.answer("Qarz bo'yicha shaxs/izohni kiriting (masalan: Ali yoki Elektr hisob).")
        return
    if current_state == UserStates.onboarding_debt_waiting_for_amount.state:
        await message.answer("Qarz summasini kiriting (faqat son).")
        return
    if current_state == UserStates.onboarding_debt_waiting_for_due_date.state:
        await message.answer("Qaytarish sanasini kiriting (YYYY-MM-DD) yoki 'skip'.")
        return


    # 4) Aks holda, asosiy menyuni ko'rsatish
    if user_data and user_data.get('phone') and (await state.get_state()) != UserStates.waiting_for_tariff.state:
        # Eski foydalanuvchi - asosiy menyuni ko'rsatish
        user_name = await get_user_name(user_id)
        
        try:
            if user_tariff == "FREE":
                await message.answer_photo(
                    photo=FSInputFile('welcome.png'),
                    caption=(
                        f"👋 Salom, {user_name}!\n\n"
                        "Balans AI ga xush kelibsiz!\n\n"
                        "Quyidagi tugmalardan foydalaning:"
                    ),
                    reply_markup=get_free_menu(),
                    parse_mode="Markdown"
                )
            elif user_tariff == "BUSINESS":
                await message.answer_photo(
                    photo=FSInputFile('welcome.png'),
                    caption=(
                        f"👋 Salom, {user_name}!\n\n"
                        "Balans AI Business ga xush kelibsiz!\n\n"
                        "Matn yoki ovozli xabar yuboring va AI avtomatik qayta ishlaydi:"
                    ),
                    reply_markup=get_business_menu(),
                    parse_mode="Markdown"
                )
            else:
                await message.answer_photo(
                    photo=FSInputFile('welcome.png'),
                    caption=(
                        f"👋 Salom, {user_name}!\n\n"
                        "Balans AI ga xush kelibsiz!\n\n"
                        "Matn yoki ovozli xabar yuboring va AI avtomatik qayta ishlaydi:"
                    ),
                    reply_markup=get_premium_menu(),
                    parse_mode="Markdown"
                )
        except Exception as e:
            logging.warning(f"Welcome rasm yuborilmadi: {e}")
            # Rasm yuborishda xatolik bo'lsa, oddiy matn xabar yuboramiz
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
    # fallback
    return

    # Agar foydalanuvchi telefon bergan bo'lsa-yu, hali tarif tanlamagan bo'lsa, tarif menyusiga yo'naltiramiz
    if (await state.get_state()) == UserStates.waiting_for_tariff.state:
        await message.answer(
            get_tariff_overview_text(),
            reply_markup=build_main_tariff_keyboard()
        )
        return

# Tur tanlash menyusini qaytaradi
def get_account_type_menu():
    """Hisob turini tanlash uchun tugmalar"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👤 Shaxsiy foydalanish uchun", callback_data="account_type_SHI")],
            [InlineKeyboardButton(text="👨‍👩‍👧‍👦 Oila uchun", callback_data="account_type_OILA")],
            [InlineKeyboardButton(text="🏢 Biznes uchun", callback_data="account_type_BIZNES")]
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
    
    # Ism so'rash
    _msg = await message.answer_photo(
        photo=FSInputFile('what_is_your_name.png'),
        caption=(
            "👋 **Keling tanishib olsak!**\n\n"
            "Ismingizni kiriting yoki `/skip` yuboring."
        ),
        parse_mode="Markdown"
    )
    try:
        await state.update_data(name_request_msg_id=_msg.message_id)
    except Exception:
        pass
    await state.set_state(UserStates.waiting_for_name)

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
    account_type = callback_query.data.split("_")[2]  # SHI, OILA, BIZNES
    
    # Account turini bazaga saqlash
    await db.execute_query(
        "UPDATE users SET account_type = %s WHERE user_id = %s",
        (account_type, user_id)
    )
    
    # Oila va Biznes uchun rasmli xabar va tugmalar
    if account_type == 'OILA':
        # Oila uchun rasmli xabar
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Aktivlashtirish", callback_data="activate_oila")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_account_type")]
        ])
        
        # Xabarni yangilash
        try:
            await callback_query.message.edit_caption(
                caption=(
                    "👨‍👩‍👧‍👦 **Oila Rejimi**\n\n"
                    "Oila rejimida siz o'z oilangiz bilan birgalikda moliyaviy ma'lumotlaringizni boshqarishingiz mumkin.\n\n"
                    "✨ **Imkoniyatlar:**\n"
                    "• Oiladagi barcha a'zolarning tranzaksiyalari\n"
                    "• Kelishilgan moliyaviy maqsadlar\n"
                    "• Oilaviy xarajatlar monitoringi\n"
                    "• Bolalar uchun alohida hisobotlar\n\n"
                    "⚡ **Tez orada ishga tushadi!**"
                ),
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        except:
            await callback_query.message.delete()
            await callback_query.message.answer_photo(
                photo=FSInputFile('welcome1.png'),
                caption=(
                    "👨‍👩‍👧‍👦 **Oila Rejimi**\n\n"
                    "Oila rejimida siz o'z oilangiz bilan birgalikda moliyaviy ma'lumotlaringizni boshqarishingiz mumkin.\n\n"
                    "✨ **Imkoniyatlar:**\n"
                    "• Oiladagi barcha a'zolarning tranzaksiyalari\n"
                    "• Kelishilgan moliyaviy maqsadlar\n"
                    "• Oilaviy xarajatlar monitoringi\n"
                    "• Bolalar uchun alohida hisobotlar\n\n"
                    "⚡ **Tez orada ishga tushadi!**"
                ),
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        await callback_query.answer()
        return
    
    if account_type == 'BIZNES':
        # Biznes uchun rasmli xabar
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Aktivlashtirish", callback_data="activate_biznes")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_account_type")]
        ])
        
        # Xabarni yangilash
        try:
            await callback_query.message.edit_caption(
                caption=(
                    "🏢 **Biznes Rejimi**\n\n"
                    "Biznes rejimida kichik va o'rta bizneslarni boshqarishingiz mumkin.\n\n"
                    "✨ **Imkoniyatlar:**\n"
                    "• Xodimlar soni va ularning maoshlarini boshqarish\n"
                    "• Do'kon va filyallarning daromadlarini monitoring qilish\n"
                    "• Xarajatlar va foydaning tahlili\n"
                    "• Bir nechta hisobni boshqarish\n"
                    "• To'liq biznes hisobotlari\n\n"
                    "⚡ **Tez orada ishga tushadi!**"
                ),
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        except:
            await callback_query.message.delete()
            await callback_query.message.answer_photo(
                photo=FSInputFile('tariff.png'),
                caption=(
                    "🏢 **Biznes Rejimi**\n\n"
                    "Biznes rejimida kichik va o'rta bizneslarni boshqarishingiz mumkin.\n\n"
                    "✨ **Imkoniyatlar:**\n"
                    "• Xodimlar soni va ularning maoshlarini boshqarish\n"
                    "• Do'kon va filyallarning daromadlarini monitoring qilish\n"
                    "• Xarajatlar va foydaning tahlili\n"
                    "• Bir nechta hisobni boshqarish\n"
                    "• To'liq biznes hisobotlari\n\n"
                    "⚡ **Tez orada ishga tushadi!**"
                ),
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        await callback_query.answer()
        return
    
    # Shaxsiy tanlangan - xabarni o'chirish
    try:
        await callback_query.message.delete()
    except:
        pass
    
    # Tabrik xabari
    tabrik_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Boshlash", callback_data="start_onboarding")]
    ])
    
    await callback_query.message.answer_photo(
        photo=FSInputFile('welcome.png'),
        caption=(
            "🎉 **Hammasi tayyor!**\n\n"
            "Balans AI ga xush kelibsiz! Biz sizga shaxsiy moliyaviy yordam berishdan xursandmiz.\n\n"
            "Boshlash tugmasini bosing."
        ),
        reply_markup=tabrik_keyboard,
        parse_mode='Markdown'
    )
    await callback_query.answer()
    await state.set_state(UserStates.onboarding_complete)

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
        photo=FSInputFile('welcome.png'),
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
        tariff = data.get('onboarding_tariff', 'FREE')
        user_id = message.from_user.id

        # Tanlangan tarifni aktiv qilish
        await db.execute_query("UPDATE users SET tariff = %s WHERE user_id = %s", (tariff, user_id))

        # Yakuniy menyu
        user_name = await get_user_name(user_id)
        if tariff == 'FREE':
            await message.answer(
                f"✅ Onboarding yakunlandi!\n\nSalom, {user_name}!\nQuyidagi tugmalardan foydalaning:",
                reply_markup=get_free_menu(),
                parse_mode='Markdown'
            )
        else:
            await message.answer(
                f"✅ Onboarding yakunlandi!\n\nSalom, {user_name}!\nMatn yoki ovoz yuboring, AI qayta ishlaydi:",
                reply_markup=get_premium_menu(),
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
        photo=FSInputFile('welcome.png'),
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

            # Qarz berish qaydini saqlaymiz
            insert_id = await db.execute_insert(
                "INSERT INTO transactions (user_id, transaction_type, amount, category, description, due_date, debt_direction) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (user_id, transaction_type, amount, category, description, due_date, debt_direction)
            )

            # Onboarding tugagan bo'lsa, balansdan chiqim yozamiz
            if not is_onboarding:
                await db.execute_query(
                    "INSERT INTO transactions (user_id, transaction_type, amount, category, description) VALUES (%s, %s, %s, %s, %s)",
                    (user_id, 'expense', amount, f"Qarz berish: {category}", f"Qarz berish - {description}")
                )

        # Qarz olish (borrowed): balansga kirim yozish faqat onboarding tugaganidan keyin
        elif transaction_type == 'debt' and debt_type == 'borrowed':
            # Qarz olish qaydini saqlaymiz
            insert_id = await db.execute_insert(
                "INSERT INTO transactions (user_id, transaction_type, amount, category, description, due_date, debt_direction) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (user_id, transaction_type, amount, category, description, due_date, debt_direction)
            )

            # Onboarding tugagan bo'lsa, balansga kirim yozamiz
            if not is_onboarding:
                await db.execute_query(
                    "INSERT INTO transactions (user_id, transaction_type, amount, category, description) VALUES (%s, %s, %s, %s, %s)",
                    (user_id, 'income', amount, f"Qarz olish: {category}", f"Qarz olish - {description}")
                )

        else:
            # Oddiy tranzaksiya (kirim, chiqim)
            insert_id = await db.execute_insert(
                "INSERT INTO transactions (user_id, transaction_type, amount, category, description, due_date, debt_direction) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (user_id, transaction_type, amount, category, description, due_date, debt_direction)
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
            f"📝 {description if description else 'Tavsif yoq'}\n\n",
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
            if current_tariff == 'FREE':
                await callback_query.message.answer(
                    "Bepul tarif menyusi:",
                    reply_markup=get_free_menu()
                )
            elif current_tariff == 'BUSINESS':
                await callback_query.message.answer(
                    "Business menyusi:",
                    reply_markup=get_business_menu()
                )
            else:
                await callback_query.message.answer(
                    "Premium menyusi:",
                    reply_markup=get_premium_menu()
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
                "Bepul tarif menyusi:",
                reply_markup=get_free_menu()
            )

    # Onboarding bo'lsa state'ni tozalamaymiz; onboarding yakunida tozalanadi
    st_data = await state.get_data()
    is_onboarding = bool(st_data.get('onboarding_tariff') or st_data.get('is_onboarding_debt'))
    if not is_onboarding:
        await state.clear()

# Hisobotlar menyusi
@dp.message(lambda message: message.text == "📊 Hisobotlar")
async def reports_menu(message: types.Message, state: FSMContext):
    """Hisobotlar menyusi - qisqa balans ko'rsatish"""
    user_id = message.from_user.id
    user_tariff = await get_user_tariff(user_id)
    
    # Balans ma'lumotlarini olish
    balances = await db.get_balances(user_id)
    
    # Qisqa balans ko'rsatish
    message_text = "📊 **Qisqa balans**\n\n"
    message_text += f"💵 **Naqd balans:** {balances['cash_balance']:,.0f} so'm\n"
    message_text += f"📊 **Sof balans:** {balances['net_balance']:,.0f} so'm\n"
    message_text += f"📈 **Jami kirim:** {balances['total_income']:,.0f} so'm\n"
    message_text += f"📉 **Jami chiqim:** {balances['total_expense']:,.0f} so'm\n"
    
    # Qarzlar bo'lsa ko'rsatish
    if balances['total_lent_debt'] > 0:
        message_text += f"💸 **Berilgan qarz:** {balances['total_lent_debt']:,.0f} so'm\n"
    if balances['total_borrowed_debt'] > 0:
        message_text += f"💳 **Olingan qarz:** {balances['total_borrowed_debt']:,.0f} so'm\n"
    
    # Mini app uchun tugma
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 To'liq ko'rish", url="https://t.me/balansaibot/hisobotlar")]
    ])
    
    await message.answer(
        message_text,
        reply_markup=keyboard,
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
    
    # Xodim bo'lsa, maxsus profil ko'rsatish
    if user_tariff == 'EMPLOYEE':
        # Boshliq ma'lumotlarini olish
        manager_data = await db.get_user_data(user_data.get('manager_id', 0))
        manager_name = manager_data.get('name', 'Noma\'lum') if manager_data else 'Noma\'lum'
        
        profile_text = f"👤 **Xodim Profili**\n\n"
        profile_text += f"🆔 ID: `{user_id}`\n"
        profile_text += f"📅 Ro'yxat: {user_data['created_at'].strftime('%d.%m.%Y')}\n"
        profile_text += f"👤 Ism: {user_data.get('name', 'Nomalum')}\n"
        if user_data.get('phone'):
            profile_text += f"📱 Tel: {user_data['phone']}\n\n"
        
        profile_text += f"🎯 **Rol:** Xodim\n"
        profile_text += f"👨‍💼 **Boshliq:** {manager_name}\n"
        profile_text += f"⚠️ **Cheklov:** Tarif sotib olish imkoniyati yo'q\n"
        
        await message.answer(profile_text, reply_markup=get_employee_profile_menu(), parse_mode='Markdown')
        return
    
    # Oddiy foydalanuvchi profili (yangi UI)
    display_name = user_data.get('name', 'Xojayin')
    
    # FREE tarif uchun tranzaksiya sonini qo'shamiz
    if user_tariff == 'FREE':
        try:
            row = await db.execute_one(
                """
                SELECT COUNT(*) 
                FROM transactions 
                WHERE user_id = %s 
                AND MONTH(created_at) = MONTH(NOW())
                AND YEAR(created_at) = YEAR(NOW())
                """,
                (user_id,)
            )
            monthly_count = row[0] if row else 0
            remaining = max(0, 250 - monthly_count)
            profile_text = (
                f"{display_name} (ID: {user_id})\n\n"
                f"Joriy tarif: Bepul\n"
                f"Tranzaksiyalar: {monthly_count}/250"
            )
        except Exception as e:
            logging.error(f"Error getting monthly stats: {e}")
            profile_text = (
                f"{display_name} (ID: {user_id})\n\n"
                f"Joriy tarif: Bepul"
            )
    elif user_tariff == 'PLUS':
        # PLUS tarif uchun maxsus format
        try:
            row = await db.execute_one(
                """
                SELECT COUNT(*) 
                FROM transactions 
                WHERE user_id = %s 
                AND MONTH(created_at) = MONTH(NOW())
                AND YEAR(created_at) = YEAR(NOW())
                """,
                (user_id,)
            )
            monthly_count = row[0] if row else 0
            
            audio_row = await db.execute_one(
                """
                SELECT COUNT(*) 
                FROM transactions 
                WHERE user_id = %s 
                AND MONTH(created_at) = MONTH(NOW())
                AND YEAR(created_at) = YEAR(NOW())
                AND description LIKE '%voice%'
                """,
                (user_id,)
            )
            audio_count = audio_row[0] if audio_row else 0
            
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
                SELECT COUNT(*) 
                FROM transactions 
                WHERE user_id = %s 
                AND MONTH(created_at) = MONTH(NOW())
                AND YEAR(created_at) = YEAR(NOW())
                """,
                (user_id,)
            )
            monthly_count = row[0] if row else 0
            
            audio_row = await db.execute_one(
                """
                SELECT COUNT(*) 
                FROM transactions 
                WHERE user_id = %s 
                AND MONTH(created_at) = MONTH(NOW())
                AND YEAR(created_at) = YEAR(NOW())
                AND description LIKE '%voice%'
                """,
                (user_id,)
            )
            audio_count = audio_row[0] if audio_row else 0
            
            expires_str = _format_date_uz(user_data['tariff_expires_at']) + " gacha" if user_data.get('tariff_expires_at') else '—'
            
            profile_text = (
                f"{display_name} (ID: {user_id})\n\n"
                f"Tarif: Pro ({expires_str})\n"
                f"Tranzaksiyalar: {monthly_count}/1000\n"
                f"Ovozli Tranzaksiyalar: {audio_count}/500"
            )
        except Exception as e:
            logging.error(f"Error getting PRO stats: {e}")
            expires_str = _format_date_uz(user_data['tariff_expires_at']) + " gacha" if user_data.get('tariff_expires_at') else '—'
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
            reply_markup=profile_kb,
            parse_mode='Markdown'
        )
    except Exception:
        await message.answer(profile_text, reply_markup=profile_kb, parse_mode='Markdown')

# Profil callback handlerlari
@dp.callback_query(lambda c: c.data == "settings")
async def settings_callback(callback_query: CallbackQuery):
    """Sozlamalar menyusini ko'rsatish"""
    user_id = callback_query.from_user.id
    user_tariff = await get_user_tariff(user_id)
    
    text = "⚙️ **Sozlamalar**\n\nHozircha sozlamalar mavjud emas."
    keyboard = get_settings_menu(user_tariff)
    try:
        await callback_query.message.edit_caption(caption=text, reply_markup=keyboard, parse_mode='Markdown')
    except Exception:
        await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode='Markdown')
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
        row = await db.execute_one("SELECT COUNT(*) FROM transactions WHERE user_id = %s", (user_id,))
        total = row[0] if row else 0
    except Exception as e:
        logging.error(f"profile_stats_callback error: {e}")
        total = 0
    
    # FREE tarif uchun oylik limit ko'rsatish
    if user_tariff == 'FREE':
        try:
            row = await db.execute_one(
                """
                SELECT COUNT(*) 
                FROM transactions 
                WHERE user_id = %s 
                AND MONTH(created_at) = MONTH(NOW())
                AND YEAR(created_at) = YEAR(NOW())
                """,
                (user_id,)
            )
            monthly_count = row[0] if row else 0
            remaining = max(0, 250 - monthly_count)
            text = f"📊 Statistika (FREE tarif)\n\n"
            text += f"Bu oy: {monthly_count}/250 tranzaksiya\n"
            text += f"Qolgan: {remaining} ta\n\n"
            text += f"Jami tranzaksiyalar: {total:,} ta"
        except Exception as e:
            logging.error(f"Error getting monthly stats: {e}")
            text = f"📊 Statistika\n\nJami tranzaksiyalar: {total:,} ta"
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

@dp.callback_query(lambda c: c.data == "onboarding_no_debts")
async def onboarding_no_debts(callback_query: CallbackQuery, state: FSMContext):
    """Qarzlar yo'q - onboarding tugatish"""
    user_id = callback_query.from_user.id
    
    # Eski xabarni o'chirish
    try:
        await callback_query.message.delete()
    except:
        pass
    
    # Onboarding tugagach tabrik xabari + menyu bir xabarda
    try:
        await ensure_tariff_valid(user_id)
    except Exception:
        pass
    current_tariff = await get_user_tariff(user_id)
    
    # Menyu tanlash
    if current_tariff == 'FREE':
        menu = get_free_menu()
    elif current_tariff == 'BUSINESS':
        menu = get_business_menu()
    else:
        menu = get_premium_menu()
    
    await callback_query.message.answer_photo(
        photo=FSInputFile('welcome.png'),
        caption=(
            "🎉 **Tabriklaymiz! Onboarding tugadi!**\n\n"
            "Sizning moliyaviy profilingiz tayyor. Endi quyidagi imkoniyatlardan foydalanishingiz mumkin:\n\n"
            "• 💰 Balansni kuzatish\n"
            "• 📊 Moliyaviy hisobotlar\n"
            "• 🤖 AI yordamchi\n"
            "• 📱 Qulay interfeys\n\n"
            "Agar qanday foydalanishni tushunmasangiz, admin bilan bog'laning:\n"
            "👤 @nurmuxammadrayimov\n\n"
            "Muvaffaqiyatlar! 🚀"
        ),
        reply_markup=menu,
        parse_mode="Markdown"
    )
    
    await state.clear()
    await callback_query.answer()

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
    user_id = message.from_user.id
    text = message.text.strip()
    
    # AI bilan qarz ma'lumotlarini parse qilish
    try:
        from ai_chat import AIChat
        ai = AIChat(db=db)
        debt_info = await ai._parse_debt_info(text)
        
        person_name = debt_info.get('person', 'Noma\'lum')
        amount = debt_info.get('amount', 0)
        due_date = debt_info.get('due_date')
        
    except Exception as e:
        logging.error(f"AI qarz parse xatolik: {e}")
        # Fallback - oddiy parse
        person_name = text.split()[0] if text.split() else "Noma'lum"
        try:
            import re
            numbers = re.findall(r'\d+', text)
            amount = float(''.join(numbers)) if numbers else 0
        except:
            amount = 0
        due_date = None
    
    # Qarzni saqlash
    data = await state.get_data()
    debt_type = data.get('debt_type', 'lent')
    
    if amount > 0:
        await db.add_transaction(
            user_id, 
            'expense' if debt_type == 'lent' else 'income',
            int(amount),
            'qarz_berdim' if debt_type == 'lent' else 'qarz_oldim',
            f"Onboarding: {person_name}ga qarz" + (f" (Qaytish: {due_date})" if due_date else "")
        )
        
        # Eski xabarlarni o'chirish
        try:
            await message.delete()
        except:
            pass
        
        # Yana qo'shish yoki tugatish
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Yana qo'shish", callback_data=f"onboarding_debt_{debt_type}")],
            [InlineKeyboardButton(text="✅ Tayyor", callback_data="onboarding_move_to_next")]
        ])
        
        await message.answer(
            f"✅ **{person_name}ga {amount:,.0f} so'm qarz qo'shildi!**\n\n"
            f"{'Qaytarish sanasi: ' + str(due_date) if due_date else ''}\n\n"
            "Yana qarz qo'shmoqchimisiz yoki davom etamizmi?",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    else:
        await message.answer("❌ Summani tushunmadim. Qaytadan kiriting (masalan: Akmal 100000):")

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
    
    # Onboarding tugagach tabrik xabari + menyu bir xabarda
    try:
        await ensure_tariff_valid(user_id)
    except Exception:
        pass
    current_tariff = await get_user_tariff(user_id)
    
    # Menyu tanlash
    if current_tariff == 'FREE':
        menu = get_free_menu()
    elif current_tariff == 'BUSINESS':
        menu = get_business_menu()
    else:
        menu = get_premium_menu()
    
    await callback_query.message.answer_photo(
        photo=FSInputFile('welcome.png'),
        caption=(
            "🎉 **Tabriklaymiz! Onboarding tugadi!**\n\n"
            "Sizning moliyaviy profilingiz tayyor. Endi quyidagi imkoniyatlardan foydalanishingiz mumkin:\n\n"
            "• 💰 Balansni kuzatish\n"
            "• 📊 Moliyaviy hisobotlar\n"
            "• 🤖 AI yordamchi (FREE tarifda cheklangan)\n"
            "• 📱 Qulay interfeys\n\n"
            "Muvaffaqiyatlar! 🚀"
        ),
        reply_markup=menu,
        parse_mode="Markdown"
    )
    
    await state.clear()
    await callback_query.answer("✅ Onboarding yakunlandi!")

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

@dp.callback_query(lambda c: c.data == "back_to_profile")
async def back_to_profile_callback(callback_query: CallbackQuery):
    """Profil menyusiga qaytish"""
    user_id = callback_query.from_user.id
    user_data = await db.get_user_data(user_id)
    
    # Foydalanuvchi tarifini olish
    user_tariff = await get_user_tariff(user_id)
    
    # Yangi yagona profil formatiga mos
    display_name = user_data.get('name', 'Xojayin')
    
    # FREE tarif uchun
    if user_tariff == 'FREE':
        try:
            row = await db.execute_one(
                """
                SELECT COUNT(*) 
                FROM transactions 
                WHERE user_id = %s 
                AND MONTH(created_at) = MONTH(NOW())
                AND YEAR(created_at) = YEAR(NOW())
                """,
                (user_id,)
            )
            monthly_count = row[0] if row else 0
            remaining = max(0, 250 - monthly_count)
            profile_text = (
                f"{display_name} (ID: {user_id})\n\n"
                f"Joriy tarif: Bepul\n"
                f"Tranzaksiyalar: {monthly_count}/250"
            )
        except Exception as e:
            logging.error(f"Error getting monthly stats: {e}")
            profile_text = (
                f"{display_name} (ID: {user_id})\n\n"
                f"Joriy tarif: Bepul"
            )
    elif user_tariff == 'PLUS':
        # PLUS tarif uchun maxsus format
        try:
            row = await db.execute_one(
                """
                SELECT COUNT(*) 
                FROM transactions 
                WHERE user_id = %s 
                AND MONTH(created_at) = MONTH(NOW())
                AND YEAR(created_at) = YEAR(NOW())
                """,
                (user_id,)
            )
            monthly_count = row[0] if row else 0
            
            audio_row = await db.execute_one(
                """
                SELECT COUNT(*) 
                FROM transactions 
                WHERE user_id = %s 
                AND MONTH(created_at) = MONTH(NOW())
                AND YEAR(created_at) = YEAR(NOW())
                AND description LIKE '%voice%'
                """,
                (user_id,)
            )
            audio_count = audio_row[0] if audio_row else 0
            
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
                SELECT COUNT(*) 
                FROM transactions 
                WHERE user_id = %s 
                AND MONTH(created_at) = MONTH(NOW())
                AND YEAR(created_at) = YEAR(NOW())
                """,
                (user_id,)
            )
            monthly_count = row[0] if row else 0
            
            audio_row = await db.execute_one(
                """
                SELECT COUNT(*) 
                FROM transactions 
                WHERE user_id = %s 
                AND MONTH(created_at) = MONTH(NOW())
                AND YEAR(created_at) = YEAR(NOW())
                AND description LIKE '%voice%'
                """,
                (user_id,)
            )
            audio_count = audio_row[0] if audio_row else 0
            
            expires_str = _format_date_uz(user_data['tariff_expires_at']) + " gacha" if user_data.get('tariff_expires_at') else '—'
            
            profile_text = (
                f"{display_name} (ID: {user_id})\n\n"
                f"Tarif: Pro ({expires_str})\n"
                f"Tranzaksiyalar: {monthly_count}/1000\n"
                f"Ovozli Tranzaksiyalar: {audio_count}/500"
            )
        except Exception as e:
            logging.error(f"Error getting PRO stats: {e}")
            expires_str = _format_date_uz(user_data['tariff_expires_at']) + " gacha" if user_data.get('tariff_expires_at') else '—'
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
        tariff_text += "💡 **Max tarifga o'tish uchun:**\n"
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
            await callback_query.message.answer("Max tarif menyusi:", reply_markup=get_premium_menu())
            
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
        "• 1 haftalik bepul sinov qanday?\n"
        "→ Yangi tarifni tanlang > 1 hafta bepul sinash tugmasini bosing\n\n"
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
    
    # 1 haftalik bepul sinov
    if callback_query.data == "duration_trial":
        data = await state.get_data()
        tariff = data.get('selected_tariff')
        
        # Debug: State ma'lumotlarini ko'ramiz
        logging.info(f"Duration trial - State data: {data}")
        logging.info(f"Duration trial - Selected tariff: {tariff}")
        
        if not tariff:
            await callback_query.answer("❌ Tarif topilmadi. Qaytadan boshlang.", show_alert=True)
            return
        
        # Foydalanuvchini tarifga o'tkazish (1 haftalik bepul)
        try:
            from datetime import datetime, timedelta
            
            logging.info(f"Updating user {user_id} tariff to {tariff} with 1 week expiry")
            
            # 1. Users jadvalini yangilash
            await db.execute_query(
                "UPDATE users SET tariff = %s, tariff_expires_at = DATE_ADD(NOW(), INTERVAL 1 WEEK) WHERE user_id = %s",
                (tariff, user_id)
            )
            
            # 2. User subscriptions jadvaliga qo'shish
            expires_at = datetime.now() + timedelta(days=7)
            await db.execute_query(
                "INSERT INTO user_subscriptions (user_id, tariff, is_active, expires_at) VALUES (%s, %s, %s, %s)",
                (user_id, tariff, True, expires_at)
            )
            
            # 3. Payments jadvaliga qo'shish (bepul sinov uchun 0 so'm)
            await db.execute_query(
                "INSERT INTO payments (user_id, tariff, provider, total_amount, currency, status, created_at) VALUES (%s, %s, %s, %s, %s, %s, NOW())",
                (user_id, tariff, 'free_trial', 0, 'UZS', 'paid')
            )
            
            logging.info(f"Successfully updated user {user_id} tariff to {tariff} with full subscription and payment records")
            
            # Tabrik xabari (pullik tariflar kabi)
            await callback_query.message.answer(
                "🎉 **Tabriklaymiz!**\n\n"
                f"✅ Siz {TARIFFS.get(tariff, tariff)} tarifiga ega bo'ldingiz!\n"
                f"⏰ Muddati: 1 hafta (bepul sinov)\n"
                f"📅 Tugash sanasi: {expires_at.strftime('%d.%m.%Y %H:%M')}\n\n"
                "🚀 **Boshlash** tugmasini bosing va onboarding jarayonini boshlaymiz!",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🚀 Boshlash", callback_data="start_onboarding")]
                ]),
                parse_mode='Markdown'
            )
            
            await callback_query.answer("✅ 1 haftalik bepul sinov faollashtirildi!")
            return
            
        except Exception as e:
            logging.error(f"Free trial activation error: {e}")
            await callback_query.answer("❌ Xatolik yuz berdi. Admin bilan bog'laning.", show_alert=True)
            return
    
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

@dp.callback_query(lambda c: not c.data.startswith("trans_") and not c.data.startswith("accept_employee_") and not c.data.startswith("reject_employee") and not c.data.startswith("leave_team") and not c.data.startswith("confirm_leave_team"))
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
    
    # 1 haftalik sinov callbacklari
    if callback_query.data.startswith("free_trial_"):
        tariff_code = callback_query.data.replace("free_trial_", "")
        print(f"DEBUG: Free trial callback received for tariff: {tariff_code}")
        
        # 1 haftalik sinov aktiv qilish
        try:
            from datetime import datetime, timedelta
            
            logging.info(f"Activating free trial for user {user_id} with tariff {tariff_code}")
            
            # 1. Users jadvalini yangilash
            await db.execute_query(
                "UPDATE users SET tariff = %s, tariff_expires_at = DATE_ADD(NOW(), INTERVAL 1 WEEK) WHERE user_id = %s",
                (tariff_code, user_id)
            )
            
            # 2. User subscriptions jadvaliga qo'shish
            expires_at = datetime.now() + timedelta(days=7)
            await db.execute_query(
                "INSERT INTO user_subscriptions (user_id, tariff, is_active, expires_at) VALUES (%s, %s, %s, %s)",
                (user_id, tariff_code, True, expires_at)
            )
            
            # 3. Payments jadvaliga qo'shish (bepul sinov uchun 0 so'm)
            await db.execute_query(
                "INSERT INTO payments (user_id, tariff, provider, total_amount, currency, status, created_at) VALUES (%s, %s, %s, %s, %s, %s, NOW())",
                (user_id, tariff_code, 'free_trial', 0, 'UZS', 'paid')
            )
            
            logging.info(f"Successfully activated free trial for user {user_id} with tariff {tariff_code}")
            
            # Tabrik xabari
            await callback_query.message.answer(
                "🎉 **Tabriklaymiz!**\n\n"
                f"✅ Siz {TARIFFS.get(tariff_code, tariff_code)} tarifiga ega bo'ldingiz!\n"
                f"⏰ Muddati: 1 hafta (bepul sinov)\n"
                f"📅 Tugash sanasi: {expires_at.strftime('%d.%m.%Y %H:%M')}\n\n"
                "🚀 **Boshlash** tugmasini bosing va onboarding jarayonini boshlaymiz!",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🚀 Boshlash", callback_data="start_onboarding")]
                ]),
                parse_mode='Markdown'
            )
            
            await callback_query.answer("✅ 1 haftalik bepul sinov faollashtirildi!")
            return
            
        except Exception as e:
            logging.error(f"Free trial activation error: {e}")
            await callback_query.answer("❌ Xatolik yuz berdi. Admin bilan bog'laning.", show_alert=True)
            return

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

        # State ga selected_tariff ni saqlaymiz
        await state.update_data(selected_tariff=tariff)
        
        keyboard = build_tariff_detail_keyboard(tariff, back_callback)
        await callback_query.message.edit_text(detail_text, reply_markup=keyboard, parse_mode='Markdown')
        await callback_query.answer()
        return

    # Boshqa holatlar yuqorida qayta ishlangan
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
            "UPDATE users SET tariff = 'FREE', manager_id = NULL WHERE user_id = %s",
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
@dp.message(lambda message: message.text and not message.text.startswith('/') and message.text not in ["📊 Hisobotlar", "👤 Profil", "➕ Kirim", "➖ Chiqim", "💳 Qarzlar", "➕ Xodim qo'shish", "❌ Bekor qilish"])
async def process_financial_message(message: types.Message, state: FSMContext):
    """MAX va FREE tariflar uchun AI chat"""
    user_id = message.from_user.id
    
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
    
    # PLUS tarif uchun financial_module ishlaydi
    if user_tariff == 'PLUS':
        # "Bajarilyapti..." xabari
        processing_msg = await message.answer("🔄 Bajarilyapti...")
        
        # PLUS uchun financial_module orqali qayta ishlaymiz
        text = message.text
        result = await financial_module.process_ai_input_advanced(text, user_id)
        
        # Processing xabarni o'chirish
        try:
            await processing_msg.delete()
        except:
            pass
        
        if result.get('success'):
            # Agar tranzaksiya tasdiqlangan bo'lsa, tugmalar bilan yuborish
            if 'transaction_data' in result:
                # State ga transaction_data ni saqlash
                await state.update_data(transaction_data=result['transaction_data'])
                
                transaction_type = result.get('type', '')
                buttons = financial_module.generate_transaction_buttons({
                    'transactions': result['transaction_data'].get('transactions', []),
                    'type': transaction_type
                })
                
                if buttons:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text=btn['text'], callback_data=btn['callback_data'])] 
                        for row in buttons for btn in row
                    ])
                    # Javob va tugmalar bir xabarda
                    await message.answer(result['message'], parse_mode='Markdown', reply_markup=keyboard)
                else:
                    await message.answer(result['message'], parse_mode='Markdown')
            else:
                await message.answer(result['message'], parse_mode='Markdown')
        else:
            # Xatolik xabari
            await message.answer(result.get('message', '❌ Xatolik yuz berdi.'), parse_mode='Markdown')
        
        return
    
    # Faqat MAX va FREE tariflar uchun
    if user_tariff not in ['PRO', 'FREE']:
        return
    
    # State'lar tekshiruvi
    if await state.get_state() in [UserStates.waiting_for_phone, UserStates.waiting_for_name, 
                                   UserStates.waiting_for_source, UserStates.waiting_for_tariff,
                                   UserStates.waiting_for_amount, UserStates.waiting_for_description, 
                                   UserStates.waiting_for_category, UserStates.waiting_for_debt_type,
                                   UserStates.waiting_for_debt_person]:
        return
    
    text = message.text
    
    # AI ishlash ko'rsatkich
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    try:
        if user_tariff == 'PRO':
            # PRO tarif uchun to'liq AI chat
            ai_messages = await ai_chat.generate_response(user_id, text)
            
            # Har bir xabarni 1-3 soniya orasida yuborish
            for msg in ai_messages:
                await message.answer(msg, parse_mode='Markdown')
                await asyncio.sleep(1.5)
        
        elif user_tariff == 'FREE':
            # FREE tarif uchun cheklangan AI chat
            # "Bajarilmoqda..." xabarini yuborish
            processing_msg = await message.answer("🔄 Bajarilmoqda...")
            
            ai_messages = await ai_chat_free.generate_response(user_id, text)
            
            # "Bajarilmoqda..." xabarini o'chirish
            try:
                await processing_msg.delete()
            except:
                pass
            
            # Faqat bir xabar yuborish
            for msg in ai_messages:
                await message.answer(msg)
        
    except Exception as e:
        logging.error(f"AI chat xatolik: {e}")
        await message.answer("Kechirasiz, xatolik yuz berdi. Iltimos, qayta urinib ko'ring.")

async def process_google_audio(message: types.Message, state: FSMContext, audio_path: str, user_id: int):
    """Google Cloud Speech natijalarini alohida qayta ishlash"""
    try:
        # Google Cloud Speech-to-Text ni ishga tushirish
        google_result = await financial_module.process_audio_input(audio_path, user_id)
        
        # Google natijasini yuborish
        if google_result['success']:
            if google_result.get('type') == 'single_confirmation':
                # Bitta tranzaksiya tasdiqlash
                await state.set_state(UserStates.waiting_for_transaction_confirmation)
                await state.update_data(transaction_data=google_result['transaction_data'])
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💾 Saqlash", callback_data="trans_single")],
                    [InlineKeyboardButton(text="🗑️ O'chirish", callback_data="trans_cancel_single")]
                ])
                
                await message.answer(google_result['message'], parse_mode='Markdown', reply_markup=keyboard)
                
            elif google_result.get('type') == 'multiple_preview':
                # Ko'p tranzaksiyalar oldindan ko'rinishi
                await state.set_state(UserStates.waiting_for_transaction_confirmation)
                await state.update_data(transaction_data=google_result['buttons_data'])
                
                # Tugmalarni yaratish
                buttons_data = google_result['buttons_data']
                transactions = buttons_data.get('transactions', [])
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[])
                
                # Har bir tranzaksiya uchun tugma
                for trans in transactions:
                    if trans['status'] == 'confirmed':
                        emoji = "💾" if trans['data']['type'] == 'expense' else "💰"
                        button_text = f"{emoji} #{trans['index']}"
                        keyboard.inline_keyboard.append([
                            InlineKeyboardButton(text=button_text, callback_data=f"trans_toggle_{trans['index']}")
                        ])
                
                # Umumiy boshqaruv tugmalari
                keyboard.inline_keyboard.append([
                    InlineKeyboardButton(text="✅ Hammasini saqlash", callback_data="trans_save_all"),
                    InlineKeyboardButton(text="❌ Hammasini bekor qilish", callback_data="trans_cancel_all")
                ])
                
                await message.answer(google_result['message'], parse_mode='Markdown', reply_markup=keyboard)
            
            elif google_result.get('type') == 'completed':
                # Natijani ko'rsatish
                await message.answer(google_result['message'], parse_mode='Markdown')
            
            else:
                # Oddiy natija
                await message.answer(google_result['message'], parse_mode='Markdown')
        else:
            # Xatolik yuz berdi
            await message.answer(google_result['message'], parse_mode='Markdown')
    
    except Exception as e:
        logging.error(f"Google background task error: {e}")


# Audio xabarlarni qayta ishlash (Premium)
@dp.message(lambda message: message.voice or message.audio)
async def process_audio_message(message: types.Message, state: FSMContext):
    """Audio xabarlarni qayta ishlash (Premium)"""
    user_id = message.from_user.id
    # Avtomatik tarif muddatini tekshirish
    await ensure_tariff_valid(user_id)
    user_tariff = await get_user_tariff(user_id)
    
    # FREE tarif uchun audio qo'llab-quvvatlash yo'q
    if user_tariff == 'FREE':
        await message.answer(
            "🎵 **Audio qo'llab-quvvatlash**\n\n"
            "Audio xabarlarni qayta ishlash faqat Plus va Max tariflarda mavjud.\n"
            "Plus tarifga o'tish uchun Profil > Tarif bo'limiga o'ting.",
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
        
        # Google Cloud Speech-to-Text
        if ACTIVE_SPEECH_MODELS['GOOGLE']:
            await process_google_audio(message, state, audio_path, user_id)
        else:
            await processing_msg.delete()
            await message.answer(
                "❌ Hozircha speech model yoqilmagan. Admin bilan bog'laning.",
                parse_mode='Markdown'
            )
        
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
        "Max tarif menyusi:",
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
        "Max tarif menyusi:",
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

            # To'lovdan so'ng onboarding holatini tekshiramiz
            try:
                balance_query = """
                SELECT COUNT(*) FROM transactions 
                WHERE user_id = %s AND category IN ('boshlang_ich_naqd', 'boshlang_ich_karta')
                """
                result = await db.execute_one(balance_query, (user_id,))
                has_initial_balance = result and result[0] > 0
            except Exception:
                has_initial_balance = True

            # To'lov muvaffaqiyatli bo'lgach rasmli xabar
            user_name = await get_user_name(user_id)
            await message.answer_photo(
                photo=FSInputFile('welcome.png'),
                caption=(
                    f"🎉 **To'lov muvaffaqiyatli!**\n\n"
                    f"Raxmat, {user_name}!\n\n"
                    f"✨ **Plus tarif aktivlashtirildi**\n\n"
                    f"Endi siz quyidagi imkoniyatlardan foydalanishingiz mumkin:\n"
                    f"• AI yordamida ovozli va matnli kiritish\n"
                    f"• Tezkor moliyaviy tahlillar\n"
                    f"• Shaxsiy byudjetni kuzatish\n"
                    f"• Cheksiz tranzaksiyalar\n\n"
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
                if current_tariff == 'FREE':
                    await message.answer(
                        "Bepul tarif menyusi:",
                        reply_markup=get_free_menu()
                    )
                elif current_tariff == 'BUSINESS':
                    await message.answer(
                        "Business tarif menyusi:",
                        reply_markup=get_business_menu()
                    )
                else:
                    await message.answer(
                        "Plus tarif menyusi:",
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

            # To'lovdan so'ng onboarding holatini tekshiramiz
            try:
                balance_query = """
                SELECT COUNT(*) FROM transactions 
                WHERE user_id = %s AND category IN ('boshlang_ich_naqd', 'boshlang_ich_karta')
                """
                result = await db.execute_one(balance_query, (user_id,))
                has_initial_balance = result and result[0] > 0
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
                if current_tariff == 'FREE':
                    await message.answer(
                        "Bepul tarif menyusi:",
                        reply_markup=get_free_menu()
                    )
                elif current_tariff == 'BUSINESS':
                    await message.answer(
                        "Business tarif menyusi:",
                        reply_markup=get_business_menu()
                    )
                else:
                    await message.answer(
                        "Plus tarif menyusi:",
                        reply_markup=get_premium_menu()
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

# Mini-app uchun authentication
def verify_telegram_auth(init_data: str) -> dict:
    """Telegram Mini App authentication tekshirish"""
    try:
        import hashlib
        import hmac
        from urllib.parse import parse_qsl
        
        if not init_data:
            return None
            
        # init_data ni parse qilish
        parsed_data = dict(parse_qsl(init_data))
        
        # hash ni olish
        received_hash = parsed_data.pop('hash', '')
        
        # Secret key ni olish (bot token dan)
        secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
        
        # Data string yaratish
        data_check_string = '\n'.join([f"{k}={v}" for k, v in sorted(parsed_data.items())])
        
        # Hash hisoblash
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        # Hash tekshirish
        if calculated_hash != received_hash:
            return None
            
        return parsed_data
    except Exception as e:
        logging.error(f"Telegram auth verification error: {e}")
        return None

# Mini-app uchun API endpoints
@app.get("/api/user/{user_id}")
async def get_user_data(user_id: int, init_data: str = None):
    """Foydalanuvchi ma'lumotlarini olish mini-app uchun"""
    try:
        # Authentication tekshirish (agar init_data berilgan bo'lsa)
        if init_data:
            auth_data = verify_telegram_auth(init_data)
            if not auth_data:
                raise HTTPException(status_code=401, detail="Authentication failed")
        
        # Foydalanuvchi ma'lumotlarini olish
        user_data = await db.fetch_one("SELECT * FROM users WHERE user_id = %s", (user_id,))
        if not user_data:
            raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")
        
        # Balans ma'lumotlarini olish
        balance = await db.get_balance(user_id)
        
        # So'nggi tranzaksiyalar
        recent_transactions = await db.fetch_all(
            "SELECT * FROM transactions WHERE user_id = %s ORDER BY created_at DESC LIMIT 10",
            (user_id,)
        )
        
        # Tarif ma'lumotlari
        tariff = user_data.get('tariff', 'FREE')
        tariff_name = TARIFFS.get(tariff, 'Bepul')
        
        return {
            "success": True,
            "user": {
                "user_id": user_id,
                "name": user_data.get('name', 'Foydalanuvchi'),
                "tariff": tariff,
                "tariff_name": tariff_name,
                "phone": user_data.get('phone', ''),
                "created_at": user_data.get('created_at').isoformat() if user_data.get('created_at') else None
            },
            "balance": balance,
            "recent_transactions": recent_transactions
        }
    except Exception as e:
        logging.error(f"Mini-app API xatolik: {e}")
        raise HTTPException(status_code=500, detail="Server xatoligi")

@app.get("/api/transactions/{user_id}")
async def get_transactions(user_id: int, limit: int = 50, offset: int = 0, init_data: str = None):
    """Tranzaksiyalar ro'yxatini olish"""
    try:
        transactions = await db.fetch_all(
            "SELECT * FROM transactions WHERE user_id = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (user_id, limit, offset)
        )
        return {
            "success": True,
            "transactions": transactions,
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        logging.error(f"Tranzaksiyalar olishda xatolik: {e}")
        raise HTTPException(status_code=500, detail="Server xatoligi")

@app.get("/api/stats/{user_id}")
async def get_user_stats(user_id: int, init_data: str = None):
    """Foydalanuvchi statistikalarini olish"""
    try:
        # Oylik statistikalar
        current_month = datetime.now().strftime('%Y-%m')
        
        monthly_income = await db.execute_one(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE user_id = %s AND transaction_type = 'income' AND DATE_FORMAT(created_at, '%%Y-%%m') = %s",
            (user_id, current_month)
        )
        
        monthly_expense = await db.execute_one(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE user_id = %s AND transaction_type = 'expense' AND DATE_FORMAT(created_at, '%%Y-%%m') = %s",
            (user_id, current_month)
        )
        
        # Tranzaksiyalar soni
        total_transactions = await db.execute_one(
            "SELECT COUNT(*) FROM transactions WHERE user_id = %s",
            (user_id,)
        )
        
        return {
            "success": True,
            "stats": {
                "monthly_income": float(monthly_income[0]) if monthly_income else 0,
                "monthly_expense": float(monthly_expense[0]) if monthly_expense else 0,
                "total_transactions": total_transactions[0] if total_transactions else 0,
                "month": current_month
            }
        }
    except Exception as e:
        logging.error(f"Statistika olishda xatolik: {e}")
        raise HTTPException(status_code=500, detail="Server xatoligi")

@app.get("/api/auth")
async def get_auth_info(init_data: str):
    """Telegram Mini App authentication ma'lumotlarini olish"""
    try:
        auth_data = verify_telegram_auth(init_data)
        if not auth_data:
            raise HTTPException(status_code=401, detail="Authentication failed")
        
        user_id = int(auth_data.get('user', {}).get('id', 0))
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")
        
        return {
            "success": True,
            "user_id": user_id,
            "user_data": auth_data.get('user', {})
        }
    except Exception as e:
        logging.error(f"Auth info error: {e}")
        raise HTTPException(status_code=500, detail="Server xatoligi")

@app.get("/api/tariffs")
async def get_tariffs():
    """Tariflar ro'yxatini qaytarish"""
    try:
        tariffs = [
            {"code": "PLUS", "name": "Plus", "monthly_price": 19990},
            {"code": "PRO", "name": "Pro", "monthly_price": 199900},
            {"code": "BUSINESS", "name": "Business", "monthly_price": 299900},
        ]
        
        discount_rates = {
            1: 0,
            3: 5,
            6: 10,
            12: 20
        }
        
        return {
            "tariffs": tariffs,
            "discount_rates": discount_rates
        }
    except Exception as e:
        logging.error(f"Get tariffs error: {e}")
        raise HTTPException(status_code=500, detail="Server xatoligi")

@app.post("/api/payment/webhook")
async def payment_webhook(data: dict):
    """Mini ilova dan to'lov ma'lumotlarini qabul qilish"""
    try:
        logging.info(f"Payment webhook received: {data}")
        
        user_id = data.get("user_id")
        tariff = data.get("tariff")
        months = data.get("months", 1)
        amount = data.get("amount")
        payment_method = data.get("payment_method", "test")
        
        logging.info(f"Processing payment for user {user_id}, tariff {tariff}, months {months}")
        
        # To'lovni tasdiqlash va tarifni aktiv qilish
        from datetime import datetime, timedelta
        expires_at = datetime.now() + timedelta(days=30 * months)
        
        await db.add_user_subscription(user_id, tariff, expires_at)
        await db.set_active_tariff(user_id, tariff)
        
        # To'lov yozuvini saqlash
        await db.execute_insert(
            """
            INSERT INTO payments (user_id, tariff, provider, total_amount, currency, status, paid_at)
            VALUES (%s, %s, %s, %s, %s, 'paid', NOW())
            """,
            (user_id, tariff, payment_method, amount, 'UZS')
        )
        
        # Foydalanuvchiga tabrik xabari yuborish
        user_data = await db.get_user_data(user_id)
        user_name = user_data.get('name', 'Xojayin') if user_data else 'Xojayin'
        
        tariff_name = TARIFFS.get(tariff, tariff)
        expires_str = _format_date_uz(expires_at) + " gacha"
        
        tariff_info = ""
        if tariff == 'PLUS':
            tariff_info = "\n• Tranzaksiyalar: 500 ta/oy\n• Ovozli Tranzaksiyalar: 250 ta/oy"
        elif tariff == 'PRO':
            tariff_info = "\n• Tranzaksiyalar: 1 000 ta/oy\n• Ovozli Tranzaksiyalar: 500 ta/oy"
        
        try:
            logging.info(f"Sending payment confirmation message to user {user_id}")
            # Tabrik xabarini rasmli ko'rinishda yuborish
            await bot.send_photo(
                chat_id=user_id,
                photo=FSInputFile('welcome.png'),
                caption=(
                    f"🎉 *Tabriklaymiz, {user_name}!*\n\n"
                    f"✅ *To'lov muvaffaqiyatli amalga oshirildi!*\n\n"
                    f"📦 **Tarif:** {tariff_name}\n"
                    f"⏰ **Muddati:** {expires_str}\n"
                    f"{tariff_info}\n\n"
                    f"🚀 *Endi sizning botingiz tayyor!*"
                ),
                parse_mode='Markdown'
            )
            logging.info(f"Payment confirmation message sent successfully to user {user_id}")
        except Exception as e:
            logging.error(f"Error sending photo message: {e}")
            # Agar rasm yuborishda xatolik bo'lsa, oddiy matn yuborish
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"🎉 Tabriklaymiz, {user_name}!\n\n"
                        f"✅ To'lov muvaffaqiyatli amalga oshirildi!\n\n"
                        f"📦 Tarif: {tariff_name}\n"
                        f"⏰ Muddati: {expires_str}\n"
                        f"{tariff_info}\n\n"
                        f"🚀 Endi sizning botingiz tayyor!"
                    )
                )
                logging.info(f"Payment confirmation text message sent to user {user_id}")
            except Exception as e2:
                logging.error(f"Error sending text message: {e2}")
        
        return {
            "success": True,
            "message": "To'lov muvaffaqiyatli amalga oshirildi",
            "new_tariff": tariff,
            "expires_at": expires_at.isoformat()
        }
    except Exception as e:
        logging.error(f"Payment webhook error: {e}")
        raise HTTPException(status_code=500, detail="Server xatoligi")



async def load_config_from_db():
    """Bazadan sozlamalarni yuklab olish"""
    try:
        # Speech models
        result = await db.execute_one("SELECT value FROM config WHERE key_name = 'active_speech_google'")
        if result:
            ACTIVE_SPEECH_MODELS['GOOGLE'] = result[0].lower() == 'true'
        
        # Free trials
        result = await db.execute_one("SELECT value FROM config WHERE key_name = 'free_trial_plus'")
        if result:
            FREE_TRIAL_ENABLED['PLUS'] = result[0].lower() == 'true'
        
        result = await db.execute_one("SELECT value FROM config WHERE key_name = 'free_trial_max'")
        if result:
            FREE_TRIAL_ENABLED['PRO'] = result[0].lower() == 'true'
        
        result = await db.execute_one("SELECT value FROM config WHERE key_name = 'free_trial_business'")
        if result:
            FREE_TRIAL_ENABLED['BUSINESS'] = result[0].lower() == 'true'
        
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
    tariff = data.get('onboarding_tariff', 'FREE')
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
    tariff = data.get('onboarding_tariff', 'FREE')
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

@app.on_event("startup")
async def startup_event():
    """FastAPI ishga tushganda bot ni ham ishga tushirish"""
    try:
        print("🚀 Bot ishga tushmoqda...")
        asyncio.create_task(start_bot())
        print("✅ Bot muvaffaqiyatli ishga tushdi!")
    except Exception as e:
        print(f"❌ Bot ishga tushishda xatolik: {e}")
        logging.error(f"Bot startup xatolik: {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # FastAPI ni ishga tushirish (bot ham parallel ishlaydi)
    uvicorn.run(app, host="0.0.0.0", port=8001)