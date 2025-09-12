import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, TARIFFS, CATEGORIES
from database import db
from models import User, TariffType
from financial_module import FinancialModule
from todo_module import TodoModule
from goal_ai_module import GoalAIModule
from reports_module import ReportsModule
from scheduler import scheduler

# Logging sozlamalari
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot va dispatcher
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Modullar
financial_module = FinancialModule()
todo_module = TodoModule()
goal_ai_module = GoalAIModule()
reports_module = ReportsModule()

# FSM holatlar
class UserStates(StatesGroup):
    waiting_for_tariff = State()
    waiting_for_goal_description = State()
    waiting_for_goal_answer = State()
    waiting_for_todo_title = State()
    waiting_for_todo_description = State()

# Asosiy menyu tugmalari
def get_main_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 To-Do"), KeyboardButton(text="📊 Hisobotlar")],
            [KeyboardButton(text="🎯 Maqsad AI"), KeyboardButton(text="⚙️ Sozlamalar")]
        ],
        resize_keyboard=True
    )
    return keyboard

# Tarif tanlash tugmalari
def get_tariff_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🆓 Bepul", callback_data="tariff_FREE")],
            [InlineKeyboardButton(text="⭐ Pro", callback_data="tariff_PRO")],
            [InlineKeyboardButton(text="💎 Max", callback_data="tariff_MAX")]
        ]
    )
    return keyboard

@dp.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext):
    """Botni ishga tushirish"""
    user_id = message.from_user.id
    
    # Foydalanuvchini ma'lumotlar bazasiga qo'shish
    await add_user_if_not_exists(user_id, message.from_user)
    
    # Foydalanuvchi tarifini tekshirish
    user_tariff = await get_user_tariff(user_id)
    
    if user_tariff == "FREE":
        # Agar tarif tanlanmagan bo'lsa
        welcome_text = """
🤖 *HamyonAI&MaqsadAI Bot* ga xush kelibsiz!

Bu bot sizga quyidagi xizmatlarni taqdim etadi:
• 📝 To-Do (kunlik vazifalar)
• 📊 Hisobotlar (grafik va tahlil)
• 🎯 Maqsad AI (faqat Max tarifda)
• ⚙️ Sozlamalar

Iltimos, tarifingizni tanlang:
        """
        
        await message.answer(
            welcome_text,
            reply_markup=get_tariff_keyboard(),
            parse_mode="Markdown"
        )
        await state.set_state(UserStates.waiting_for_tariff)
    else:
        # Agar tarif tanlangan bo'lsa, asosiy menyuni ko'rsatish
        tariff_names = {
            "FREE": "🆓 Bepul",
            "PRO": "⭐ Pro", 
            "MAX": "💎 Max"
        }
        
        await message.answer(
            f"🤖 *HamyonAI&MaqsadAI Bot*\n\n"
            f"✅ Siz {tariff_names[user_tariff]} tarifda ishlayapsiz!\n\n"
            "Kerakli xizmatni tanlang:",
            reply_markup=get_main_menu(),
            parse_mode="Markdown"
        )
        await state.clear()

@dp.callback_query(lambda c: c.data.startswith("tariff_"))
async def process_tariff_selection(callback_query: types.CallbackQuery, state: FSMContext):
    """Tarif tanlashni qayta ishlash"""
    tariff = callback_query.data.split("_")[1]
    user_id = callback_query.from_user.id
    
    # Foydalanuvchi tarifini yangilash
    await update_user_tariff(user_id, tariff)
    
    tariff_names = {
        "FREE": "🆓 Bepul",
        "PRO": "⭐ Pro", 
        "MAX": "💎 Max"
    }
    
    await callback_query.message.edit_text(
        f"✅ Siz {tariff_names[tariff]} tarifini tanladingiz!\n\n"
        "Endi asosiy menyudan kerakli xizmatni tanlang:"
    )
    await callback_query.message.answer(
        "🏠 *Asosiy menyu*\n\n"
        "Kerakli xizmatni tanlang:",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )
    await state.clear()

