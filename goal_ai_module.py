import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI
from config import OPENAI_API_KEY
from database import db
from models import Goal, DailyTask

class GoalAIModule:
    def __init__(self):
        self.openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    
    async def start_goal_creation_process(self, user_id: int, initial_goal: str) -> Dict[str, Any]:
        """Maqsad yaratish jarayonini boshlash - ko'p savollar bilan"""
        try:
            # Maqsad yaratish jarayonini ma'lumotlar bazasiga saqlash
            query = """
            INSERT INTO goal_creation_sessions (user_id, initial_goal, current_step, created_at)
            VALUES (%s, %s, %s, NOW())
            """
            session_id = await db.execute_insert(query, (user_id, initial_goal, 1))
            
            # Birinchi savolni yaratish
            first_question = await self.generate_goal_question(1, initial_goal)
            
            return {
                "success": True,
                "session_id": session_id,
                "question": first_question,
                "step": 1,
                "total_steps": 10
            }
            
        except Exception as e:
            logging.error(f"Maqsad yaratish jarayonini boshlashda xatolik: {e}")
            return {
                "success": False,
                "message": "❌ Maqsad yaratish jarayonini boshlashda xatolik yuz berdi."
            }
    
    async def generate_goal_question(self, step: int, context: str) -> Dict[str, Any]:
        """Maqsad uchun savol yaratish - AI orqali generatsiya"""
        try:
            # AI orqali savol yaratish
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": f"""Siz maqsad yaratish bo'yicha mutaxassis AI siz. Foydalanuvchi maqsadi: "{context}"

{step}-bosqichda quyidagi formatda savol yarating:

{{
    "question": "Savol matni",
    "type": "text" yoki "buttons",
    "options": ["variant1", "variant2", ...] (faqat buttons uchun),
    "placeholder": "Maslahat matni" (faqat text uchun)
}}

MUHIM: 
- Faqat maqsadni to'liq aniqlash uchun kerakli savollarni bering
- Savollar aniq, foydali va maqsadni 100% tushunish uchun zarur bo'lishi kerak
- Keraksiz yoki g'alati savollar bermang
- Har bir savol maqsadni yanada aniqroq qilishi kerak

Savollar tartibi va mavzulari:
1. Maqsadni batafsilroq tushuntirish (nima, qanday, necha, qachon)
2. Muhimlik darajasi (1-10) - tugmalar bilan
3. Vaqt oralig'i - tugmalar bilan  
4. Hozirgi holat (qanchalik yaqin) - tugmalar bilan
5. Kerakli resurslar (pul, vaqt, bilim, tajriba, asboblar)
6. Mavjud resurslar (hozir nima bor, qanday imkoniyatlar)
7. To'siqlar va qiyinchiliklar (nima muammo bo'lishi mumkin)
8. O'zgarishlar va natijalar (erishganda nima bo'ladi, qanday foyda)
9. Kunlik vaqt ajratish - tugmalar bilan
10. Yordam va qo'llab-quvvatlash (kim yordam bera oladi, qanday yordam)

