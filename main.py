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
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, Contact
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, TARIFFS, CATEGORIES
from database import db
from financial_module import FinancialModule
from reports_module import ReportsModule

# Bot va dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Modullar
financial_module = FinancialModule()
reports_module = ReportsModule()

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

# Bepul tarif menyusi
def get_free_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Kirim"), KeyboardButton(text="➖ Chiqim")],
            [KeyboardButton(text="💳 Qarzlar"), KeyboardButton(text="📊 Hisobotlar")],
            [KeyboardButton(text="👤 Profil")]
        ],
        resize_keyboard=True
    )
    return keyboard

# Premium tarif menyusi
def get_premium_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Hisobotlar"), KeyboardButton(text="👤 Profil")]
        ],
        resize_keyboard=True
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

# Profil menyusi
def get_profile_menu():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data="settings")],
            [InlineKeyboardButton(text="💳 Tarif", callback_data="tariff_info")],
            [InlineKeyboardButton(text="🔄 Tarifni o'zgartirish", callback_data="change_tariff")]
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
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🆓 Bepul", callback_data="tariff_FREE")],
            [InlineKeyboardButton(text="⭐ Premium", callback_data="tariff_PREMIUM")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_profile")]
        ]
    )
    return keyboard

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
    """Foydalanuvchi tarifini olish"""
    try:
        query = "SELECT tariff FROM users WHERE user_id = %s"
        result = await db.execute_one(query, (user_id,))
        return result[0] if result else "FREE"
    except:
        return "FREE"

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
    if user_data and user_data.get('phone'):
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
        else:
            await message.answer(
                f"👋 Salom, {user_name}!\n\n"
                "Balans AI Premium ga xush kelibsiz!\n\n"
                "Matn yoki ovozli xabar yuboring va AI avtomatik qayta ishlaydi:",
                reply_markup=get_premium_menu(),
                parse_mode="Markdown"
            )
    else:
        # Yangi foydalanuvchi - onboarding
        await message.answer(
            "🤖 *Balans AI* ga xush kelibsiz!\n\n"
            "Men sizning shaxsiy moliyaviy yordamchingizman. "
            "Sizning barcha moliyaviy ma'lumotlaringizni boshqarishga yordam beraman.\n\n"
            "📊 *Asosiy imkoniyatlar:*\n"
            "• Kirim va chiqimlarni kuzatish\n"
            "• Qarzlar boshqaruvi\n"
            "• Batafsil hisobotlar\n"
            "• AI yordamchi (Premium)\n\n"
            "📱 *Davom etish uchun telefon raqamingizni yuboring:*",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)]],
                resize_keyboard=True
            ),
            parse_mode="Markdown"
        )
        await state.set_state(UserStates.waiting_for_phone)

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
        reply_markup=ReplyKeyboardMarkup(keyboard=[], resize_keyboard=True),
        parse_mode="Markdown"
    )
    await state.set_state(UserStates.waiting_for_name)