@dp.message(lambda message: message.text == "📝 To-Do")
async def todo_menu(message: types.Message, state: FSMContext):
    """To-Do menyusi - kunlik vazifalar"""
    # Agar maqsad yaratish jarayonida bo'lsa
    if await state.get_state() == UserStates.waiting_for_goal_answer:
        await message.answer(
            "⏳ *Maqsad yaratish jarayonida!*\n\n"
            "To-Do vazifalarini ko'rish uchun avval maqsad yaratishni yakunlang yoki bekor qiling.",
            parse_mode="Markdown"
        )
        return
    
    user_id = message.from_user.id
    
    # Bugungi vazifalarni olish
    todos = await todo_module.get_today_todos(user_id)
    
    if not todos:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="➕ Bugun uchun vazifa qo'shish", callback_data="add_today_todo")]
            ]
        )
        await message.answer(
            "📅 *Bugun qiladigan ishlar*\n\n"
            "Hozircha vazifalar yo'q. Yangi vazifa qo'shing!",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    else:
        # Vazifalar ro'yxatini ko'rsatish
        keyboard_buttons = []
        for i, todo in enumerate(todos, 1):
            status = "✅" if todo['is_completed'] else "⏳"
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=f"{status} {todo['title'][:30]}...", 
                    callback_data=f"todo_{todo['id']}"
                )
            ])
        
        keyboard_buttons.append([
            InlineKeyboardButton(text="➕ Yangi vazifa", callback_data="add_today_todo")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        message_text = "📅 *Bugun qiladigan ishlar*\n\n"
        for i, todo in enumerate(todos, 1):
            status = "✅" if todo['is_completed'] else "⏳"
            message_text += f"{i}. {status} {todo['title']}\n"
        
        await message.answer(
            message_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

# To-Do callback handlerlari
@dp.callback_query(lambda c: c.data == "add_today_todo")
async def add_today_todo(callback_query: types.CallbackQuery, state: FSMContext):
    """Bugun uchun yangi vazifa qo'shish"""
    await callback_query.message.edit_text(
        "📝 *Yangi vazifa*\n\n"
        "Bugun qiladigan ishingizni yozing:",
        parse_mode="Markdown"
    )
    await state.set_state(UserStates.waiting_for_todo_title)

@dp.callback_query(lambda c: c.data.startswith("todo_"))
async def show_todo_details(callback_query: types.CallbackQuery):
    """Vazifa tafsilotlarini ko'rsatish"""
    todo_id = int(callback_query.data.split("_")[1])
    user_id = callback_query.from_user.id
    
    # Vazifa ma'lumotlarini olish
    todos = await todo_module.get_user_todos(user_id)
    todo = next((t for t in todos if t['id'] == todo_id), None)
    
    if not todo:
        await callback_query.answer("❌ Vazifa topilmadi!")
        return
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Bajarildi", callback_data=f"complete_{todo_id}"),
                InlineKeyboardButton(text="❌ Bekor qilindi", callback_data=f"cancel_{todo_id}")
            ],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_todos")]
        ]
    )
    
    status = "✅ Bajarilgan" if todo['is_completed'] else "⏳ Kutilmoqda"
    
    await callback_query.message.edit_text(
        f"📝 *{todo['title']}*\n\n"
        f"📄 *Tafsilot:* {todo['description']}\n"
        f"📅 *Muddat:* {todo['due_date']}\n"
        f"📊 *Holat:* {status}",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@dp.callback_query(lambda c: c.data.startswith("complete_"))
async def complete_todo(callback_query: types.CallbackQuery):
    """Vazifani bajarilgan deb belgilash"""
    todo_id = int(callback_query.data.split("_")[1])
    user_id = callback_query.from_user.id
    
    success = await todo_module.mark_todo_completed(todo_id, user_id)
    
    if success:
        await callback_query.answer("✅ Vazifa bajarildi!")
        # To-Do menyusini yangilash
        await todo_menu(callback_query.message)
    else:
        await callback_query.answer("❌ Xatolik yuz berdi!")

@dp.callback_query(lambda c: c.data.startswith("cancel_"))
async def cancel_todo(callback_query: types.CallbackQuery):
    """Vazifani bekor qilish"""
    todo_id = int(callback_query.data.split("_")[1])
    user_id = callback_query.from_user.id
    
    success = await todo_module.delete_todo(todo_id, user_id)
    
    if success:
        await callback_query.answer("❌ Vazifa bekor qilindi!")
        # To-Do menyusini yangilash
        await todo_menu(callback_query.message)
    else:
        await callback_query.answer("❌ Xatolik yuz berdi!")

@dp.callback_query(lambda c: c.data == "back_to_todos")
async def back_to_todos(callback_query: types.CallbackQuery):
    """To-Do menyusiga qaytish"""
    await todo_menu(callback_query.message)

@dp.message(UserStates.waiting_for_todo_title)
async def process_todo_title(message: types.Message, state: FSMContext):
    """Vazifa sarlavhasini qayta ishlash"""
    await state.update_data(title=message.text)
    
    await message.answer(
        "📝 Tafsilot yozing (ixtiyoriy):",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="⏭️ O'tkazib yuborish")]],
            resize_keyboard=True
        )
    )
    await state.set_state(UserStates.waiting_for_todo_description)