Har bir savol maqsadni yanada aniq va amalga oshirish mumkin qilishi kerak."""
                    },
                    {
                        "role": "user",
                        "content": f"{step}-bosqich uchun savol yarating"
                    }
                ],
                temperature=0.7
            )
            
            ai_response = response.choices[0].message.content
            if not ai_response:
                return self._get_fallback_question(step)
            
            import json
            try:
                data = json.loads(ai_response)
                return data
            except json.JSONDecodeError:
                return self._get_fallback_question(step)
            
        except Exception as e:
            logging.error(f"Savol yaratishda xatolik: {e}")
            return self._get_fallback_question(step)
    
    def _get_fallback_question(self, step: int) -> Dict[str, Any]:
        """Zaxira savollar"""
        questions = {
            1: {
                "question": "Maqsadingizni batafsilroq tushuntiring. Nima qilmoqchisiz?",
                "type": "text",
                "placeholder": "Masalan: 1 yilda o'z biznesimni ochib, oylik $5000 daromad olish"
            },
            2: {
                "question": "Bu maqsad siz uchun qanchalik muhim? (1-10)",
                "type": "buttons",
                "options": ["1 - Kam muhim", "3", "5 - O'rtacha", "7", "9", "10 - Juda muhim"]
            },
            3: {
                "question": "Maqsadga erishish uchun qancha vaqt kerak?",
                "type": "buttons",
                "options": ["1 oy", "3 oy", "6 oy", "1 yil", "2 yil", "5 yil yoki ko'proq"]
            },
            4: {
                "question": "Hozirgi holatda bu maqsadga qanchalik yaqinsiz?",
                "type": "buttons",
                "options": ["0% - Boshlanmagan", "25% - Boshlangan", "50% - Yarim yo'lda", "75% - Deyarli tayyor", "90% - Juda yaqin"]
            },
            5: {
                "question": "Maqsadga erishish uchun qanday resurslar kerak?",
                "type": "text",
                "placeholder": "Masalan: pul, vaqt, bilim, tajriba, yordam"
            },
            6: {
                "question": "Sizda hozir bu resurslardan qaysilari bor?",
                "type": "text",
                "placeholder": "Mavjud resurslaringizni yozing"
            },
            7: {
                "question": "Maqsadga erishishda qanday to'siqlar bo'lishi mumkin?",
                "type": "text",
                "placeholder": "Muammolar, qiyinchiliklar, xavflar"
            },
            8: {
                "question": "Maqsadga erishganda nima o'zgaradi?",
                "type": "text",
                "placeholder": "Hayotingizda qanday o'zgarishlar bo'ladi?"
            },
            9: {
                "question": "Maqsadga erishish uchun kuniga qancha vaqt ajratasiz?",
                "type": "buttons",
                "options": ["30 daqiqa", "1 soat", "2 soat", "4 soat", "8 soat", "8 soatdan ko'proq"]
            },
            10: {
                "question": "Maqsadga erishishda kim sizga yordam bera oladi?",
                "type": "text",
                "placeholder": "Oila, do'stlar, murabbiylar, mutaxassislar"
            }
        }
        
        return questions.get(step, questions[1])
    
    async def process_goal_answer(self, session_id: int, answer: str) -> Dict[str, Any]:
        """Maqsad savoliga javobni qayta ishlash"""
        try:
            # Javobni saqlash
            query = """
            INSERT INTO goal_answers (session_id, step, answer, created_at)
            VALUES (%s, (SELECT current_step FROM goal_creation_sessions WHERE id = %s), %s, NOW())
            """
            await db.execute_insert(query, (session_id, session_id, answer))
            
            # Keyingi bosqichga o'tish
            update_query = """
            UPDATE goal_creation_sessions 
            SET current_step = current_step + 1 
            WHERE id = %s
            """
            await db.execute_query(update_query, (session_id,))
            
            # Hozirgi bosqichni olish
            current_query = "SELECT current_step FROM goal_creation_sessions WHERE id = %s"
            result = await db.execute_one(current_query, (session_id,))
            current_step = result[0] if result else 1
            
            if current_step > 10:
                # Barcha savollar tugadi, maqsadni yaratish
                return await self.finalize_goal_creation(session_id)
            else:
                # Keyingi savolni yaratish
                context_query = "SELECT initial_goal FROM goal_creation_sessions WHERE id = %s"
                context_result = await db.execute_one(context_query, (session_id,))
                context = context_result[0] if context_result else ""
                
                next_question = await self.generate_goal_question(current_step, context)
                
                return {
                    "success": True,
                    "question": next_question,
                    "step": current_step,
                    "total_steps": 10,
                    "is_final": False,
                    "processing_message": "🤖 *AI maqsadingizni tayyorlayapti...*\n\nBarcha javoblaringizni tahlil qilib, sizga eng yaxshi strategiya va rejani yaratmoqda. Kuting..."
                }
                
        except Exception as e:
            logging.error(f"Javobni qayta ishlashda xatolik: {e}")
            return {
                "success": False,
                "message": "❌ Javobni qayta ishlashda xatolik yuz berdi."
            }
    
    async def finalize_goal_creation(self, session_id: int) -> Dict[str, Any]:
        """Maqsad yaratish jarayonini yakunlash"""
        try:
            # Barcha javoblarni olish
            answers_query = """
            SELECT step, answer FROM goal_answers 
            WHERE session_id = %s 
            ORDER BY step
            """
            answers = await db.execute_query(answers_query, (session_id,))
            
            # Maqsad ma'lumotlarini olish
            session_query = "SELECT user_id, initial_goal FROM goal_creation_sessions WHERE id = %s"
            session_result = await db.execute_one(session_query, (session_id,))
            user_id, initial_goal = session_result if session_result else (None, "")
            
            # AI orqali maqsadni yakunlash
            answers_text = "\n".join([f"{step}. {answer}" for step, answer in answers])
            
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o",  # Eng kuchli model
                messages=[
                    {
                        "role": "system",
                        "content": """Siz maqsad yaratish bo'yicha mutaxassis AI siz. Foydalanuvchi javoblariga asoslanib, quyidagi formatda yakuniy maqsad yarating:

