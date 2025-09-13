import aiomysql
import asyncio
from config import MYSQL_CONFIG
import logging

class Database:
    def __init__(self):
        self.pool = None
        
    async def create_pool(self):
        """Ma'lumotlar bazasi ulanishini yaratish"""
        try:
            self.pool = await aiomysql.create_pool(
                host=MYSQL_CONFIG['host'],
                port=3306,
                user=MYSQL_CONFIG['user'],
                password=MYSQL_CONFIG['password'],
                db=MYSQL_CONFIG['database'],
                autocommit=True,
                minsize=1,
                maxsize=10
            )
            logging.info("Ma'lumotlar bazasi ulanishi muvaffaqiyatli yaratildi")
        except Exception as e:
            logging.error(f"Ma'lumotlar bazasi ulanishida xatolik: {e}")
            
    async def close_pool(self):
        """Ma'lumotlar bazasi ulanishini yopish"""
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()
            
    async def execute_query(self, query, params=None):
        """SQL so'rovni bajarish"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, params)
                return await cursor.fetchall()
                
    async def execute_one(self, query, params=None):
        """Bitta natija qaytaruvchi SQL so'rov"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, params)
                return await cursor.fetchone()
                
    async def execute_insert(self, query, params=None):
        """Ma'lumot kiritish so'rovi"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, params)
                return cursor.lastrowid

    async def get_user_data(self, user_id):
        """Foydalanuvchi ma'lumotlarini olish"""
        query = """
        SELECT user_id, username, first_name, last_name, tariff, 
               tariff_expires_at, created_at, is_active
        FROM users 
        WHERE user_id = %s
        """
        result = await self.execute_one(query, (user_id,))
        if result:
            return {
                'user_id': result[0],
                'username': result[1],
                'first_name': result[2],
                'last_name': result[3],
                'tariff': result[4],
                'tariff_expires_at': result[5],
                'created_at': result[6],
                'is_active': result[7]
            }
        return None

    async def get_goal_reminder_settings(self, user_id):
        """Maqsad AI eslatmalar sozlamalarini olish"""
        query = """
        SELECT daily_task_time, motivation_time, progress_check_time
        FROM goal_reminder_settings 
        WHERE user_id = %s
        """
        result = await self.execute_one(query, (user_id,))
        if result:
            return {
                'daily_task_time': result[0],
                'motivation_time': result[1],
                'progress_check_time': result[2]
            }
        return None

    async def update_goal_reminder_settings(self, user_id, daily_task_time=None, 
                                          motivation_time=None, progress_check_time=None):
        """Maqsad AI eslatmalar sozlamalarini yangilash"""
        # Avval mavjudligini tekshirish
        check_query = "SELECT id FROM goal_reminder_settings WHERE user_id = %s"
        exists = await self.execute_one(check_query, (user_id,))
        
        if exists:
            # Yangilash
            update_fields = []
            params = []
            
            if daily_task_time is not None:
                update_fields.append("daily_task_time = %s")
                params.append(daily_task_time)
            if motivation_time is not None:
                update_fields.append("motivation_time = %s")
                params.append(motivation_time)
            if progress_check_time is not None:
                update_fields.append("progress_check_time = %s")
                params.append(progress_check_time)
            
            if update_fields:
                params.append(user_id)
                query = f"UPDATE goal_reminder_settings SET {', '.join(update_fields)} WHERE user_id = %s"
                await self.execute_query(query, params)
        else:
            # Yangi yaratish
            query = """
            INSERT INTO goal_reminder_settings 
            (user_id, daily_task_time, motivation_time, progress_check_time)
            VALUES (%s, %s, %s, %s)
            """
            await self.execute_query(query, (user_id, daily_task_time or '08:00:00',
                                           motivation_time or '09:00:00', 
                                           progress_check_time or '21:00:00'))

# Global database instance
db = Database()