@dp.message(UserStates.waiting_for_todo_description)
async def process_todo_description(message: types.Message, state: FSMContext):
    """Vazifa tafsilotini qayta ishlash va saqlash"""
    data = await state.get_data()
    
    description = "" if message.text == "⏭️ O'tkazib yuborish" else message.text
    
    # Bugun uchun vazifa yaratish
    from datetime import datetime
    todo_id = await todo_module.create_todo(
        user_id=message.from_user.id,
        title=data['title'],
        description=description,
        due_date=datetime.now().date()
    )
    
    if todo_id:
        await message.answer(
            f"✅ *Vazifa yaratildi!*\n\n"
            f"📝 {data['title']}\n"
            f"📄 {description or 'Tafsilot yoq'}\n\n"
            f"📅 Bugun bajarish kerak!",
            reply_markup=get_main_menu(),
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            "❌ Vazifani yaratishda xatolik!",
            reply_markup=get_main_menu()
        )
    
    await state.clear()

@dp.message(lambda message: message.text == "🎯 Maqsad AI")
async def goal_ai_menu(message: types.Message, state: FSMContext):
    """Maqsad AI menyusi (faqat Max tarifda)"""
    user_id = message.from_user.id
    user_tariff = await get_user_tariff(user_id)
    
    if user_tariff != "MAX":
        await message.answer(
            "❌ *Maqsad AI* faqat Max tarifda mavjud!\n\n"
            "Max tarifga o'tish uchun sozlamalarga kiring.",
            parse_mode="Markdown"
        )
        return
    
    # Foydalanuvchining faol maqsadi bor-yo'qligini tekshirish
    active_goal = await goal_ai_module.get_active_goal(user_id)
    
    if not active_goal:
        # Maqsad yo'q - faqat yaratish tugmasi
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎯 Maqsad yaratish", callback_data="start_goal_creation")]
            ]
        )
        await message.answer(
            "🎯 *Maqsad AI*\n\n"
            "Hali maqsadingiz yo'q. Katta maqsadlaringizni amalga oshirish uchun AI yordamchisidan foydalaning!",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    else:
        # Maqsad bor - progress va hisobotlar
        goal_title = active_goal.get('title', 'Maqsad')
        progress = float(active_goal.get('progress', 0))
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📊 Hisobotlar", callback_data="goal_reports")],
                [InlineKeyboardButton(text="📈 Progress", callback_data="goal_progress")],
                [InlineKeyboardButton(text="🎯 Yangi maqsad", callback_data="start_goal_creation")]
            ]
        )
        
        await message.answer(
            f"🎯 *Maqsad AI*\n\n"
            f"**Joriy maqsad:** {goal_title}\n"
            f"**Progress:** {progress}%\n\n"
            f"Maqsadingizga erishish uchun quyidagi imkoniyatlardan foydalaning:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

# Maqsad AI callback handlerlari
@dp.callback_query(lambda c: c.data == "start_goal_creation")
async def start_goal_creation(callback_query: types.CallbackQuery, state: FSMContext):
    """Maqsad yaratish jarayonini boshlash"""
    user_id = callback_query.from_user.id
    
    # Foydalanuvchida allaqachon maqsad bor-yo'qligini tekshirish
    existing_goals = await goal_ai_module.get_user_goals(user_id)
    active_goals = [g for g in existing_goals if g['is_active']]
    
    if active_goals:
        await callback_query.answer(
            "❌ Sizda allaqachon faol maqsad mavjud!\n\n"
            "Faqat 1 ta maqsad yaratish mumkin. Avval mavjud maqsadni yakunlang.",
            show_alert=True
        )
        return
    
    await callback_query.message.edit_text(
        "🎯 *Yangi maqsad yaratish*\n\n"
        "Maqsadingizni qisqacha yozing:\n"
        "Masalan: '1 yilda biznesdan $10,000 daromad olish'",
        parse_mode="Markdown"
    )
    await state.set_state(UserStates.waiting_for_goal_description)

@dp.callback_query(lambda c: c.data == "my_goals")
async def show_my_goals(callback_query: types.CallbackQuery):
    """Foydalanuvchi maqsadlarini ko'rsatish"""
    goals = await goal_ai_module.get_user_goals(callback_query.from_user.id)
    message_text = goal_ai_module.format_goals_message(goals)
    
    await callback_query.message.edit_text(
        message_text,
        parse_mode="Markdown"
    )

@dp.callback_query(lambda c: c.data == "daily_goal_tasks")
async def show_daily_goal_tasks(callback_query: types.CallbackQuery):
    """Kunlik maqsad vazifalarini ko'rsatish"""
    tasks = await goal_ai_module.get_today_tasks(callback_query.from_user.id)
    message_text = goal_ai_module.format_today_tasks_message(tasks)
    
    await callback_query.message.edit_text(
        message_text,
        parse_mode="Markdown"
    )

@dp.callback_query(lambda c: c.data == "daily_advice")
async def show_daily_advice(callback_query: types.CallbackQuery):
    """Kunlik maslahat ko'rsatish"""
    advice = await goal_ai_module.generate_daily_advice(callback_query.from_user.id)
    
    await callback_query.message.edit_text(
        advice,
        parse_mode="Markdown"
    )

@dp.message(lambda message: message.text == "🎯 Yangi maqsad")
async def new_goal(message: types.Message, state: FSMContext):
    """Yangi maqsad yaratish"""
    await message.answer(
        "🎯 *Yangi maqsad*\n\n"
        "Maqsadingizni batafsil yozing:\n"
        "Masalan: '1 yilda biznesdan $10,000 daromad olish'",
        parse_mode="Markdown"
    )
    await state.set_state(UserStates.waiting_for_goal_description)

@dp.message(UserStates.waiting_for_goal_description)
async def process_goal_description(message: types.Message, state: FSMContext):
    """Maqsad tavsifini qayta ishlash - ko'p savollar jarayoni"""
    # Savollar generatsiya qilinayotganini ko'rsatish
    processing_msg = await message.answer(
        "🤖 *AI savollar tayyorlayapti...*\n\n"
        "Iltimos, biroz kuting. 10 ta savol orqali maqsadingizni 100% aniqlaymiz!",
        parse_mode="Markdown"
    )
    
    result = await goal_ai_module.start_goal_creation_process(message.from_user.id, message.text)
    
    # Processing xabarini o'chirish
    await processing_msg.delete()
    
    if result['success']:
        # Birinchi savolni ko'rsatish
        question_data = result['question']
        
        if question_data['type'] == 'buttons':
            # Tugmali savol
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=option, callback_data=f"goal_answer_{option}")] 
                    for option in question_data['options']
                ] + [
                    [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_goal_creation")]
                ]
            )
            await message.answer(
                f"❓ *Savol {result['step']}/{result['total_steps']}*\n\n"
                f"{question_data['question']}",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        else:
            # Matnli savol
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_goal_creation")]
                ]
            )
            await message.answer(
                f"❓ *Savol {result['step']}/{result['total_steps']}*\n\n"
                f"{question_data['question']}\n\n"
                f"💡 *Maslahat:* {question_data.get('placeholder', '')}",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        
        # Session ID ni state ga saqlash
        await state.update_data(session_id=result['session_id'])
        await state.set_state(UserStates.waiting_for_goal_answer)
    else:
        await message.answer(
            result['message'],
            reply_markup=get_main_menu(),
            parse_mode="Markdown"
        )
        await state.clear()

# Maqsad savoliga javob berish
@dp.message(UserStates.waiting_for_goal_answer)
async def process_goal_answer(message: types.Message, state: FSMContext):
    """Maqsad savoliga javob berish"""
    data = await state.get_data()
    session_id = data.get('session_id')
    
    if not session_id:
        await message.answer("❌ Xatolik yuz berdi. Qaytadan boshlang.")
        await state.clear()
        return
    
    result = await goal_ai_module.process_goal_answer(session_id, message.text)
    
    if result['success']:
        if result.get('is_final'):
            # Maqsad yaratildi
            await message.answer(
                result['message'],
                parse_mode="Markdown"
            )
            
            if result.get('needs_setup'):
                # Sozlamalar tugmalari
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="⚙️ Sozlamalarni o'rnatish", callback_data="setup_goal_settings")]
                    ]
                )
                await message.answer(
                    "⚙️ *Sozlamalarni o'rnatish*\n\n"
                    "Maqsad AI to'liq ishlashi uchun sozlamalarni o'rnating:",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            
            await state.clear()
        else:
            # Keyingi savol
            question_data = result['question']
            
            if question_data['type'] == 'buttons':
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text=option, callback_data=f"goal_answer_{option}")] 
                        for option in question_data['options']
                    ] + [
                        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_goal_creation")]
                    ]
                )
                await message.answer(
                    f"❓ *Savol {result['step']}/{result['total_steps']}*\n\n"
                    f"{question_data['question']}",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            else:
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_goal_creation")]
                    ]
                )
                await message.answer(
                    f"❓ *Savol {result['step']}/{result['total_steps']}*\n\n"
                    f"{question_data['question']}\n\n"
                    f"💡 *Maslahat:* {question_data.get('placeholder', '')}",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
    else:
        await message.answer(
            result['message'],
            reply_markup=get_main_menu(),
            parse_mode="Markdown"
        )
        await state.clear()

# Maqsad savoliga tugma orqali javob berish
@dp.callback_query(lambda c: c.data.startswith("goal_answer_"))
async def process_goal_button_answer(callback_query: types.CallbackQuery, state: FSMContext):
    """Maqsad savoliga tugma orqali javob berish"""
    answer = callback_query.data.replace("goal_answer_", "")
    data = await state.get_data()
    session_id = data.get('session_id')
    
    if not session_id:
        await callback_query.answer("❌ Xatolik yuz berdi. Qaytadan boshlang.")
        return
    
    result = await goal_ai_module.process_goal_answer(session_id, answer)
    
    if result['success']:
        if result.get('is_final'):
            # Maqsad yaratildi
            await callback_query.message.edit_text(
                result['message'],
                parse_mode="Markdown"
            )
            
            if result.get('needs_setup'):
                # Sozlamalar tugmalari
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="⚙️ Sozlamalarni o'rnatish", callback_data="setup_goal_settings")]
                    ]
                )
                await callback_query.message.answer(
                    "⚙️ *Sozlamalarni o'rnatish*\n\n"
                    "Maqsad AI to'liq ishlashi uchun sozlamalarni o'rnating:",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            
            await state.clear()
        else:
            # Keyingi savol
            question_data = result['question']
            
            if question_data['type'] == 'buttons':
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text=option, callback_data=f"goal_answer_{option}")] 
                        for option in question_data['options']
                    ] + [
                        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_goal_creation")]
                    ]
                )
                await callback_query.message.edit_text(
                    f"❓ *Savol {result['step']}/{result['total_steps']}*\n\n"
                    f"{question_data['question']}",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            else:
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_goal_creation")]
                    ]
                )
                await callback_query.message.edit_text(
                    f"❓ *Savol {result['step']}/{result['total_steps']}*\n\n"
                    f"{question_data['question']}\n\n"
                    f"💡 *Maslahat:* {question_data.get('placeholder', '')}",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
    else:
        await callback_query.answer(result['message'])

# Maqsad yaratishni bekor qilish
@dp.callback_query(lambda c: c.data == "cancel_goal_creation")
async def cancel_goal_creation(callback_query: types.CallbackQuery, state: FSMContext):
    """Maqsad yaratishni bekor qilish"""
    await state.clear()
    await callback_query.message.edit_text(
        "❌ *Maqsad yaratish bekor qilindi*\n\n"
        "Asosiy menyuga qaytildi.",
        parse_mode="Markdown"
    )
    await callback_query.message.answer(
        "🏠 *Asosiy menyu*\n\n"
        "Kerakli xizmatni tanlang:",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )

# Maqsad sozlamalarini o'rnatish
@dp.callback_query(lambda c: c.data == "setup_goal_settings")
async def setup_goal_settings(callback_query: types.CallbackQuery, state: FSMContext):
    """Maqsad sozlamalarini o'rnatish"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌅 Kunlik vazifalar vaqti", callback_data="set_daily_tasks_time")],
            [InlineKeyboardButton(text="💪 Motivatsiya vaqti", callback_data="set_motivation_time")],
            [InlineKeyboardButton(text="📊 Progress so'rovi vaqti", callback_data="set_progress_time")],
            [InlineKeyboardButton(text="✅ Sozlamalarni yakunlash", callback_data="finish_setup")]
        ]
    )
    
    await callback_query.message.edit_text(
            "⚙️ *Maqsad AI sozlamalari*\n\n"
            "Quyidagi vaqtlarni belgilang:\n\n"
            "🌅 *Kunlik vazifalar* - Har kuni ertalab yuboriladi\n"
            "💪 *Motivatsiya* - Har kuni kuchli motivatsiya xabari\n"
            "📊 *Progress so'rovi* - Har kuni kechqurun bugungi ishlarni so'raydi\n\n"
            "Kerakli sozlamani tanlang:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )


# Kunlik vazifalar vaqtini o'rnatish
@dp.callback_query(lambda c: c.data == "set_daily_tasks_time")
async def set_daily_tasks_time(callback_query: types.CallbackQuery, state: FSMContext):
    """Kunlik vazifalar vaqtini o'rnatish"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="05:00", callback_data="daily_05:00"), InlineKeyboardButton(text="06:00", callback_data="daily_06:00")],
            [InlineKeyboardButton(text="07:00", callback_data="daily_07:00"), InlineKeyboardButton(text="08:00", callback_data="daily_08:00")],
            [InlineKeyboardButton(text="09:00", callback_data="daily_09:00"), InlineKeyboardButton(text="10:00", callback_data="daily_10:00")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="setup_goal_settings")]
        ]
    )
    
    await callback_query.message.edit_text(
        "🌅 *1-qadam: Kunlik vazifalar vaqtini tanlang*\n\n"
        "Har kuni qaysi vaqtda kunlik vazifalar yuborilsin?\n"
        "05:00 dan 10:00 gacha bo'lgan vaqtlardan birini tanlang:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


# Kunlik vazifalar vaqtini saqlash
@dp.callback_query(lambda c: c.data.startswith("daily_"))
async def save_daily_time(callback_query: types.CallbackQuery, state: FSMContext):
    """Kunlik vazifalar vaqtini saqlash"""
    time = callback_query.data.replace("daily_", "")
    await state.update_data(daily_tasks_time=time)
    
    await callback_query.message.edit_text(
        f"✅ *Muvaffaqiyatli!*\n\n"
        f"Kunlik vazifalar vaqti: {time}\n\n"
        f"Endi motivatsiya vaqtini tanlang:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="💪 Motivatsiya vaqtini tanlash", callback_data="set_motivation_time")]]
        ),
        parse_mode="Markdown"
    )