# Ism qabul qilish
@dp.message(UserStates.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    """Ismni qabul qilish"""
    user_id = message.from_user.id
    name = message.text.strip()
    
    if not name or name.lower() in ['skip', 'otkazib yuborish', 'otkazib', '']:
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
    
    await callback_query.message.edit_text(
        "✅ *Manba saqlandi!*\n\n"
        "Endi tarifingizni tanlang:",
        reply_markup=get_tariff_menu(),
        parse_mode="Markdown"
    )
    await state.set_state(UserStates.waiting_for_tariff)

# Tarif tanlash
@dp.callback_query(lambda c: c.data.startswith("tariff_"), UserStates.waiting_for_tariff)
async def process_tariff(callback_query: CallbackQuery, state: FSMContext):
    """Tarifni qabul qilish"""
    user_id = callback_query.from_user.id
    tariff = callback_query.data.split("_")[1]
    
    # Tarifni saqlash
    await db.execute_query(
        "UPDATE users SET tariff = %s WHERE user_id = %s",
        (tariff, user_id)
    )
    
    user_name = await get_user_name(user_id)
    
    if tariff == "FREE":
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
    else:
        await callback_query.message.edit_text(
            f"✅ *Premium tarif tanlandi!*\n\n"
            f"Salom, {user_name}!\n\n"
            "Matn yoki ovozli xabar yuboring va AI avtomatik qayta ishlaydi:",
            parse_mode="Markdown"
        )
        await callback_query.message.answer(
            "Premium tarif menyusi:",
            reply_markup=get_premium_menu()
        )
    
    await state.clear()

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
    
    await message.answer(
        "📂 *Kategoriyani tanlang:*",
        reply_markup=get_income_category_menu(),
        parse_mode="Markdown"
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
        await db.execute_query(
            "INSERT INTO transactions (user_id, transaction_type, amount, category, description) VALUES (%s, %s, %s, %s, %s)",
            (user_id, transaction_type, amount, category, description)
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
        message_text += "📱 *Kengaytirilgan hisobotlar*\n\n"
        message_text += "Kengaytirilgan hisobotlar va grafiklar uchun Premium tarifga o'ting.\n"
        message_text += "Tarifni o'zgartirish uchun Profil > Tarif bo'limiga o'ting."
        
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
    
    # Profil ma'lumotlarini tayyorlash
    profile_text = f"👤 **Profil ma'lumotlari**\n\n"
    profile_text += f"🆔 **Telegram ID:** `{user_id}`\n"
    profile_text += f"📅 **Ro'yxatdan o'tgan sana:** {user_data['created_at'].strftime('%d.%m.%Y')}\n"
    profile_text += f"💳 **Tarif:** {TARIFFS.get(user_data['tariff'], 'Nomalum')}\n"
    profile_text += f"👤 **Ism:** {user_data.get('name', 'Nomalum')}\n"
    if user_data.get('phone'):
        profile_text += f"📱 **Telefon:** {user_data['phone']}\n"
    
    # Agar pullik tarif bo'lsa, muddatini ko'rsatish
    if user_data['tariff'] in ['PRO', 'MAX', 'PREMIUM'] and user_data.get('tariff_expires_at'):
        profile_text += f"⏰ **Faol bo'lish muddati:** {user_data['tariff_expires_at'].strftime('%d.%m.%Y %H:%M')}\n"
    elif user_data['tariff'] in ['PRO', 'MAX', 'PREMIUM']:
        profile_text += f"⏰ **Faol bo'lish muddati:** Cheksiz\n"
    
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
    """Tarifni o'zgartirish"""
    user_id = callback_query.from_user.id
    user_data = await db.get_user_data(user_id)
    
    if not user_data:
        await callback_query.message.edit_text("❌ Foydalanuvchi ma'lumotlari topilmadi!")
        return
    
    current_tariff = user_data['tariff']
    
    text = f"🔄 **Tarifni o'zgartirish**\n\n"
    text += f"🎯 **Joriy tarif:** {TARIFFS.get(current_tariff, 'Nomalum')}\n\n"
    text += "Yangi tarifni tanlang:"
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🆓 Bepul tarif", callback_data="change_to_FREE")],
            [InlineKeyboardButton(text="💎 Premium tarif", callback_data="change_to_PREMIUM")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_profile")]
        ]
    )
    
    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode='Markdown')
    await callback_query.answer()

@dp.callback_query(lambda c: c.data.startswith("change_to_"))
async def process_tariff_change(callback_query: CallbackQuery):
    """Tarif o'zgartirishni qayta ishlash"""
    user_id = callback_query.from_user.id
    new_tariff = callback_query.data.replace("change_to_", "")
    
    # Tarifni yangilash
    await update_user_tariff(user_id, new_tariff)
    
    user_name = await get_user_name(user_id)
    
    if new_tariff == "FREE":
        await callback_query.message.edit_text(
            f"✅ *Bepul tarifga o'tildi!*\n\n"
            f"Salom, {user_name}!\n\n"
            "Quyidagi tugmalardan foydalaning:",
            parse_mode="Markdown"
        )
        await callback_query.message.answer(
            "Bepul tarif menyusi:",
            reply_markup=get_free_menu()
        )
    else: # PREMIUM
        await callback_query.message.edit_text(
            f"✅ *Premium tarifga o'tildi!*\n\n"
            f"Salom, {user_name}!\n\n"
            "Matn yoki ovozli xabar yuboring va AI avtomatik qayta ishlaydi:",
            parse_mode="Markdown"
        )
        await callback_query.message.answer(
            "Premium tarif menyusi:",
            reply_markup=get_premium_menu()
        )
    
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "tariff_info")
async def tariff_info_callback(callback_query: CallbackQuery):
    """Tarif ma'lumotlarini ko'rsatish"""
    text = """💳 **Tariflar**

🆓 **Bepul**
• Qo'lda kirim/chiqim kiritish
• Asosiy hisobotlar
• 10 ta tranzaksiya/oy

⭐ **Premium - 50,000 so'm/oy**
• AI yordamida avtomatik qayta ishlash
• Ovozli xabarlar qo'llab-quvvatlash
• Kengaytirilgan hisobotlar
• Cheksiz tranzaksiyalar

Tarifni tanlang:"""
    
    keyboard = get_tariff_menu()
    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode='Markdown')
    await callback_query.answer()

