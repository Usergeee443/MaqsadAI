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
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
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
    waiting_for_tariff = State()

# Asosiy menyu tugmalari
def get_main_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Hisobotlar"), KeyboardButton(text="👤 Profil")]
        ],
        resize_keyboard=True
    )
    return keyboard

# Profil menyusi
def get_profile_menu():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data="settings")],
            [InlineKeyboardButton(text="💳 Tarif", callback_data="tariff_info")]
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
            [InlineKeyboardButton(text="⭐ Pro", callback_data="tariff_PRO")],
            [InlineKeyboardButton(text="💎 Pro", callback_data="tariff_PRO")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_profile")]
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
            "INSERT INTO users (user_id, username, first_name, last_name, tariff) VALUES (%s, %s, %s, %s, 'FREE') ON DUPLICATE KEY UPDATE username = %s, first_name = %s, last_name = %s",
            (user_id, username, first_name, last_name, username, first_name, last_name)
        )
    except Exception as e:
        logging.error(f"Foydalanuvchi qo'shishda xatolik: {e}")
    
    await message.answer(
        "🤖 *Balans AI* ga xush kelibsiz!\n\n"
        "Men sizning moliyaviy yordamchingizman. Quyidagi xizmatlardan foydalanishingiz mumkin:\n\n"
        "💰 *Moliyaviy ma'lumotlar* - Kirim, chiqim va qarzlar\n"
        "📊 *Hisobotlar* - Batafsil moliyaviy tahlil\n"
        "🎯 *AI yordamchi* - Moliyaviy maslahatlar\n\n"
        "Ishni boshlash uchun quyidagi tugmalardan foydalaning:",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
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
• AI yordamchi maslahatlari

💰 *Moliyaviy ma'lumotlar:*
Faqat matn yoki ovozli xabar yuboring:
• "Bugun 50 ming so'm ovqatga ketdi"
• "100 ming so'm ish haqi oldim"
• "30 ming so'm qarz berdim"

📊 *Hisobotlar:*
• Balans ma'lumotlari
• Kategoriyalar bo'yicha tahlil
• Oylik tendensiya
• So'nggi tranzaksiyalar

🎯 *AI yordamchi:*
• Moliyaviy maslahatlar
• Xarajatlarni optimizatsiya qilish
• Investitsiya tavsiyalari

*Buyruqlar:*
/start - Botni qayta ishga tushirish
/help - Yordam
    """
    await message.answer(help_text, parse_mode="Markdown")

# Hisobotlar menyusi
@dp.message(lambda message: message.text == "📊 Hisobotlar")
async def reports_menu(message: types.Message, state: FSMContext):
    """Hisobotlar menyusi"""
    user_id = message.from_user.id
    user_tariff = await get_user_tariff(user_id)
    
    # Faqat PRO va MAX tariflar uchun kengaytirilgan hisobot
    if user_tariff not in ['PRO', 'MAX']:
        # Oddiy hisobot
        summary = await reports_module.get_financial_summary(user_id)
        balance = await reports_module.get_balance_report(user_id)
        
        message_text = f"{summary}\n\n"
        message_text += f"💰 *Balans:* {balance['balance']:,.0f} so'm\n"
        message_text += f"📈 *Kirim:* {balance['income']:,.0f} so'm\n"
        message_text += f"📉 *Chiqim:* {balance['expense']:,.0f} so'm\n\n"
        message_text += "📱 *Kengaytirilgan hisobotlar*\n\n"
        message_text += "Kengaytirilgan hisobotlar va grafiklar uchun Pro tarifga o'ting.\n"
        message_text += "Tarifni o'zgartirish uchun Profil > Tarif bo'limiga o'ting."
        
        await message.answer(
            message_text,
            reply_markup=get_main_menu(),
            parse_mode="Markdown"
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
        reply_markup=get_main_menu(),
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
    
    # Agar pullik tarif bo'lsa, muddatini ko'rsatish
    if user_data['tariff'] in ['PRO', 'MAX'] and user_data.get('tariff_expires_at'):
        profile_text += f"⏰ **Faol bo'lish muddati:** {user_data['tariff_expires_at'].strftime('%d.%m.%Y %H:%M')}\n"
    elif user_data['tariff'] in ['PRO', 'MAX']:
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
    
    if user_data['tariff'] in ['PRO', 'MAX'] and user_data.get('tariff_expires_at'):
        profile_text += f"⏰ **Faol bo'lish muddati:** {user_data['tariff_expires_at'].strftime('%d.%m.%Y %H:%M')}\n"
    elif user_data['tariff'] in ['PRO', 'MAX']:
        profile_text += f"⏰ **Faol bo'lish muddati:** Cheksiz\n"
    
    keyboard = get_profile_menu()
    await callback_query.message.edit_text(profile_text, reply_markup=keyboard, parse_mode='Markdown')
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "tariff_info")
async def tariff_info_callback(callback_query: CallbackQuery):
    """Tarif ma'lumotlarini ko'rsatish"""
    text = """💳 **Tariflar**

🆓 **Bepul**
• Asosiy moliyaviy hisobotlar
• 10 ta tranzaksiya/oy

⭐ **Pro - 50,000 so'm/oy**
• Kengaytirilgan hisobotlar
• Cheksiz tranzaksiyalar
• Audio qo'llab-quvvatlash

💎 **Max - 100,000 so'm/oy**
• Barcha Pro imkoniyatlari
• AI yordamchi maslahatlari
• Kengaytirilgan tahlillar

Tarifni tanlang:"""
    
    keyboard = get_tariff_menu()
    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode='Markdown')
    await callback_query.answer()

@dp.callback_query(lambda c: c.data.startswith("tariff_") and c.data.split("_")[1] in ["FREE", "PRO", "MAX"])
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
    message = f"✅ Tarif '{tariff_name}' ga o'zgartirildi!"
    
    await callback_query.message.edit_text(message, parse_mode='Markdown')
    await callback_query.answer(message)

# Moliyaviy ma'lumotlarni qayta ishlash
@dp.message(lambda message: message.text and not message.text.startswith('/') and message.text not in ["📊 Hisobotlar", "👤 Profil"])
async def process_financial_message(message: types.Message, state: FSMContext):
    """Moliyaviy ma'lumotlarni qayta ishlash"""
    # Agar foydalanuvchi tarif tanlash jarayonida bo'lsa
    if await state.get_state() == UserStates.waiting_for_tariff:
        return
    
    # Agar foydalanuvchi boshqa holatda bo'lsa
    if await state.get_state() in [UserStates.waiting_for_goal_description, UserStates.waiting_for_goal_answer,
                                   UserStates.waiting_for_todo_title, UserStates.waiting_for_todo_description]:
        return
    
    user_id = message.from_user.id
    text = message.text
    
    # AI yordamida moliyaviy ma'lumotni qayta ishlash
    result = await financial_module.process_ai_input(text, user_id)
    
    if result['success']:
        await message.answer(result['message'], parse_mode='Markdown')
    else:
        await message.answer(result['message'], parse_mode='Markdown')

# Audio xabarlarni qayta ishlash
@dp.message(lambda message: message.voice or message.audio)
async def process_audio_message(message: types.Message, state: FSMContext):
    """Audio xabarlarni qayta ishlash"""
    # Agar foydalanuvchi tarif tanlash jarayonida bo'lsa
    if await state.get_state() == UserStates.waiting_for_tariff:
        return
    
    # Agar foydalanuvchi boshqa holatda bo'lsa
    if await state.get_state() in [UserStates.waiting_for_goal_description, UserStates.waiting_for_goal_answer,
                                   UserStates.waiting_for_todo_title, UserStates.waiting_for_todo_description]:
        return
    
    user_id = message.from_user.id
    user_tariff = await get_user_tariff(user_id)
    
    # Faqat PRO va MAX tariflar uchun audio qo'llab-quvvatlash
    if user_tariff not in ['PRO', 'MAX']:
        await message.answer(
            "🎵 **Audio qo'llab-quvvatlash**\n\n"
            "Audio xabarlarni qayta ishlash faqat Pro tarif uchun mavjud.\n"
            "Tarifni yangilash uchun Profil > Tarif bo'limiga o'ting.",
            parse_mode='Markdown'
        )
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
    
    try:
        # Bot ishga tushirish
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