# Motivatsiya vaqtini o'rnatish
@dp.callback_query(lambda c: c.data == "set_motivation_time")
async def set_motivation_time(callback_query: types.CallbackQuery, state: FSMContext):
    """Motivatsiya vaqtini o'rnatish"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="08:00", callback_data="motivation_08:00"), InlineKeyboardButton(text="09:00", callback_data="motivation_09:00")],
            [InlineKeyboardButton(text="10:00", callback_data="motivation_10:00"), InlineKeyboardButton(text="11:00", callback_data="motivation_11:00")],
            [InlineKeyboardButton(text="12:00", callback_data="motivation_12:00"), InlineKeyboardButton(text="13:00", callback_data="motivation_13:00")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="setup_goal_settings")]
        ]
    )
    
    await callback_query.message.edit_text(
        "💪 *2-qadam: Motivatsiya vaqtini tanlang*\n\n"
        "Har kuni qaysi vaqtda motivatsiya xabari yuborilsin?",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


# Motivatsiya vaqtini saqlash
@dp.callback_query(lambda c: c.data.startswith("motivation_"))
async def save_motivation_time(callback_query: types.CallbackQuery, state: FSMContext):
    """Motivatsiya vaqtini saqlash"""
    time = callback_query.data.replace("motivation_", "")
    await state.update_data(motivation_time=time)
    
    await callback_query.message.edit_text(
        f"✅ *Muvaffaqiyatli!*\n\n"
        f"Motivatsiya vaqti: {time}\n\n"
        f"Endi progress so'rovi vaqtini tanlang:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="📊 Progress so'rovi vaqtini tanlash", callback_data="set_progress_time")]]
        ),
        parse_mode="Markdown"
    )


# Progress so'rovi vaqtini o'rnatish
@dp.callback_query(lambda c: c.data == "set_progress_time")
async def set_progress_time(callback_query: types.CallbackQuery, state: FSMContext):
    """Progress so'rovi vaqtini o'rnatish"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="18:00", callback_data="progress_18:00"), InlineKeyboardButton(text="19:00", callback_data="progress_19:00")],
            [InlineKeyboardButton(text="20:00", callback_data="progress_20:00"), InlineKeyboardButton(text="21:00", callback_data="progress_21:00")],
            [InlineKeyboardButton(text="22:00", callback_data="progress_22:00"), InlineKeyboardButton(text="23:00", callback_data="progress_23:00")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="setup_goal_settings")]
        ]
    )
    
    await callback_query.message.edit_text(
        "📊 *3-qadam: Progress so'rovi vaqtini tanlang*\n\n"
        "Har kuni qaysi vaqtda bugungi progress so'ralsin?",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


# Progress vaqtini saqlash va yakunlash
@dp.callback_query(lambda c: c.data.startswith("progress_"))
async def save_progress_time(callback_query: types.CallbackQuery, state: FSMContext):
    """Progress vaqtini saqlash va yakunlash"""
    time = callback_query.data.replace("progress_", "")
    data = await state.get_data()
    
    daily_time = data.get('daily_tasks_time', '08:00')
    motivation_time = data.get('motivation_time', '09:00')
    
    await callback_query.message.edit_text(
        f"🎉 *Tabriklaymiz! Barcha sozlamalar tayyor!*\n\n"
        f"✅ Kunlik vazifalar: {daily_time}\n"
        f"✅ Motivatsiya: {motivation_time}\n"
        f"✅ Progress so'rovi: {time}\n\n"
        f"Endi Maqsad AI sizga har kuni:\n"
        f"• {daily_time} da kunlik vazifalar yuboradi\n"
        f"• {motivation_time} da motivatsiya xabari yuboradi\n"
        f"• {time} da progress so'raydi\n\n"
        f"Maqsadingizga erishish uchun omad! 🚀",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🎯 Maqsad AI", callback_data="goal_ai_menu")]]
        ),
        parse_mode="Markdown"
    )
    await state.clear()


