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

# Bepul tarif menyusi
def get_free_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Kirim"), KeyboardButton(text="➖ Chiqim")],
            [KeyboardButton(text="💳 Qarzlar"), KeyboardButton(text="📊 Hisobotlar")],
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
            [KeyboardButton(text="📊 Hisobotlar"), KeyboardButton(text="👤 Profil")]
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
            [InlineKeyboardButton(text="🔄 O'zgartirish", callback_data="change_tariff")]
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
            [InlineKeyboardButton(text="🆓 Bepul (davom etish)", callback_data="tariff_FREE")],
            [InlineKeyboardButton(text="⭐ Premium (To'lov qilish)", callback_data="tariff_PREMIUM")]
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
            f"✅ *Bepul (davom etish) tanlandi!*\n\n"
            f"Salom, {user_name}!\n\n"
            "Quyidagi tugmalardan foydalaning:",
            parse_mode="Markdown"
        )
        await callback_query.message.answer(
            "Bepul tarif menyusi:",
            reply_markup=get_free_menu()
        )
    else:
        # Premium tanlanganda onboarding final step boshlanadi
        await callback_query.message.edit_text(
            f"🎉 *Tabriklaymiz! Siz Premium foydalanuvchiga aylandingiz.*\n\n"
            f"Endi hisobingizni o'z ehtiyojlaringizga moslab sozlab olishingiz mumkin.\n"
            f"Hozircha faqat bitta sozlama mavjud — *Daromad sozlamalari.*\n"
            f"(Kelajakda yangi sozlamalar qo'shamiz. Har doim Profil > Sozlamalardan o'zgartirish mumkin.)",
            parse_mode="Markdown"
        )
        
        # Onboarding final step tugmalari
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Sozlashni boshlash", callback_data="start_income_setup")],
            [InlineKeyboardButton(text="⏭ Keyinga o'tish", callback_data="skip_income_setup")]
        ])
        await callback_query.message.answer(
            "Daromad sozlamalarini sozlashni xohlaysizmi?",
            reply_markup=keyboard
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
    
    # Profil ma'lumotlarini tayyorlash (qisqartirilgan)
    profile_text = f"👤 **Profil**\n\n"
    profile_text += f"🆔 ID: `{user_id}`\n"
    profile_text += f"📅 Ro'yxat: {user_data['created_at'].strftime('%d.%m.%Y')}\n"
    profile_text += f"💳 Tarif: {TARIFFS.get(user_tariff, 'Nomalum')}\n"
    profile_text += f"👤 Ism: {user_data.get('name', 'Nomalum')}\n"
    if user_data.get('phone'):
        profile_text += f"📱 Tel: {user_data['phone']}\n"
    
    # Agar pullik tarif bo'lsa, muddatini ko'rsatish
    if user_tariff in ['PRO', 'MAX', 'PREMIUM'] and user_data.get('tariff_expires_at'):
        profile_text += f"⏰ Muddati: {user_data['tariff_expires_at'].strftime('%d.%m.%Y')}\n"
    elif user_tariff in ['PRO', 'MAX', 'PREMIUM']:
        profile_text += f"⏰ Muddati: Cheksiz\n"
    
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
    try:
        data = await state.get_data()
        transaction_data = data.get('transaction_data', {})
        
        if not transaction_data:
            await callback_query.answer("❌ Tranzaksiya ma'lumotlari topilmadi!")
            return
        
        # Financial module orqali ishlov berish
        result = await financial_module.handle_transaction_action(
            callback_query.data, 
            callback_query.from_user.id, 
            transaction_data
        )
        
        if result['success']:
            if result.get('type') == 'completed':
                # Barcha ish tugadi
                await state.clear()
                await callback_query.message.edit_text(
                    result['message'], 
                    parse_mode='Markdown',
                    reply_markup=None
                )
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
                await callback_query.message.edit_text(
                    result['message'], 
                    parse_mode='Markdown',
                    reply_markup=None
                )
        else:
            await callback_query.answer(result['message'])
        
        await callback_query.answer()
        
    except Exception as e:
        logging.error(f"Tranzaksiya callback ishlov berishda xatolik: {e}")
        await callback_query.answer("❌ Xatolik yuz berdi!")


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