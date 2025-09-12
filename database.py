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

# Global database instance
db = Database()