# Sozlamalarni yakunlash
@dp.callback_query(lambda c: c.data == "finish_setup")
async def finish_setup(callback_query: types.CallbackQuery, state: FSMContext):
    """Sozlamalarni yakunlash"""
    await callback_query.message.edit_text(
        "✅ *Maqsad AI sozlamalari yakunlandi!*\n\n"
        "Endi sizning maqsadingiz uchun:\n"
        "• Kunlik vazifalar yuboriladi\n"
        "• Motivatsiya xabarlari yuboriladi\n"
        "• Progress so'rovlari yuboriladi\n\n"
        "Maqsad AI orqali maqsadingizni kuzatib boring!",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🎯 Maqsad AI", callback_data="goal_ai_menu")]]
        ),
        parse_mode="Markdown"
    )
    await state.clear()

@dp.message(lambda message: message.text == "📊 Hisobotlar")
async def reports_menu(message: types.Message, state: FSMContext):
    """Hisobotlar menyusi - soddalashtirilgan"""
    # Agar maqsad yaratish jarayonida bo'lsa
    if await state.get_state() == UserStates.waiting_for_goal_answer:
        await message.answer(
            "⏳ *Maqsad yaratish jarayonida!*\n\n"
            "Hisobotlarni ko'rish uchun avval maqsad yaratishni yakunlang yoki bekor qiling.",
            parse_mode="Markdown"
        )
        return
    
    user_id = message.from_user.id
    
    # Moliyaviy xulosa
    summary = await reports_module.get_financial_summary(user_id)
    
    # Balans ma'lumotlari
    balance = await reports_module.get_balance_report(user_id)
    
    # Kategoriyalar bo'yicha hisobot
    categories = await reports_module.get_category_report(user_id, 30)
    
    # Xabar tuzish
    message_text = f"{summary}\n\n"
    
    # Balans
    message_text += f"💰 *Balans:* {balance['balance']:,.0f} so'm\n"
    message_text += f"📈 *Kirim:* {balance['income']:,.0f} so'm\n"
    message_text += f"📉 *Chiqim:* {balance['expense']:,.0f} so'm\n\n"
    
    # Eng ko'p chiqim kategoriyasi
    if categories['expense_categories']:
        top_category = max(categories['expense_categories'].items(), key=lambda x: x[1]['total'])
        message_text += f"🔥 *Eng ko'p chiqim:* {top_category[0]} ({top_category[1]['total']:,.0f} so'm)\n\n"
    
    # So'nggi tranzaksiyalar
    recent = await reports_module.get_recent_transactions(user_id, 5)
    if recent:
        message_text += "📋 *So'nggi tranzaksiyalar:*\n"
        for trans in recent:
            type_emoji = {"income": "📈", "expense": "📉", "debt": "💳"}.get(trans["type"], "❓")
            message_text += f"• {type_emoji} {trans['amount']:,.0f} so'm - {trans['category']}\n"
    
    await message.answer(
        message_text,
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )


@dp.message(lambda message: message.text == "⚙️ Sozlamalar")
async def settings_menu(message: types.Message):
    """Sozlamalar menyusi"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔄 Tarifni o'zgartirish"), KeyboardButton(text="🌐 Til")],
            [KeyboardButton(text="🔔 Eslatmalar"), KeyboardButton(text="🔙 Asosiy menyu")]
        ],
        resize_keyboard=True
    )
    await message.answer(
        "⚙️ *Sozlamalar*\n\n"
        "Bot sozlamalarini boshqaring:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@dp.message(lambda message: message.text == "🔄 Tarifni o'zgartirish")
async def change_tariff(message: types.Message, state: FSMContext):
    """Tarifni o'zgartirish"""
    await message.answer(
        "🔄 *Tarifni o'zgartirish*\n\n"
        "Yangi tarifni tanlang:",
        reply_markup=get_tariff_keyboard(),
        parse_mode="Markdown"
    )
    await state.set_state(UserStates.waiting_for_tariff)

@dp.message(lambda message: message.text == "🔙 Asosiy menyu")
async def back_to_main(message: types.Message, state: FSMContext):
    """Asosiy menyuga qaytish"""
    await state.clear()
    await message.answer(
        "🏠 *Asosiy menyu*\n\n"
        "Kerakli xizmatni tanlang:",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )

# Yordamchi funksiyalar
async def add_user_if_not_exists(user_id: int, user_data):
    """Foydalanuvchini ma'lumotlar bazasiga qo'shish"""
    try:
        query = """
        INSERT IGNORE INTO users (user_id, username, first_name, last_name, tariff, created_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        """
        await db.execute_insert(query, (
            user_id,
            user_data.username,
            user_data.first_name,
            user_data.last_name,
            "FREE"
        ))
    except Exception as e:
        logger.error(f"Foydalanuvchi qo'shishda xatolik: {e}")

async def update_user_tariff(user_id: int, tariff: str):
    """Foydalanuvchi tarifini yangilash"""
    try:
        query = "UPDATE users SET tariff = %s WHERE user_id = %s"
        await db.execute_query(query, (tariff, user_id))
    except Exception as e:
        logger.error(f"Tarif yangilashda xatolik: {e}")

async def get_user_tariff(user_id: int) -> str:
    """Foydalanuvchi tarifini olish"""
    try:
        query = "SELECT tariff FROM users WHERE user_id = %s"
        result = await db.execute_one(query, (user_id,))
        return result[0] if result else "FREE"
    except Exception as e:
        logger.error(f"Tarif olishda xatolik: {e}")
        return "FREE"


# Moliyaviy yordamchi - oxirgi handler
@dp.message()
async def process_financial_message(message: types.Message, state: FSMContext):
    """Har qanday matnni moliyaviy ma'lumot sifatida qayta ishlash"""
    # Agar foydalanuvchi tarif tanlash jarayonida bo'lsa
    if await state.get_state() == UserStates.waiting_for_tariff:
        return
    
    # Agar foydalanuvchi boshqa holatda bo'lsa
    if await state.get_state() in [UserStates.waiting_for_goal_description, UserStates.waiting_for_goal_answer,
                                   UserStates.waiting_for_todo_title, UserStates.waiting_for_todo_description]:
        return
    
    # Barcha tariflarda moliyaviy ma'lumot sifatida qayta ishlash
    user_id = message.from_user.id
    user_tariff = await get_user_tariff(user_id)
    
    # AI yordamida qayta ishlash (barcha tariflarda)
    result = await financial_module.process_ai_input(message.text, user_id)
    
    if result['success']:
        await message.answer(
            result['message'],
            reply_markup=get_main_menu(),
            parse_mode="Markdown"
        )
    else:
        # Agar AI qayta ishlay olmasa, oddiy yordam xabari
        await message.answer(
            "💡 *Yordam*\n\n"
            "Quyidagi tugmalardan birini tanlang:\n"
            "• 📝 To-Do - Kunlik vazifalar\n"
            "• 📊 Hisobotlar - Moliyaviy hisobotlar\n"
            "• 🎯 Maqsad AI - Maqsad yaratish (Max tarifda)\n"
            "• ⚙️ Sozlamalar - Bot sozlamalari\n\n"
            "Yoki moliyaviy ma'lumot yuboring:\n"
            "Masalan: 'Bugun 50 ming so'm ovqatga ketdi'",
            reply_markup=get_main_menu(),
            parse_mode="Markdown"
        )


