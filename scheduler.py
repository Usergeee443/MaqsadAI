import asyncio
import logging
from datetime import datetime, time
from aiogram import Bot
from config import BOT_TOKEN
from database import db
from goal_ai_module import GoalAIModule
from todo_module import TodoModule

class Scheduler:
    def __init__(self):
        self.bot = Bot(token=BOT_TOKEN)
        self.goal_ai_module = GoalAIModule()
        self.todo_module = TodoModule()
        
    async def send_daily_reminders(self):
        """Kunlik eslatmalar yuborish"""
        try:
            # Barcha faol foydalanuvchilarni olish
            query = """
            SELECT user_id FROM users 
            WHERE is_active = TRUE
            """
            users = await db.execute_query(query)
            
            for user_row in users:
                user_id = user_row[0]
                await self.send_user_daily_reminder(user_id)
                
        except Exception as e:
            logging.error(f"Kunlik eslatmalar yuborishda xatolik: {e}")
    
    async def send_user_daily_reminder(self, user_id: int):
        """Foydalanuvchiga kunlik eslatma yuborish"""
        try:
            # Kunlik maslahat
            advice = await self.goal_ai_module.generate_daily_advice(user_id)
            
            # Bugungi vazifalar
            todos = await self.todo_module.get_today_todos(user_id)
            todo_message = self.todo_module.format_today_todos_message(todos)
            
            # Kunlik xabar
            daily_message = f"🌅 *Xayrli tong!*\n\n{advice}\n\n{todo_message}"
            
            await self.bot.send_message(
                chat_id=user_id,
                text=daily_message,
                parse_mode="Markdown"
            )
            
            # Ertalabki vazifalar uchun eslatma
            if todos:
                await asyncio.sleep(2)  # Kichik kechikish
                await self.bot.send_message(
                    chat_id=user_id,
                    text="💪 *Bugun barcha vazifalarni bajaring!*\n\nHar bir kichik qadam sizni orzularingizga yaqinlashtiradi!",
                    parse_mode="Markdown"
                )
            
        except Exception as e:
            logging.error(f"Foydalanuvchi {user_id} ga eslatma yuborishda xatolik: {e}")
    
    async def cleanup_old_todos(self):
        """Eski vazifalarni tozalash"""
        try:
            # Kechagi vazifalarni o'chirish
            query = """
            DELETE FROM todos 
            WHERE due_date < CURDATE() AND is_completed = TRUE
            """
            await db.execute_query(query)
            
            # Muddati o'tgan vazifalarni bekor qilish
            query = """
            UPDATE todos 
            SET is_completed = FALSE 
            WHERE due_date < CURDATE() AND is_completed = FALSE
            """
            await db.execute_query(query)
            
        except Exception as e:
            logging.error(f"Eski vazifalarni tozalashda xatolik: {e}")
    
    async def suggest_new_todos(self):
        """Yangi vazifalar taklif qilish"""
        try:
            # Vazifalari yo'q foydalanuvchilarga taklif
            query = """
            SELECT DISTINCT u.user_id 
            FROM users u
            LEFT JOIN todos t ON u.user_id = t.user_id AND t.due_date = CURDATE()
            WHERE u.is_active = TRUE AND t.id IS NULL
            """
            users = await db.execute_query(query)
            
            for user_row in users:
                user_id = user_row[0]
                await self.bot.send_message(
                    chat_id=user_id,
                    text="📝 *Bugun uchun vazifa qo'shing!*\n\n"
                         "Kunlik vazifalar sizni maqsadlaringizga yaqinlashtiradi.\n"
                         "To-Do tugmasini bosing va yangi vazifa yarating!",
                    parse_mode="Markdown"
                )
                
        except Exception as e:
            logging.error(f"Yangi vazifalar taklif qilishda xatolik: {e}")
    
    async def run_daily_tasks(self):
        """Kunlik vazifalarni bajarish"""
        while True:
            try:
                current_time = datetime.now().time()
                
                # Ertalab 9:00 da kunlik eslatmalar
                if current_time.hour == 9 and current_time.minute == 0:
                    await self.send_daily_reminders()
                    await asyncio.sleep(60)  # 1 daqiqa kutish
                
                # Kechqurun 22:00 da tozalash
                elif current_time.hour == 22 and current_time.minute == 0:
                    await self.cleanup_old_todos()
                    await asyncio.sleep(60)  # 1 daqiqa kutish
                
                # Kechqurun 23:00 da yangi vazifalar taklifi
                elif current_time.hour == 23 and current_time.minute == 0:
                    await self.suggest_new_todos()
                    await asyncio.sleep(60)  # 1 daqiqa kutish
                
                # 1 daqiqa kutish
                await asyncio.sleep(60)
                
            except Exception as e:
                logging.error(f"Kunlik vazifalarni bajarishda xatolik: {e}")
                await asyncio.sleep(60)

# Global scheduler instance
scheduler = Scheduler()


