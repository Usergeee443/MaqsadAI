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

    async def create_tables(self):
        """Jadvallarni yaratish"""
        try:
            # Users jadvali
            await self.execute_query("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username VARCHAR(255),
                    first_name VARCHAR(255),
                    last_name VARCHAR(255),
                    phone VARCHAR(20),
                    name VARCHAR(255) DEFAULT 'Xojayin',
                    source VARCHAR(50),
                    tariff ENUM('FREE', 'PRO', 'MAX', 'PREMIUM') DEFAULT 'FREE',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
            """)
            
            # Transactions jadvali
            await self.execute_query("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT,
                    transaction_type ENUM('income', 'expense', 'debt') NOT NULL,
                    amount DECIMAL(15,2) NOT NULL,
                    category VARCHAR(100),
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)
            
            # Categories jadvali
            await self.execute_query("""
                CREATE TABLE IF NOT EXISTS categories (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    type ENUM('income', 'expense', 'debt') NOT NULL,
                    user_id BIGINT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)
            
            # Yangi ustunlarni qo'shish (agar mavjud bo'lmasa)
            await self.add_missing_columns()
            
            logging.info("Jadvallar muvaffaqiyatli yaratildi")
            
        except Exception as e:
            logging.error(f"Jadvallar yaratishda xatolik: {e}")

    async def add_missing_columns(self):
        """Eski jadvallarga yangi ustunlarni qo'shish"""
        try:
            # Users jadvaliga yangi ustunlar qo'shish
            columns_to_add = [
                ("phone", "VARCHAR(20)"),
                ("name", "VARCHAR(255) DEFAULT 'Xojayin'"),
                ("source", "VARCHAR(50)"),
            ]
            
            for column_name, column_definition in columns_to_add:
                try:
                    await self.execute_query(f"ALTER TABLE users ADD COLUMN {column_name} {column_definition}")
                    logging.info(f"Ustun {column_name} qo'shildi")
                except Exception as e:
                    if "Duplicate column name" in str(e):
                        logging.info(f"Ustun {column_name} allaqachon mavjud")
                    else:
                        logging.error(f"Ustun {column_name} qo'shishda xatolik: {e}")
            
            # Tarif enum ni yangilash
            try:
                await self.execute_query("ALTER TABLE users MODIFY COLUMN tariff ENUM('FREE', 'PRO', 'MAX', 'PREMIUM') DEFAULT 'FREE'")
                logging.info("Tarif enum yangilandi")
            except Exception as e:
                logging.error(f"Tarif enum yangilashda xatolik: {e}")
                
        except Exception as e:
            logging.error(f"Ustunlar qo'shishda xatolik: {e}")

    async def get_user_data(self, user_id):
        """Foydalanuvchi ma'lumotlarini olish"""
        query = """
        SELECT user_id, username, first_name, last_name, phone, name, source, tariff, created_at
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
                'phone': result[4],
                'name': result[5],
                'source': result[6],
                'tariff': result[7],
                'created_at': result[8],
                'tariff_expires_at': None,
                'is_active': True
            }
        return None

    async def get_user_transactions(self, user_id, limit=50, offset=0):
        """Foydalanuvchi tranzaksiyalarini olish"""
        query = """
        SELECT id, transaction_type, amount, category, description, created_at
        FROM transactions 
        WHERE user_id = %s 
        ORDER BY created_at DESC 
        LIMIT %s OFFSET %s
        """
        results = await self.execute_query(query, (user_id, limit, offset))
        transactions = []
        for result in results:
            transactions.append({
                'id': result[0],
                'type': result[1],
                'amount': float(result[2]),
                'category': result[3],
                'description': result[4],
                'created_at': result[5]
            })
        return transactions

    async def add_transaction(self, user_id, transaction_type, amount, category, description=None):
        """Yangi tranzaksiya qo'shish"""
        query = """
        INSERT INTO transactions (user_id, transaction_type, amount, category, description)
        VALUES (%s, %s, %s, %s, %s)
        """
        return await self.execute_insert(query, (user_id, transaction_type, amount, category, description))

    async def get_balance(self, user_id):
        """Foydalanuvchi balansini olish"""
        # Kirimlar
        income_query = "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE user_id = %s AND transaction_type = 'income'"
        income_result = await self.execute_one(income_query, (user_id,))
        income = float(income_result[0]) if income_result else 0.0
        
        # Chiqimlar
        expense_query = "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE user_id = %s AND transaction_type = 'expense'"
        expense_result = await self.execute_one(expense_query, (user_id,))
        expense = float(expense_result[0]) if expense_result else 0.0
        
        # Qarzlar
        debt_query = "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE user_id = %s AND transaction_type = 'debt'"
        debt_result = await self.execute_one(debt_query, (user_id,))
        debt = float(debt_result[0]) if debt_result else 0.0
        
        return {
            'income': income,
            'expense': expense,
            'debt': debt,
            'balance': income - expense
        }

    async def get_category_stats(self, user_id, days=30):
        """Kategoriyalar bo'yicha statistikalar"""
        query = """
        SELECT category, transaction_type, SUM(amount) as total, COUNT(*) as count
        FROM transactions 
        WHERE user_id = %s AND created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
        GROUP BY category, transaction_type
        ORDER BY total DESC
        """
        results = await self.execute_query(query, (user_id, days))
        
        stats = {
            'income_categories': {},
            'expense_categories': {},
            'debt_categories': {}
        }
        
        for result in results:
            category, trans_type, total, count = result
            total = float(total)
            
            if trans_type == 'income':
                stats['income_categories'][category] = {'total': total, 'count': count}
            elif trans_type == 'expense':
                stats['expense_categories'][category] = {'total': total, 'count': count}
            elif trans_type == 'debt':
                stats['debt_categories'][category] = {'total': total, 'count': count}
        
        return stats

    async def get_monthly_stats(self, user_id, months=6):
        """Oylik statistikalar"""
        query = """
        SELECT 
            DATE_FORMAT(created_at, '%Y-%m') as month,
            transaction_type,
            SUM(amount) as total
        FROM transactions 
        WHERE user_id = %s AND created_at >= DATE_SUB(NOW(), INTERVAL %s MONTH)
        GROUP BY month, transaction_type
        ORDER BY month DESC
        """
        results = await self.execute_query(query, (user_id, months))
        
        monthly_data = {}
        for result in results:
            month, trans_type, total = result
            if month not in monthly_data:
                monthly_data[month] = {'income': 0, 'expense': 0, 'debt': 0}
            monthly_data[month][trans_type] = float(total)
        
        return monthly_data

# Global database instance
db = Database()