# Maqsad AI hisobotlari
@dp.callback_query(lambda c: c.data == "goal_reports")
async def show_goal_reports(callback_query: types.CallbackQuery):
    """Maqsad hisobotlarini ko'rsatish"""
    user_id = callback_query.from_user.id
    active_goal = await goal_ai_module.get_active_goal(user_id)
    
    if not active_goal:
        await callback_query.answer("❌ Faol maqsad topilmadi!", show_alert=True)
        return
    
    # Progress hisobini ko'rsatish
    progress = float(active_goal.get('progress', 0))
    days_passed = (datetime.now() - active_goal['created_at']).days
    
    await callback_query.message.edit_text(
        f"📊 *Maqsad hisobotlari*\n\n"
        f"**Maqsad:** {active_goal['title']}\n"
        f"**Progress:** {progress}%\n"
        f"**Kunlar o'tdi:** {days_passed}\n"
        f"**Yaratilgan:** {active_goal['created_at'].strftime('%d.%m.%Y')}\n\n"
        f"Maqsadga erishish imkoniyati: {progress}%",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 Orqaga", callback_data="goal_ai_menu")]]
        ),
        parse_mode="Markdown"
    )

# Maqsad progress
@dp.callback_query(lambda c: c.data == "goal_progress")
async def show_goal_progress(callback_query: types.CallbackQuery):
    """Maqsad progressini ko'rsatish"""
    user_id = callback_query.from_user.id
    active_goal = await goal_ai_module.get_active_goal(user_id)
    
    if not active_goal:
        await callback_query.answer("❌ Faol maqsad topilmadi!", show_alert=True)
        return
    
    progress = float(active_goal.get('progress', 0))
    progress_bar = "█" * int(progress // 10) + "░" * int(10 - progress // 10)
    
    await callback_query.message.edit_text(
        f"📈 *Maqsad progressi*\n\n"
        f"**{active_goal['title']}**\n\n"
        f"Progress: {progress}%\n"
        f"{progress_bar}\n\n"
        f"**Tavsif:** {active_goal['description']}\n\n"
        f"**Strategiya:** {active_goal['strategy']}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 Orqaga", callback_data="goal_ai_menu")]]
        ),
        parse_mode="Markdown"
    )


async def main():
    """Asosiy dastur"""
    # Ma'lumotlar bazasini ulash
    await db.create_pool()
    
    try:
        # Scheduler ni ishga tushirish
        scheduler_task = asyncio.create_task(scheduler.run_daily_tasks())
        
        # Botni ishga tushirish
        await dp.start_polling(bot)
    finally:
        # Scheduler ni to'xtatish
        scheduler_task.cancel()
        # Ma'lumotlar bazasini yopish
        await db.close_pool()

if __name__ == "__main__":
    asyncio.run(main())