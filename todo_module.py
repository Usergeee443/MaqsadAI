import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from database import db
from models import Todo

class TodoModule:
    def __init__(self):
        pass
    
    async def create_todo(self, user_id: int, title: str, description: str = None, 
                         due_date: datetime = None) -> int:
        """Yangi vazifa yaratish"""
        try:
            query = """
            INSERT INTO todos (user_id, title, description, due_date, is_completed, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            """
            todo_id = await db.execute_insert(query, (
                user_id, title, description, due_date, False
            ))
            return todo_id
        except Exception as e:
            logging.error(f"Vazifa yaratishda xatolik: {e}")
            return None
    
    async def get_user_todos(self, user_id: int, completed: bool = None) -> List[Dict[str, Any]]:
        """Foydalanuvchi vazifalarini olish"""
        try:
            if completed is None:
                query = """
                SELECT id, title, description, due_date, is_completed, created_at
                FROM todos 
                WHERE user_id = %s 
                ORDER BY created_at DESC
                """
                params = (user_id,)
            else:
                query = """
                SELECT id, title, description, due_date, is_completed, created_at
                FROM todos 
                WHERE user_id = %s AND is_completed = %s
                ORDER BY created_at DESC
                """
                params = (user_id, completed)
            
            results = await db.execute_query(query, params)
            
            todos = []
            for row in results:
                todos.append({
                    "id": row[0],
                    "title": row[1],
                    "description": row[2] or "Mavjud emas",
                    "due_date": row[3].strftime("%d.%m.%Y") if row[3] else "Muddat yo'q",
                    "is_completed": bool(row[4]),
                    "created_at": row[5].strftime("%d.%m.%Y %H:%M")
                })
            
            return todos
        except Exception as e:
            logging.error(f"Vazifalarni olishda xatolik: {e}")
            return []
    
    async def mark_todo_completed(self, todo_id: int, user_id: int) -> bool:
        """Vazifani bajarilgan deb belgilash"""
        try:
            query = """
            UPDATE todos 
            SET is_completed = TRUE 
            WHERE id = %s AND user_id = %s
            """
            await db.execute_query(query, (todo_id, user_id))
            return True
        except Exception as e:
            logging.error(f"Vazifani bajarilgan deb belgilashda xatolik: {e}")
            return False
    
    async def delete_todo(self, todo_id: int, user_id: int) -> bool:
        """Vazifani o'chirish"""
        try:
            query = "DELETE FROM todos WHERE id = %s AND user_id = %s"
            await db.execute_query(query, (todo_id, user_id))
            return True
        except Exception as e:
            logging.error(f"Vazifani o'chirishda xatolik: {e}")
            return False
    
    async def get_today_todos(self, user_id: int) -> List[Dict[str, Any]]:
        """Bugungi vazifalarni olish"""
        try:
            query = """
            SELECT id, title, description, due_date, is_completed
            FROM todos 
            WHERE user_id = %s 
            AND (due_date = CURDATE() OR due_date IS NULL)
            AND is_completed = FALSE
            ORDER BY created_at ASC
            """
            results = await db.execute_query(query, (user_id,))
            
            todos = []
            for row in results:
                todos.append({
                    "id": row[0],
                    "title": row[1],
                    "description": row[2] or "Mavjud emas",
                    "due_date": row[3].strftime("%d.%m.%Y") if row[3] else "Muddat yo'q",
                    "is_completed": bool(row[4])
                })
            
            return todos
        except Exception as e:
            logging.error(f"Bugungi vazifalarni olishda xatolik: {e}")
            return []
    
    async def get_overdue_todos(self, user_id: int) -> List[Dict[str, Any]]:
        """Muddati o'tgan vazifalarni olish"""
        try:
            query = """
            SELECT id, title, description, due_date, is_completed
            FROM todos 
            WHERE user_id = %s 
            AND due_date < CURDATE()
            AND is_completed = FALSE
            ORDER BY due_date ASC
            """
            results = await db.execute_query(query, (user_id,))
            
            todos = []
            for row in results:
                todos.append({
                    "id": row[0],
                    "title": row[1],
                    "description": row[2] or "Mavjud emas",
                    "due_date": row[3].strftime("%d.%m.%Y"),
                    "is_completed": bool(row[4])
                })
            
            return todos
        except Exception as e:
            logging.error(f"Muddati o'tgan vazifalarni olishda xatolik: {e}")
            return []
    
    def format_todos_message(self, todos: List[Dict[str, Any]], title: str = "📝 Vazifalar") -> str:
        """Vazifalar ro'yxatini formatlash"""
        if not todos:
            return f"{title}\n\n📋 Hozircha vazifalar mavjud emas."
        
        message = f"{title}\n\n"
        
        for i, todo in enumerate(todos, 1):
            status = "✅" if todo["is_completed"] else "⏳"
            message += f"{i}. {status} *{todo['title']}*\n"
            message += f"   📝 {todo['description']}\n"
            message += f"   📅 {todo['due_date']}\n\n"
        
        return message
    
    def format_today_todos_message(self, todos: List[Dict[str, Any]]) -> str:
        """Bugungi vazifalar xabari"""
        if not todos:
            return "🎉 *Bugun barcha vazifalar bajarildi!*\n\nYangi vazifa qo'shing yoki dam oling."
        
        message = "📅 *Bugungi vazifalar*\n\n"
        
        for i, todo in enumerate(todos, 1):
            message += f"{i}. ⏳ *{todo['title']}*\n"
            if todo['description'] != "Mavjud emas":
                message += f"   📝 {todo['description']}\n"
            message += "\n"
        
        return message
    
    async def get_todo_statistics(self, user_id: int) -> Dict[str, int]:
        """Vazifalar statistikasi"""
        try:
            # Jami vazifalar
            total_query = "SELECT COUNT(*) FROM todos WHERE user_id = %s"
            total_result = await db.execute_one(total_query, (user_id,))
            total_todos = total_result[0] if total_result else 0
            
            # Bajarilgan vazifalar
            completed_query = "SELECT COUNT(*) FROM todos WHERE user_id = %s AND is_completed = TRUE"
            completed_result = await db.execute_one(completed_query, (user_id,))
            completed_todos = completed_result[0] if completed_result else 0
            
            # Muddati o'tgan vazifalar
            overdue_query = """
            SELECT COUNT(*) FROM todos 
            WHERE user_id = %s AND due_date < CURDATE() AND is_completed = FALSE
            """
            overdue_result = await db.execute_one(overdue_query, (user_id,))
            overdue_todos = overdue_result[0] if overdue_result else 0
            
            return {
                "total": total_todos,
                "completed": completed_todos,
                "pending": total_todos - completed_todos,
                "overdue": overdue_todos
            }
        except Exception as e:
            logging.error(f"Vazifalar statistikasini olishda xatolik: {e}")
            return {"total": 0, "completed": 0, "pending": 0, "overdue": 0}