@dp.callback_query(lambda c: c.data.startswith("tariff_") and c.data.split("_")[1] in ["FREE", "PREMIUM"])
async def process_tariff_selection(callback_query: CallbackQuery):
    """Tarif tanlashni qayta ishlash"""
    tariff = callback_query.data.split("_")[1]
    user_id = callback_query.from_user.id
    
    # Tarifni yangilash
    await db.execute_query(
        "UPDATE users SET tariff = %s WHERE user_id = %s",
        (tariff, user_id)
    )
    
    tariff_name = TARIFFS.get(tariff, "Nomalum")
    user_name = await get_user_name(user_id)
    
    if tariff == "FREE":
        message = f"✅ Tarif '{tariff_name}' ga o'zgartirildi!\n\nSalom, {user_name}!\n\nQuyidagi tugmalardan foydalaning:"
        keyboard = get_free_menu()
    else:
        message = f"✅ Tarif '{tariff_name}' ga o'zgartirildi!\n\nSalom, {user_name}!\n\nMatn yoki ovozli xabar yuboring va AI avtomatik qayta ishlaydi:"
        keyboard = get_premium_menu()
    
    await callback_query.message.edit_text(message, reply_markup=keyboard, parse_mode='Markdown')
    await callback_query.answer()

# Premium tarif - AI yordamida moliyaviy ma'lumotlarni qayta ishlash
@dp.message(lambda message: message.text and not message.text.startswith('/') and message.text not in ["📊 Hisobotlar", "👤 Profil", "➕ Kirim", "➖ Chiqim", "💳 Qarzlar"])
async def process_financial_message(message: types.Message, state: FSMContext):
    """Moliyaviy ma'lumotlarni qayta ishlash (Premium)"""
    user_id = message.from_user.id
    user_tariff = await get_user_tariff(user_id)
    
    # Faqat Premium tarif uchun AI qayta ishlash
    if user_tariff not in ['PRO', 'MAX', 'PREMIUM']:
        return
    
    # Agar foydalanuvchi boshqa holatda bo'lsa
    if await state.get_state() in [UserStates.waiting_for_phone, UserStates.waiting_for_name, 
                                   UserStates.waiting_for_source, UserStates.waiting_for_tariff,
                                   UserStates.waiting_for_amount, UserStates.waiting_for_description, 
                                   UserStates.waiting_for_category]:
        return
    
    text = message.text
    
    # AI yordamida moliyaviy ma'lumotni qayta ishlash
    result = await financial_module.process_ai_input(text, user_id)
    
    if result['success']:
        await message.answer(result['message'], parse_mode='Markdown')
    else:
        await message.answer(result['message'], parse_mode='Markdown')

# Audio xabarlarni qayta ishlash (Premium)
@dp.message(lambda message: message.voice or message.audio)
async def process_audio_message(message: types.Message, state: FSMContext):
    """Audio xabarlarni qayta ishlash (Premium)"""
    user_id = message.from_user.id
    user_tariff = await get_user_tariff(user_id)
    
    # Faqat Premium tarif uchun audio qo'llab-quvvatlash
    if user_tariff not in ['PRO', 'MAX', 'PREMIUM']:
        await message.answer(
            "🎵 **Audio qo'llab-quvvatlash**\n\n"
            "Audio xabarlarni qayta ishlash faqat Premium tarifda mavjud.\n"
            "Tarifni yangilash uchun Profil > Tarif bo'limiga o'ting.",
            parse_mode='Markdown'
        )
        return
    
    # Agar foydalanuvchi boshqa holatda bo'lsa
    if await state.get_state() in [UserStates.waiting_for_phone, UserStates.waiting_for_name, 
                                   UserStates.waiting_for_source, UserStates.waiting_for_tariff,
                                   UserStates.waiting_for_amount, UserStates.waiting_for_description, 
                                   UserStates.waiting_for_category]:
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
        
        # Audio faylni qayta ishlash
        result = await financial_module.process_audio_input(audio_path, user_id)
        
        # Natijani yuborish
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