{
    "title": "Aniq maqsad sarlavhasi",
    "description": "Batafsil tavsif",
    "target_amount": 10000,
    "target_date": "2024-12-31",
    "strategy": "Umumiy strategiya",
    "milestones": [
        {"title": "1-bosqich", "description": "Tavsif", "deadline": "2024-03-31"},
        {"title": "2-bosqich", "description": "Tavsif", "deadline": "2024-06-30"}
    ],
    "daily_tasks": [
        "Kunlik vazifa 1",
        "Kunlik vazifa 2",
        "Kunlik vazifa 3"
    ],
    "motivation": "Motivatsiya matni"
}

Agar maqsad moliyaviy bo'lmasa, target_amount null bo'lsin."""
                    },
                    {
                        "role": "user",
                        "content": f"Boshlang'ich maqsad: {initial_goal}\n\nJavoblar:\n{answers_text}\n\nYakuniy maqsadni yarating:"
                    }
                ],
                temperature=0.7
            )
            
            import json
            ai_response = response.choices[0].message.content
            goal_data = json.loads(ai_response)
            
            # Maqsadni ma'lumotlar bazasiga saqlash
            goal_id = await self.save_goal(
                user_id=user_id,
                title=goal_data['title'],
                description=goal_data['description'],
                target_amount=goal_data.get('target_amount'),
                target_date=datetime.strptime(goal_data['target_date'], '%Y-%m-%d') if goal_data.get('target_date') else None
            )
            
            # Kunlik vazifalarni saqlash
            for task in goal_data.get('daily_tasks', []):
                await self.create_daily_task(goal_id, task)
            
            # Sessionni yopish
            await db.execute_query("DELETE FROM goal_creation_sessions WHERE id = %s", (session_id,))
            
            return {
                "success": True,
                "goal_id": goal_id,
                "goal_data": goal_data,
                "message": f"🎯 *Maqsad muvaffaqiyatli yaratildi!*\n\n"
                          f"📌 *{goal_data['title']}*\n"
                          f"📝 {goal_data['description']}\n\n"
                          f"💪 *Motivatsiya:*\n{goal_data.get('motivation', 'Siz buni qila olasiz!')}\n\n"
                          f"📊 *Strategiya:*\n{goal_data['strategy']}\n\n"
                          f"📅 *Kunlik vazifalar:*\n" + 
                          "\n".join([f"• {task}" for task in goal_data.get('daily_tasks', [])]) + 
                          f"\n\n⚙️ *Endi sozlamalarni o'rnatamiz:*\n"
                          f"• Kunlik vazifalar vaqtini belgilang\n"
                          f"• Motivatsiya xabarlari vaqtini belgilang\n"
                          f"• Kechki progress so'rovi vaqtini belgilang",
                "is_final": True,
                "needs_setup": True
            }
            
        except Exception as e:
            logging.error(f"Maqsadni yakunlashda xatolik: {e}")
            return {
                "success": False,
                "message": "❌ Maqsadni yakunlashda xatolik yuz berdi."
            }
    
    async def save_goal(self, user_id: int, title: str, description: str, 
                       target_amount: Optional[float] = None, 
                       target_date: Optional[datetime] = None) -> int:
        """Maqsadni ma'lumotlar bazasiga saqlash"""
        try:
            query = """
            INSERT INTO goals (user_id, title, description, target_amount, target_date, 
                             current_progress, is_active, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            """
            goal_id = await db.execute_insert(query, (
                user_id, title, description, target_amount, target_date, 0.0, True
            ))
            return goal_id
        except Exception as e:
            logging.error(f"Maqsad saqlashda xatolik: {e}")
            return None
    
    async def create_daily_task(self, goal_id: int, task: str) -> int:
        """Kunlik vazifa yaratish"""
        try:
            query = """
            INSERT INTO daily_tasks (goal_id, task, is_completed, due_date, created_at)
            VALUES (%s, %s, %s, %s, NOW())
            """
            task_id = await db.execute_insert(query, (
                goal_id, task, False, datetime.now().date()
            ))
            return task_id
        except Exception as e:
            logging.error(f"Kunlik vazifa yaratishda xatolik: {e}")
            return None
    
    async def get_user_goals(self, user_id: int) -> List[Dict[str, Any]]:
        """Foydalanuvchi maqsadlarini olish"""
        try:
            query = """
            SELECT id, title, description, target_amount, target_date, 
                   current_progress, is_active, created_at
            FROM goals 
            WHERE user_id = %s 
            ORDER BY created_at DESC
            """
            results = await db.execute_query(query, (user_id,))
            
            goals = []
            for row in results:
                goals.append({
                    "id": row[0],
                    "title": row[1],
                    "description": row[2],
                    "target_amount": row[3],
                    "target_date": row[4].strftime("%d.%m.%Y") if row[4] else "Muddat yo'q",
                    "current_progress": float(row[5]),
                    "is_active": bool(row[6]),
                    "created_at": row[7].strftime("%d.%m.%Y")
                })
            
            return goals
        except Exception as e:
            logging.error(f"Maqsadlarni olishda xatolik: {e}")
            return []
    
    async def get_today_tasks(self, user_id: int) -> List[Dict[str, Any]]:
        """Bugungi kunlik vazifalarni olish"""
        try:
            query = """
            SELECT dt.id, dt.task, dt.is_completed, g.title as goal_title
            FROM daily_tasks dt
            JOIN goals g ON dt.goal_id = g.id
            WHERE g.user_id = %s AND dt.due_date = CURDATE()
            ORDER BY dt.created_at ASC
            """
            results = await db.execute_query(query, (user_id,))
            
            tasks = []
            for row in results:
                tasks.append({
                    "id": row[0],
                    "task": row[1],
                    "is_completed": bool(row[2]),
                    "goal_title": row[3]
                })
            
            return tasks
        except Exception as e:
            logging.error(f"Bugungi vazifalarni olishda xatolik: {e}")
            return []
    
    async def mark_task_completed(self, task_id: int, user_id: int) -> bool:
        """Kunlik vazifani bajarilgan deb belgilash"""
        try:
            query = """
            UPDATE daily_tasks dt
            JOIN goals g ON dt.goal_id = g.id
            SET dt.is_completed = TRUE
            WHERE dt.id = %s AND g.user_id = %s
            """
            await db.execute_query(query, (task_id, user_id))
            return True
        except Exception as e:
            logging.error(f"Vazifani bajarilgan deb belgilashda xatolik: {e}")
            return False
    
    async def get_goal_progress(self, goal_id: int) -> Dict[str, Any]:
        """Maqsad progressini olish"""
        try:
            # Maqsad ma'lumotlari
            goal_query = """
            SELECT title, target_amount, target_date, current_progress, created_at
            FROM goals WHERE id = %s
            """
            goal_result = await db.execute_one(goal_query, (goal_id,))
            
            if not goal_result:
                return None
            
            # Kunlik vazifalar statistikasi
            tasks_query = """
            SELECT 
                COUNT(*) as total_tasks,
                SUM(CASE WHEN is_completed = TRUE THEN 1 ELSE 0 END) as completed_tasks
            FROM daily_tasks 
            WHERE goal_id = %s
            """
            tasks_result = await db.execute_one(tasks_query, (goal_id,))
            
            total_tasks = tasks_result[0] if tasks_result else 0
            completed_tasks = tasks_result[1] if tasks_result else 0
            
            # Progress foizini hisoblash
            task_progress = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0
            
            return {
                "title": goal_result[0],
                "target_amount": goal_result[1],
                "target_date": goal_result[2].strftime("%d.%m.%Y") if goal_result[2] else None,
                "current_progress": float(goal_result[3]),
                "total_tasks": total_tasks,
                "completed_tasks": completed_tasks,
                "task_progress": task_progress,
                "created_at": goal_result[4].strftime("%d.%m.%Y")
            }
        except Exception as e:
            logging.error(f"Maqsad progressini olishda xatolik: {e}")
            return None
    
    async def generate_daily_advice(self, user_id: int) -> str:
        """Kunlik maslahat yaratish"""
        try:
            # Foydalanuvchi maqsadlarini olish
            goals = await self.get_user_goals(user_id)
            active_goals = [g for g in goals if g['is_active']]
            
            if not active_goals:
                return "🎯 Hozircha faol maqsadlar yo'q. Yangi maqsad yarating!"
            
            # AI orqali kunlik maslahat yaratish
            goals_text = "\n".join([f"- {goal['title']}: {goal['description']}" for goal in active_goals[:3]])
            
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": "Siz maqsadlarga erishish bo'yicha maslahatchi AI siz. Foydalanuvchiga qisqa va foydali kunlik maslahat bering."
                    },
                    {
                        "role": "user",
                        "content": f"Men quyidagi maqsadlarga erishmoqchiman:\n{goals_text}\n\nBugun nima qilishim kerak?"
                    }
                ],
                temperature=0.8,
                max_tokens=200
            )
            
            advice = response.choices[0].message.content
            return f"💡 *Kunlik maslahat*\n\n{advice}"
            
        except Exception as e:
            logging.error(f"Kunlik maslahat yaratishda xatolik: {e}")
            return "💡 Bugun maqsadlaringizga qadam qo'ying! Har bir kichik harakat sizni orzularingizga yaqinlashtiradi."
    
    def format_goals_message(self, goals: List[Dict[str, Any]]) -> str:
        """Maqsadlar ro'yxatini formatlash"""
        if not goals:
            return "🎯 Hozircha maqsadlar mavjud emas.\n\nYangi maqsad yarating va AI sizga yordam beradi!"
        
        message = "🎯 *Mening maqsadlarim*\n\n"
        
        for i, goal in enumerate(goals, 1):
            status = "🟢" if goal['is_active'] else "🔴"
            message += f"{i}. {status} *{goal['title']}*\n"
            message += f"   📝 {goal['description']}\n"
            if goal['target_amount']:
                message += f"   💰 Maqsad: {goal['target_amount']:,.0f} so'm\n"
            message += f"   📅 {goal['target_date']}\n"
            message += f"   📊 Progress: {goal['current_progress']:.1f}%\n\n"
        
        return message
    
    def format_today_tasks_message(self, tasks: List[Dict[str, Any]]) -> str:
        """Bugungi kunlik vazifalar xabari"""
        if not tasks:
            return "🎉 *Bugun barcha kunlik vazifalar bajarildi!*\n\nYangi maqsad yarating yoki dam oling."
        
        message = "📅 *Bugungi kunlik vazifalar*\n\n"
        
        for i, task in enumerate(tasks, 1):
            status = "✅" if task['is_completed'] else "⏳"
            message += f"{i}. {status} *{task['task']}*\n"
            message += f"   🎯 {task['goal_title']}\n\n"
        
        return message
    
    async def get_active_goal(self, user_id: int) -> Dict[str, Any]:
        """Foydalanuvchining faol maqsadini olish"""
        try:
            query = """
            SELECT id, title, description, current_progress, created_at
            FROM goals 
            WHERE user_id = %s AND is_active = 1 
            ORDER BY created_at DESC 
            LIMIT 1
            """
            result = await db.execute_one(query, (user_id,))
            
            if not result:
                return None
            
            goal_data = {
                'id': result[0],
                'title': result[1],
                'description': result[2],
                'strategy': 'Strategiya mavjud emas',  # Default qiymat
                'progress': result[3],
                'created_at': result[4]
            }
            
            return goal_data
            
        except Exception as e:
            logging.error(f"Faol maqsadni olishda xatolik: {e}")
            return None
