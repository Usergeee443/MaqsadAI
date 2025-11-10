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
                    tariff ENUM('NONE', 'FREE', 'PLUS', 'PRO', 'FAMILY', 'FAMILY_PLUS', 'FAMILY_PRO', 'BUSINESS', 'BUSINESS_PLUS', 'BUSINESS_PRO', 'EMPLOYEE') DEFAULT 'NONE',
                    tariff_expires_at DATETIME NULL,
                    manager_id BIGINT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (manager_id) REFERENCES users(user_id) ON DELETE SET NULL
                )
            """)

            # Ensure existing installations support new ENUM values and default
            try:
                await self.execute_query(
                    "ALTER TABLE users MODIFY COLUMN tariff "
                    "ENUM('NONE', 'FREE', 'PLUS', 'PRO', 'FAMILY', 'FAMILY_PLUS', 'FAMILY_PRO', 'BUSINESS', 'BUSINESS_PLUS', 'BUSINESS_PRO', 'EMPLOYEE') "
                    "DEFAULT 'NONE'"
                )
            except Exception as e:
                logging.debug(f"Users tariff enum alter skipped: {e}")
            
            # Transactions jadvali
            await self.execute_query("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT,
                    transaction_type ENUM('income', 'expense', 'debt') NOT NULL,
                    amount DECIMAL(15,2) NOT NULL,
                    category VARCHAR(100),
                    description TEXT,
                    due_date DATE NULL,
                    debt_direction ENUM('lent','borrowed') NULL,
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
            
            # Income settings jadvali
            await self.execute_query("""
                CREATE TABLE IF NOT EXISTS income_settings (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT,
                    income_type ENUM('business', 'monthly', 'weekly', 'daily', 'yearly') NOT NULL,
                    amount DECIMAL(15,2),
                    frequency_day INT,
                    frequency_month INT,
                    frequency_weekday INT,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)
            
            # Income reminders jadvali
            await self.execute_query("""
                CREATE TABLE IF NOT EXISTS income_reminders (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT,
                    reminder_date DATE,
                    expected_amount DECIMAL(15,2),
                    received_amount DECIMAL(15,2),
                    status ENUM('pending', 'received_full', 'received_partial', 'not_received') DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)
            
            # account_type ustunini qo'shish (SHI, OILA, BIZNES)
            try:
                await self.execute_query("ALTER TABLE users ADD COLUMN account_type VARCHAR(20) DEFAULT 'SHI'")
                logging.info("Ustun account_type qo'shildi")
            except Exception as e:
                logging.info(f"Ustun account_type allaqachon mavjud: {e}")
                pass
            
            # Yangi ustunlarni qo'shish (agar mavjud bo'lmasa)
            await self.add_missing_columns()
            
            # manager_id ustunini qo'shish (agar mavjud bo'lmasa)
            try:
                await self.execute_query("ALTER TABLE users ADD COLUMN manager_id BIGINT NULL")
                await self.execute_query("ALTER TABLE users ADD FOREIGN KEY (manager_id) REFERENCES users(user_id) ON DELETE SET NULL")
            except Exception:
                pass  # Ustun allaqachon mavjud
            
            # User steps jadvali - onboarding bosqichlari uchun
            await self.execute_query("""
                CREATE TABLE IF NOT EXISTS user_steps (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    current_step INT DEFAULT 1,
                    step_1_name VARCHAR(255) NULL,
                    step_2_age INT NULL,
                    step_3_occupation VARCHAR(255) NULL,
                    step_4_income_source VARCHAR(255) NULL,
                    step_5_family_status VARCHAR(255) NULL,
                    step_6_financial_goals TEXT NULL,
                    step_7_expense_categories TEXT NULL,
                    step_8_savings_habits VARCHAR(255) NULL,
                    step_9_investment_experience VARCHAR(255) NULL,
                    step_10_preferred_communication VARCHAR(255) NULL,
                    status ENUM('in_progress', 'completed') DEFAULT 'in_progress',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    UNIQUE KEY unique_user (user_id)
                )
            """)
            
            # User subscriptions jadvali - ko'p tarif tizimi uchun
            await self.execute_query("""
                CREATE TABLE IF NOT EXISTS user_subscriptions (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    tariff ENUM('PLUS', 'BUSINESS', 'PRO', 'FAMILY', 'FAMILY_PLUS', 'FAMILY_PRO', 'BUSINESS_PLUS', 'BUSINESS_PRO', 'EMPLOYEE') NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    expires_at DATETIME NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    UNIQUE KEY unique_user_tariff (user_id, tariff),
                    INDEX idx_user_id (user_id),
                    INDEX idx_tariff (tariff),
                    INDEX idx_is_active (is_active)
                )
            """)
            
            # Payments jadvali
            await self.execute_query("""
                CREATE TABLE IF NOT EXISTS payments (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    tariff ENUM('FREE', 'PLUS', 'MAX', 'FAMILY', 'FAMILY_PLUS', 'FAMILY_MAX', 'BUSINESS', 'BUSINESS_PLUS', 'BUSINESS_MAX', 'EMPLOYEE') NOT NULL,
                    provider VARCHAR(50) DEFAULT 'telegram_click',
                    total_amount BIGINT NOT NULL,
                    currency VARCHAR(10) NOT NULL,
                    payload VARCHAR(255),
                    telegram_charge_id VARCHAR(255),
                    provider_charge_id VARCHAR(255),
                    status ENUM('pending','paid','failed') DEFAULT 'paid',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    paid_at TIMESTAMP NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)
            
            # AI Chat History jadvali
            await self.execute_query("""
                CREATE TABLE IF NOT EXISTS ai_chat_history (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    role ENUM('user', 'assistant', 'system') NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    INDEX idx_user_id (user_id),
                    INDEX idx_created_at (created_at)
                )
            """)
            
            # Config jadvali - bot sozlamalari uchun
            await self.execute_query("""
                CREATE TABLE IF NOT EXISTS config (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    key_name VARCHAR(100) UNIQUE NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_key (key_name)
                )
            """)
            
            # Plus paket xaridlari jadvali
            await self.execute_query("""
                CREATE TABLE IF NOT EXISTS plus_package_purchases (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    package_code VARCHAR(20) NOT NULL,
                    text_limit INT NOT NULL,
                    text_used INT DEFAULT 0,
                    voice_limit INT NOT NULL,
                    voice_used INT DEFAULT 0,
                    status ENUM('active','completed') DEFAULT 'active',
                    purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    INDEX idx_user_status (user_id, status),
                    INDEX idx_user_purchased (user_id, purchased_at)
                )
            """)
            
            # Debts jadvali - qarzlar uchun
            await self.execute_query("""
                CREATE TABLE IF NOT EXISTS debts (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    debt_type ENUM('lent', 'borrowed') NOT NULL,
                    amount DECIMAL(15,2) NOT NULL,
                    person_name VARCHAR(255),
                    due_date DATE NULL,
                    status ENUM('active', 'paid') DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    INDEX idx_user_id (user_id),
                    INDEX idx_status (status)
                )
            """)
            
            # Debt reminders jadvali
            await self.execute_query("""
                CREATE TABLE IF NOT EXISTS debt_reminders (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    transaction_id INT NULL,
                    reminder_date DATE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    FOREIGN KEY (transaction_id) REFERENCES transactions(id) ON DELETE CASCADE
                )
            """)
            
            # Boshlang'ich qiymatlarni qo'shish
            await self.execute_query("""
                INSERT IGNORE INTO config (key_name, value) VALUES
                ('active_speech_google', 'false'),
                ('active_speech_elevenlabs', 'true'),
                ('active_speech_whisper', 'false'),
                ('free_trial_plus', 'true'),
                ('free_trial_max', 'true'),
                ('free_trial_business', 'true')
            """)

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
                ("tariff_expires_at", "DATETIME NULL")
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
                await self.execute_query(
                    "ALTER TABLE users MODIFY COLUMN tariff "
                    "ENUM('NONE', 'FREE', 'PLUS', 'PRO', 'FAMILY', 'FAMILY_PLUS', 'FAMILY_PRO', "
                    "'BUSINESS', 'BUSINESS_PLUS', 'BUSINESS_PRO', 'EMPLOYEE') DEFAULT 'NONE'"
                )
                logging.info("Tarif enum yangilandi")
            except Exception as e:
                logging.error(f"Tarif enum yangilashda xatolik: {e}")
            
            # User subscriptions jadvalini yangilash
            try:
                await self.execute_query("ALTER TABLE user_subscriptions MODIFY COLUMN tariff ENUM('PLUS', 'BUSINESS', 'PRO', 'FAMILY', 'FAMILY_PLUS', 'FAMILY_PRO', 'BUSINESS_PLUS', 'BUSINESS_PRO', 'EMPLOYEE') NOT NULL")
                logging.info("User subscriptions tariff enum yangilandi")
            except Exception as e:
                logging.error(f"User subscriptions tariff enum yangilashda xatolik: {e}")
            
            # Payments jadvalini yangilash
            try:
                await self.execute_query("ALTER TABLE payments MODIFY COLUMN tariff ENUM('FREE', 'PLUS', 'PRO', 'FAMILY', 'FAMILY_PLUS', 'FAMILY_PRO', 'BUSINESS', 'BUSINESS_PLUS', 'BUSINESS_PRO', 'EMPLOYEE') NOT NULL")
                logging.info("Payments tariff enum yangilandi")
            except Exception as e:
                logging.error(f"Payments tariff enum yangilashda xatolik: {e}")
            
            # Premium tarifli foydalanuvchilarni FREE ga o'zgartirish
            try:
                await self.execute_query("UPDATE users SET tariff = 'FREE' WHERE tariff = 'PREMIUM'")
                await self.execute_query("UPDATE payments SET tariff = 'FREE' WHERE tariff = 'PREMIUM'")
                await self.execute_query("UPDATE user_subscriptions SET tariff = 'FREE' WHERE tariff = 'PREMIUM'")
                logging.info("Premium tarifli foydalanuvchilar FREE ga o'zgartirildi")
            except Exception as e:
                logging.error(f"Premium tarifni FREE ga o'zgartirishda xatolik: {e}")

            # Transactions jadvaliga yangi ustunlar
            trans_columns = [
                ("due_date", "DATE NULL"),
                ("debt_direction", "ENUM('lent','borrowed') NULL")
            ]
            for column_name, column_definition in trans_columns:
                try:
                    await self.execute_query(f"ALTER TABLE transactions ADD COLUMN {column_name} {column_definition}")
                    logging.info(f"transactions.{column_name} qo'shildi")
                except Exception as e:
                    if "Duplicate column name" in str(e):
                        logging.info(f"transactions.{column_name} allaqachon mavjud")
                    else:
                        logging.error(f"transactions.{column_name} qo'shishda xatolik: {e}")

            # Qarz eslatmalari jadvali
            try:
                await self.execute_query("""
                    CREATE TABLE IF NOT EXISTS debt_reminders (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        transaction_id INT NOT NULL,
                        reminder_date DATE NOT NULL,
                        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY uniq_user_tx_date (user_id, transaction_id, reminder_date),
                        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                        FOREIGN KEY (transaction_id) REFERENCES transactions(id) ON DELETE CASCADE
                    )
                """)
            except Exception as e:
                logging.error(f"debt_reminders jadvalini yaratishda xatolik: {e}")
                
        except Exception as e:
            logging.error(f"Ustunlar qo'shishda xatolik: {e}")

    async def get_user_data(self, user_id):
        """Foydalanuvchi ma'lumotlarini olish"""
        query = """
        SELECT user_id, username, first_name, last_name, phone, name, source, tariff, created_at, tariff_expires_at
        FROM users 
        WHERE user_id = %s
        """
        result = await self.execute_one(query, (user_id,))
        if result:
            tariff = result[7]
            if tariff in (None, 'FREE'):
                tariff = 'NONE'
            return {
                'user_id': result[0],
                'username': result[1],
                'first_name': result[2],
                'last_name': result[3],
                'phone': result[4],
                'name': result[5],
                'source': result[6],
                'tariff': tariff,
                'created_at': result[8],
                'tariff_expires_at': result[9],
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
        
        # Qarzlar (yo'nalma bo'yicha)
        borrowed_query = "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE user_id = %s AND transaction_type = 'debt' AND debt_direction = 'borrowed'"
        borrowed_result = await self.execute_one(borrowed_query, (user_id,))
        borrowed = float(borrowed_result[0]) if borrowed_result else 0.0

        lent_query = "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE user_id = %s AND transaction_type = 'debt' AND debt_direction = 'lent'"
        lent_result = await self.execute_one(lent_query, (user_id,))
        lent = float(lent_result[0]) if lent_result else 0.0

        # Naqd balans: kirim + olingan qarz - chiqim - berilgan qarz
        cash_balance = income + borrowed - expense - lent
        # Sof balans: faqat kirim - chiqim (qarz olingan pul sof balansga hisoblanmaydi)
        net_balance = income - expense
        
        return {
            'income': income,
            'expense': expense,
            'borrowed': borrowed,
            'lent': lent,
            'cash_balance': cash_balance,
            'net_balance': net_balance,
            'total_income': income,
            'total_expense': expense,
            'total_borrowed_debt': borrowed,
            'total_lent_debt': lent
        }

    async def get_balances(self, user_id):
        """Kengaytirilgan balanslarni olish (naqd va sof)"""
        return await self.get_balance(user_id)

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
    
    # Income settings funksiyalari
    async def save_income_settings(self, user_id, income_type, amount=None, frequency_day=None, frequency_month=None, frequency_weekday=None):
        """Daromad sozlamalarini saqlash"""
        query = """
        INSERT INTO income_settings (user_id, income_type, amount, frequency_day, frequency_month, frequency_weekday)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
        income_type = VALUES(income_type),
        amount = VALUES(amount),
        frequency_day = VALUES(frequency_day),
        frequency_month = VALUES(frequency_month),
        frequency_weekday = VALUES(frequency_weekday),
        updated_at = CURRENT_TIMESTAMP
        """
        return await self.execute_insert(query, (user_id, income_type, amount, frequency_day, frequency_month, frequency_weekday))
    
    async def get_income_settings(self, user_id):
        """Foydalanuvchining daromad sozlamalarini olish"""
        query = """
        SELECT income_type, amount, frequency_day, frequency_month, frequency_weekday, is_active
        FROM income_settings 
        WHERE user_id = %s AND is_active = TRUE
        """
        return await self.execute_one(query, (user_id,))
    
    async def create_income_reminder(self, user_id, reminder_date, expected_amount):
        """Daromad eslatmasini yaratish"""
        query = """
        INSERT INTO income_reminders (user_id, reminder_date, expected_amount)
        VALUES (%s, %s, %s)
        """
        return await self.execute_insert(query, (user_id, reminder_date, expected_amount))
    
    async def update_income_reminder(self, user_id, reminder_date, received_amount, status):
        """Daromad eslatmasini yangilash"""
        query = """
        UPDATE income_reminders 
        SET received_amount = %s, status = %s
        WHERE user_id = %s AND reminder_date = %s
        """
        return await self.execute_query(query, (received_amount, status, user_id, reminder_date))
    
    async def get_pending_reminders(self, user_id):
        """Kutilayotgan eslatmalarni olish"""
        query = """
        SELECT id, reminder_date, expected_amount, status
        FROM income_reminders 
        WHERE user_id = %s AND status = 'pending' AND reminder_date <= CURDATE()
        """
        return await self.execute_query(query, (user_id,))

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
    
    async def add_user_subscription(self, user_id, tariff, expires_at):
        """Foydalanuvchiga yangi tarif qo'shish"""
        query = """
        INSERT INTO user_subscriptions (user_id, tariff, expires_at)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE 
        is_active = TRUE, expires_at = VALUES(expires_at)
        """
        return await self.execute_query(query, (user_id, tariff, expires_at))
    
    async def get_user_subscriptions(self, user_id):
        """Foydalanuvchining barcha tariflarini olish"""
        query = """
        SELECT tariff, is_active, expires_at, created_at
        FROM user_subscriptions
        WHERE user_id = %s AND expires_at > NOW()
        ORDER BY created_at DESC
        """
        return await self.execute_query(query, (user_id,))
    
    async def set_active_tariff(self, user_id, tariff):
        """Foydalanuvchining aktiv tarifini o'rnatish"""
        # Avval barcha tariflarni noaktiv qilamiz
        await self.execute_query(
            "UPDATE user_subscriptions SET is_active = FALSE WHERE user_id = %s",
            (user_id,)
        )
        # Keyin tanlangan tarifni aktiv qilamiz
        await self.execute_query(
            "UPDATE user_subscriptions SET is_active = TRUE WHERE user_id = %s AND tariff = %s",
            (user_id, tariff)
        )
        # Users jadvalidagi tariff ustunini ham yangilaymiz
        await self.execute_query(
            "UPDATE users SET tariff = %s WHERE user_id = %s",
            (tariff, user_id)
        )
    
    # Plus paketlari funksiyalari
    async def create_plus_package_purchase(self, user_id, package_code, text_limit, voice_limit):
        """Foydalanuvchi uchun yangi Plus paket xaridini yaratish"""
        # Avvalgi aktiv paketlarni yopamiz
        await self.execute_query(
            """
            UPDATE plus_package_purchases
            SET status = 'completed', updated_at = NOW()
            WHERE user_id = %s AND status = 'active'
            """,
            (user_id,)
        )
        
        # Yangi paketni yaratamiz
        query = """
        INSERT INTO plus_package_purchases (user_id, package_code, text_limit, voice_limit)
        VALUES (%s, %s, %s, %s)
        """
        return await self.execute_insert(query, (user_id, package_code, text_limit, voice_limit))
    
    async def get_active_plus_package(self, user_id):
        """Foydalanuvchining hozirgi aktiv Plus paketini olish"""
        query = """
        SELECT id, package_code, text_limit, text_used, voice_limit, voice_used, status, purchased_at
        FROM plus_package_purchases
        WHERE user_id = %s AND status = 'active'
        ORDER BY purchased_at DESC
        LIMIT 1
        """
        result = await self.execute_one(query, (user_id,))
        if not result:
            return None
        return {
            'id': result[0],
            'package_code': result[1],
            'text_limit': result[2],
            'text_used': result[3],
            'voice_limit': result[4],
            'voice_used': result[5],
            'status': result[6],
            'purchased_at': result[7],
        }
    
    async def increment_plus_usage(self, user_id, usage_type: str):
        """Plus paketi bo'yicha foydalanishni oshirish"""
        package = await self.get_active_plus_package(user_id)
        if not package:
            return False, None
        
        if usage_type not in ('text', 'voice'):
            return False, package
        
        if usage_type == 'text':
            if package['text_used'] >= package['text_limit']:
                return False, package
            new_used = package['text_used'] + 1
            status = 'completed' if (new_used >= package['text_limit'] and package['voice_used'] >= package['voice_limit']) else 'active'
            await self.execute_query(
                """
                UPDATE plus_package_purchases
                SET text_used = %s, status = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (new_used, status, package['id'])
            )
            package['text_used'] = new_used
            package['status'] = status
        else:
            if package['voice_used'] >= package['voice_limit']:
                return False, package
            new_used = package['voice_used'] + 1
            status = 'completed' if (new_used >= package['voice_limit'] and package['text_used'] >= package['text_limit']) else 'active'
            await self.execute_query(
                """
                UPDATE plus_package_purchases
                SET voice_used = %s, status = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (new_used, status, package['id'])
            )
            package['voice_used'] = new_used
            package['status'] = status
        
        return True, package
    
    async def get_plus_usage_summary(self, user_id):
        """Plus paketi bo'yicha foydalanish statistikasini olish"""
        package = await self.get_active_plus_package(user_id)
        if not package:
            return None
        return {
            'package_code': package['package_code'],
            'text_limit': package['text_limit'],
            'text_used': package['text_used'],
            'voice_limit': package['voice_limit'],
            'voice_used': package['voice_used'],
            'purchased_at': package['purchased_at'],
        }
    
    async def has_active_plus_package(self, user_id):
        """Foydalanuvchining aktiv Plus paketi bor-yo'qligini tekshirish"""
        package = await self.get_active_plus_package(user_id)
        return package is not None
    
    # User steps funksiyalari
    async def get_user_steps(self, user_id):
        """Foydalanuvchining onboarding bosqichlarini olish"""
        query = """
        SELECT * FROM user_steps WHERE user_id = %s
        """
        return await self.execute_one(query, (user_id,))
    
    async def create_user_steps(self, user_id):
        """Foydalanuvchi uchun onboarding bosqichlarini yaratish"""
        query = """
        INSERT INTO user_steps (user_id, current_step, status)
        VALUES (%s, 1, 'in_progress')
        ON DUPLICATE KEY UPDATE current_step = current_step
        """
        return await self.execute_query(query, (user_id,))
    
    async def update_user_step(self, user_id, step_number, step_value):
        """Foydalanuvchining ma'lum bosqichini yangilash"""
        step_column = f"step_{step_number}_{self.get_step_field_name(step_number)}"
        query = f"""
        UPDATE user_steps 
        SET {step_column} = %s, current_step = %s, updated_at = NOW()
        WHERE user_id = %s
        """
        return await self.execute_query(query, (step_value, step_number + 1, user_id))
    
    async def complete_user_steps(self, user_id):
        """Foydalanuvchining onboarding jarayonini yakunlash"""
        query = """
        UPDATE user_steps 
        SET status = 'completed', updated_at = NOW()
        WHERE user_id = %s
        """
        return await self.execute_query(query, (user_id,))
    
    def get_step_field_name(self, step_number):
        """Bosqich nomini olish"""
        step_fields = {
            1: "name",
            2: "age", 
            3: "occupation",
            4: "income_source",
            5: "family_status",
            6: "financial_goals",
            7: "expense_categories",
            8: "savings_habits",
            9: "investment_experience",
            10: "preferred_communication"
        }
        return step_fields.get(step_number, "unknown")
    
    async def get_active_tariff(self, user_id):
        """Foydalanuvchining hozirgi aktiv tarifini olish"""
        # Avvalo Plus paketlarini tekshiramiz
        package = await self.get_active_plus_package(user_id)
        if package:
            return 'PLUS'
        
        query = """
        SELECT tariff FROM user_subscriptions
        WHERE user_id = %s AND is_active = TRUE AND expires_at > NOW()
        LIMIT 1
        """
        result = await self.execute_one(query, (user_id,))
        return result[0] if result else "NONE"

# Global database instance
db = Database()