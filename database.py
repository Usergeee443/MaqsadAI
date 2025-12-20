import aiomysql
import asyncio
from config import MYSQL_CONFIG
import logging

class Database:
    def __init__(self):
        self.pool = None
        
    async def create_pool(self):
        """Ma'lumotlar bazasi ulanishini yaratish.
        
        Agar ulanish muvaffaqiyatsiz bo'lsa, xato log qilinadi va istisno qayta ko'tariladi.
        Shunda bot DB bo'lmasa, ishlashni davom ettirmaydi.
        """
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
            # Pool yaratilmagan bo'lsa, uni None qilib qo'yamiz va xatoni qayta ko'taramiz
            self.pool = None
            raise
            
    async def close_pool(self):
        """Ma'lumotlar bazasi ulanishini yopish"""
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()
            
    async def execute_query(self, query, params=None):
        """SQL so'rovni bajarish - dict qaytaradi"""
        if not self.pool:
            raise RuntimeError("Database pool mavjud emas. Avval create_pool() chaqirilishi kerak.")
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(query, params)
                return await cursor.fetchall()
                
    async def execute_one(self, query, params=None):
        """Bitta natija qaytaruvchi SQL so'rov - dict qaytaradi"""
        if not self.pool:
            raise RuntimeError("Database pool mavjud emas. Avval create_pool() chaqirilishi kerak.")
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(query, params)
                return await cursor.fetchone()
                
    async def execute_insert(self, query, params=None):
        """Ma'lumot kiritish so'rovi"""
        if not self.pool:
            raise RuntimeError("Database pool mavjud emas. Avval create_pool() chaqirilishi kerak.")
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
            
            # Pro tarifida API xarajatlari tracking jadvali
            await self.execute_query("""
                CREATE TABLE IF NOT EXISTS pro_usage_tracking (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    month_year VARCHAR(7) NOT NULL,
                    text_cost DECIMAL(10,2) DEFAULT 0,
                    voice_cost DECIMAL(10,2) DEFAULT 0,
                    total_cost DECIMAL(10,2) DEFAULT 0,
                    text_count INT DEFAULT 0,
                    voice_count INT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    UNIQUE KEY unique_user_month (user_id, month_year),
                    INDEX idx_user_month (user_id, month_year)
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
            
            # Reminders jadvali - umumiy eslatmalar uchun (Pro va Plus)
            await self.execute_query("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    reminder_type ENUM('debt_give', 'debt_receive', 'payment', 'meeting', 'event', 'task', 'other') NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    description TEXT,
                    reminder_date DATE NOT NULL,
                    reminder_time TIME DEFAULT '09:00:00',
                    amount DECIMAL(15,2) NULL,
                    currency VARCHAR(10) DEFAULT 'UZS',
                    person_name VARCHAR(255) NULL,
                    location VARCHAR(255) NULL,
                    is_recurring BOOLEAN DEFAULT FALSE,
                    recurrence_pattern ENUM('daily', 'weekly', 'monthly', 'yearly') NULL,
                    recurrence_day INT NULL,
                    notification_30min_sent BOOLEAN DEFAULT FALSE,
                    notification_exact_sent BOOLEAN DEFAULT FALSE,
                    is_completed BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    INDEX idx_user_date (user_id, reminder_date),
                    INDEX idx_user_completed (user_id, is_completed),
                    INDEX idx_reminder_date (reminder_date, is_completed),
                    INDEX idx_notification (reminder_date, reminder_time, notification_30min_sent, notification_exact_sent)
                )
            """)
            
            # Reminders jadvaliga yangi ustunlar qo'shish (agar mavjud bo'lmasa)
            reminder_columns = [
                ("location", "VARCHAR(255) NULL"),
                ("is_recurring", "BOOLEAN DEFAULT FALSE"),
                ("recurrence_pattern", "ENUM('daily', 'weekly', 'monthly', 'yearly') NULL"),
                ("recurrence_day", "INT NULL"),
                ("notification_30min_sent", "BOOLEAN DEFAULT FALSE"),
                ("notification_exact_sent", "BOOLEAN DEFAULT FALSE")
            ]
            for col_name, col_def in reminder_columns:
                try:
                    await self.execute_query(f"ALTER TABLE reminders ADD COLUMN {col_name} {col_def}")
                except Exception:
                    pass  # Ustun allaqachon mavjud
            
            # reminder_type ni yangilash (yangi qiymatlar qo'shish)
            try:
                await self.execute_query("""
                    ALTER TABLE reminders MODIFY COLUMN reminder_type 
                    ENUM('debt_give', 'debt_receive', 'payment', 'meeting', 'event', 'task', 'other') NOT NULL
                """)
            except Exception:
                pass
            
            # Warehouse (Ombor) jadvallari - Biznes tarif uchun
            # Tovarlar jadvali
            await self.execute_query("""
                CREATE TABLE IF NOT EXISTS warehouse_products (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    category VARCHAR(100),
                    barcode VARCHAR(100),
                    price DECIMAL(15, 2) DEFAULT 0,
                    quantity INT DEFAULT 0,
                    min_quantity INT DEFAULT 0,
                    image_url VARCHAR(500),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    INDEX idx_user (user_id),
                    INDEX idx_category (category),
                    INDEX idx_barcode (barcode)
                )
            """)
            
            # Ombor harakatlari (kirim/chiqim) jadvali
            await self.execute_query("""
                CREATE TABLE IF NOT EXISTS warehouse_movements (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    product_id INT NOT NULL,
                    movement_type ENUM('in', 'out') NOT NULL,
                    quantity INT NOT NULL,
                    unit_price DECIMAL(15, 2),
                    total_cost DECIMAL(15, 2),
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    FOREIGN KEY (product_id) REFERENCES warehouse_products(id) ON DELETE CASCADE,
                    INDEX idx_user (user_id),
                    INDEX idx_product (product_id),
                    INDEX idx_type (movement_type),
                    INDEX idx_date (created_at)
                )
            """)
            
            # Ombor xarajatlari jadvali
            await self.execute_query("""
                CREATE TABLE IF NOT EXISTS warehouse_expenses (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    product_id INT,
                    movement_id INT,
                    expense_type ENUM('purchase', 'storage', 'transport', 'other') NOT NULL,
                    amount DECIMAL(15, 2) NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    FOREIGN KEY (product_id) REFERENCES warehouse_products(id) ON DELETE SET NULL,
                    FOREIGN KEY (movement_id) REFERENCES warehouse_movements(id) ON DELETE SET NULL,
                    INDEX idx_user (user_id),
                    INDEX idx_product (product_id),
                    INDEX idx_type (expense_type)
                )
            """)
            
            # Biznes xodimlar jadvali
            await self.execute_query("""
                CREATE TABLE IF NOT EXISTS business_employees (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    owner_id BIGINT NOT NULL,
                    telegram_id BIGINT NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    role ENUM('employee', 'manager') DEFAULT 'employee',
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (owner_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    INDEX idx_owner (owner_id),
                    INDEX idx_telegram (telegram_id),
                    INDEX idx_active (is_active)
                )
            """)
            
            # Biznes vazifalari jadvali
            await self.execute_query("""
                CREATE TABLE IF NOT EXISTS business_tasks (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    owner_id BIGINT NOT NULL,
                    employee_id INT,
                    title VARCHAR(255) NOT NULL,
                    description TEXT,
                    due_date DATETIME,
                    status ENUM('pending', 'in_progress', 'completed', 'cancelled') DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP NULL,
                    FOREIGN KEY (owner_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    FOREIGN KEY (employee_id) REFERENCES business_employees(id) ON DELETE SET NULL,
                    INDEX idx_owner (owner_id),
                    INDEX idx_employee (employee_id),
                    INDEX idx_status (status)
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
            
            # Warehouse_products ga unit ustunini qo'shish
            try:
                await self.execute_query("ALTER TABLE warehouse_products ADD COLUMN unit VARCHAR(50) DEFAULT 'dona'")
                logging.info("warehouse_products.unit qo'shildi")
            except Exception as e:
                if "Duplicate column name" in str(e):
                    logging.info("warehouse_products.unit allaqachon mavjud")
                else:
                    logging.error(f"warehouse_products.unit qo'shishda xatolik: {e}")
            
            # Warehouse_movements ga reason ustunini qo'shish
            try:
                await self.execute_query("ALTER TABLE warehouse_movements ADD COLUMN reason VARCHAR(100) DEFAULT 'other'")
                logging.info("warehouse_movements.reason qo'shildi")
            except Exception as e:
                if "Duplicate column name" in str(e):
                    logging.info("warehouse_movements.reason allaqachon mavjud")
                else:
                    logging.error(f"warehouse_movements.reason qo'shishda xatolik: {e}")
            
            # Debts jadvaliga paid_amount ustunini qo'shish
            try:
                await self.execute_query("ALTER TABLE debts ADD COLUMN paid_amount DECIMAL(15,2) DEFAULT 0")
                logging.info("debts.paid_amount qo'shildi")
            except Exception as e:
                if "Duplicate column name" in str(e):
                    logging.info("debts.paid_amount allaqachon mavjud")
                else:
                    logging.error(f"debts.paid_amount qo'shishda xatolik: {e}")

            # Transactions jadvaliga currency ustunini qo'shish
            try:
                await self.execute_query("ALTER TABLE transactions ADD COLUMN currency VARCHAR(10) DEFAULT 'UZS'")
                logging.info("transactions.currency qo'shildi")
            except Exception as e:
                if "Duplicate column name" in str(e):
                    logging.info("transactions.currency allaqachon mavjud")
                else:
                    logging.error(f"transactions.currency qo'shishda xatolik: {e}")

            # Valyuta kurslari jadvali
            try:
                await self.execute_query("""
                    CREATE TABLE IF NOT EXISTS currency_rates (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        currency_code VARCHAR(10) NOT NULL,
                        rate_to_uzs DECIMAL(20,6) NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        UNIQUE KEY unique_currency (currency_code)
                    )
                """)
                
                # Default kurslarni qo'shish
                default_rates = [
                    ('UZS', 1.0),
                    ('USD', 12750.0),
                    ('EUR', 13800.0),
                    ('RUB', 135.0),
                    ('TRY', 370.0)
                ]
                for code, rate in default_rates:
                    await self.execute_query("""
                        INSERT INTO currency_rates (currency_code, rate_to_uzs) 
                        VALUES (%s, %s)
                        ON DUPLICATE KEY UPDATE rate_to_uzs = VALUES(rate_to_uzs)
                    """, (code, rate))
                logging.info("currency_rates jadvali yaratildi va default kurslar qo'shildi")
            except Exception as e:
                logging.error(f"currency_rates jadvalini yaratishda xatolik: {e}")

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
            
            # Plus package purchases jadvalidagi noto'g'ri status qiymatlarini tozalash
            try:
                # Noto'g'ri status qiymatlarini tozalash
                await self.execute_query("""
                    UPDATE plus_package_purchases 
                    SET status = 'active' 
                    WHERE status NOT IN ('active', 'completed') 
                    OR status IS NULL
                """)
                logging.info("Plus package purchases status qiymatlari tozalandi")
            except Exception as e:
                logging.error(f"Plus package purchases status tozalashda xatolik: {e}")
                
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
            tariff = result.get('tariff')
            if tariff in (None, 'FREE'):
                tariff = 'NONE'
            return {
                'user_id': result.get('user_id'),
                'username': result.get('username'),
                'first_name': result.get('first_name'),
                'last_name': result.get('last_name'),
                'phone': result.get('phone'),
                'name': result.get('name'),
                'source': result.get('source'),
                'tariff': tariff,
                'created_at': result.get('created_at'),
                'tariff_expires_at': result.get('tariff_expires_at'),
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
                'id': result.get('id'),
                'type': result.get('transaction_type'),
                'amount': float(result.get('amount', 0)),
                'category': result.get('category'),
                'description': result.get('description'),
                'created_at': result.get('created_at')
            })
        return transactions

    async def add_transaction(self, user_id, transaction_type, amount, category, description=None, currency='UZS'):
        """Yangi tranzaksiya qo'shish (valyuta bilan)"""
        # Valyutani to'g'ri formatda saqlash
        currency = currency.upper() if currency else 'UZS'
        if currency not in ['UZS', 'USD', 'EUR', 'RUB', 'TRY']:
            currency = 'UZS'
        query = """
        INSERT INTO transactions (user_id, transaction_type, amount, category, currency, description)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        return await self.execute_insert(query, (user_id, transaction_type, amount, category, currency, description))

    async def get_balance(self, user_id):
        """Foydalanuvchi balansini olish"""
        # Kirimlar
        income_query = "SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE user_id = %s AND transaction_type = 'income'"
        income_result = await self.execute_one(income_query, (user_id,))
        income = float(income_result.get('total', 0)) if income_result else 0.0
        
        # Chiqimlar
        expense_query = "SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE user_id = %s AND transaction_type = 'expense'"
        expense_result = await self.execute_one(expense_query, (user_id,))
        expense = float(expense_result.get('total', 0)) if expense_result else 0.0
        
        # Qarzlar (yo'nalma bo'yicha)
        borrowed_query = "SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE user_id = %s AND transaction_type = 'debt' AND debt_direction = 'borrowed'"
        borrowed_result = await self.execute_one(borrowed_query, (user_id,))
        borrowed = float(borrowed_result.get('total', 0)) if borrowed_result else 0.0

        lent_query = "SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE user_id = %s AND transaction_type = 'debt' AND debt_direction = 'lent'"
        lent_result = await self.execute_one(lent_query, (user_id,))
        lent = float(lent_result.get('total', 0)) if lent_result else 0.0

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
            category = result.get('category')
            trans_type = result.get('transaction_type')
            total = float(result.get('total', 0))
            count = result.get('count', 0)
            
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
            month = result.get('month')
            trans_type = result.get('transaction_type')
            total = result.get('total', 0)
            if month not in monthly_data:
                monthly_data[month] = {'income': 0, 'expense': 0, 'debt': 0}
            if trans_type:
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
    
    async def set_active_tariff(self, user_id, tariff, expires_at=None):
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
        # Agar expires_at berilmagan bo'lsa va paket emas bo'lsa, subscription jadvalidan olamiz
        if expires_at is None and tariff not in ('PLUS', 'NONE'):
            sub = await self.execute_one(
                "SELECT expires_at FROM user_subscriptions WHERE user_id = %s AND tariff = %s LIMIT 1",
                (user_id, tariff)
            )
            expires_at = sub.get('expires_at') if sub else None
        # Users jadvalidagi tariff ustunini ham yangilaymiz
        await self.execute_query(
            "UPDATE users SET tariff = %s, tariff_expires_at = %s WHERE user_id = %s",
            (tariff, expires_at, user_id)
        )
    
    # Plus paketlari funksiyalari
    async def create_plus_package_purchase(self, user_id, package_code, text_limit, voice_limit):
        """Foydalanuvchi uchun yangi Plus paket xaridini yaratish"""
        # Avvalgi aktiv paketlarni yopamiz
        await self.execute_query(
            """
            UPDATE plus_package_purchases
            SET status = 'completed', updated_at = NOW()
            WHERE user_id = %s AND LOWER(status) = 'active'
            """,
            (user_id,)
        )
        
        # Yangi paketni yaratamiz
        query = """
        INSERT INTO plus_package_purchases (user_id, package_code, text_limit, voice_limit, text_used, voice_used, status)
        VALUES (%s, %s, %s, %s, 0, 0, 'active')
        """
        return await self.execute_insert(query, (user_id, package_code, text_limit, voice_limit))
    
    async def get_active_plus_package(self, user_id):
        """Foydalanuvchining hozirgi aktiv Plus paketini olish"""
        query = """
        SELECT id, package_code, text_limit, text_used, voice_limit, voice_used, status, purchased_at
        FROM plus_package_purchases
        WHERE user_id = %s
        ORDER BY purchased_at DESC
        LIMIT 1
        """
        result = await self.execute_one(query, (user_id,))
        if not result:
            return None
        package = {
            'id': result.get('id'),
            'package_code': result.get('package_code'),
            'text_limit': result.get('text_limit', 0),
            'text_used': int(result.get('text_used', 0)) if result.get('text_used') is not None else 0,
            'voice_limit': result.get('voice_limit', 0),
            'voice_used': int(result.get('voice_used', 0)) if result.get('voice_used') is not None else 0,
            'status': result.get('status'),
            'purchased_at': result.get('purchased_at'),
        }
        # Status ni to'g'ri formatlash - faqat 'active' yoki 'completed'
        status_value = package.get('status')
        if status_value:
            status_lower = str(status_value).lower()
            if status_lower not in ('active', 'completed'):
                # Agar noto'g'ri qiymat bo'lsa, qoldiqlarga qarab aniqlaymiz
                remaining_text = package['text_limit'] - package['text_used']
                remaining_voice = package['voice_limit'] - package['voice_used']
                package['status'] = 'active' if (remaining_text > 0 or remaining_voice > 0) else 'completed'
            else:
                # To'g'ri qiymat bo'lsa, kichik harfga o'tkazamiz
                package['status'] = status_lower
        else:
            # Status None bo'lsa, qoldiqlarga qarab aniqlaymiz
            remaining_text = package['text_limit'] - package['text_used']
            remaining_voice = package['voice_limit'] - package['voice_used']
            package['status'] = 'active' if (remaining_text > 0 or remaining_voice > 0) else 'completed'
        return package
    
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
            # Status ni to'g'ri formatlash - faqat 'active' yoki 'completed'
            if new_used >= package['text_limit'] and package['voice_used'] >= package['voice_limit']:
                new_status = 'completed'
            else:
                new_status = 'active'
            
            # Xavfsizlik uchun status ni tekshirish
            if new_status not in ('active', 'completed'):
                new_status = 'active'
            
            try:
                # Avval bazadagi status ni to'g'ri formatlash - faqat text_used ni yangilash
                # Status ni keyinroq alohida yangilaymiz
                await self.execute_query(
                    """
                    UPDATE plus_package_purchases
                    SET text_used = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (new_used, package['id'])
                )
                
                # Status ni alohida yangilash - faqat to'g'ri qiymat bilan
                try:
                    await self.execute_query(
                        """
                        UPDATE plus_package_purchases
                        SET status = %s
                        WHERE id = %s
                        """,
                        (new_status, package['id'])
                    )
                except Exception as status_error:
                    # Agar status yangilashda xatolik bo'lsa, bazadagi status ni to'g'ri formatlash
                    logging.warning(f"Status yangilashda xatolik, bazadagi status ni to'g'rilaymiz: {status_error}")
                    try:
                        await self.execute_query(
                            """
                            UPDATE plus_package_purchases
                            SET status = CASE 
                                WHEN text_used >= text_limit AND voice_used >= voice_limit THEN 'completed'
                                ELSE 'active'
                            END
                            WHERE id = %s
                            """,
                            (package['id'],)
                        )
                    except Exception as e3:
                        logging.error(f"Status to'g'rilashda xatolik: {e3}")
                
                package['text_used'] = new_used
                package['status'] = new_status
            except Exception as e:
                logging.error(f"Error updating plus usage (text): {e}")
                return False, package
        else:
            if package['voice_used'] >= package['voice_limit']:
                return False, package
            new_used = package['voice_used'] + 1
            # Status ni to'g'ri formatlash - faqat 'active' yoki 'completed'
            if new_used >= package['voice_limit'] and package['text_used'] >= package['text_limit']:
                new_status = 'completed'
            else:
                new_status = 'active'
            
            # Xavfsizlik uchun status ni tekshirish
            if new_status not in ('active', 'completed'):
                new_status = 'active'
            
            try:
                # Avval voice_used ni yangilash
                await self.execute_query(
                    """
                    UPDATE plus_package_purchases
                    SET voice_used = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (new_used, package['id'])
                )
                
                # Status ni alohida yangilash - faqat to'g'ri qiymat bilan
                try:
                    await self.execute_query(
                        """
                        UPDATE plus_package_purchases
                        SET status = %s
                        WHERE id = %s
                        """,
                        (new_status, package['id'])
                    )
                except Exception as status_error:
                    # Agar status yangilashda xatolik bo'lsa, bazadagi status ni to'g'ri formatlash
                    logging.warning(f"Status yangilashda xatolik, bazadagi status ni to'g'rilaymiz: {status_error}")
                    try:
                        await self.execute_query(
                            """
                            UPDATE plus_package_purchases
                            SET status = CASE 
                                WHEN text_used >= text_limit AND voice_used >= voice_limit THEN 'completed'
                                ELSE 'active'
                            END
                            WHERE id = %s
                            """,
                            (package['id'],)
                        )
                    except Exception as e3:
                        logging.error(f"Status to'g'rilashda xatolik: {e3}")
                
                package['voice_used'] = new_used
                package['status'] = new_status
            except Exception as e:
                logging.error(f"Error updating plus usage (voice): {e}")
                return False, package
        
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
        return result.get('tariff') if result else "NONE"
    
    # Reminders funksiyalari
    async def create_reminder(self, user_id: int, reminder_type: str, title: str, 
                             reminder_date, description: str = None, amount: float = None,
                             currency: str = 'UZS', person_name: str = None, reminder_time: str = '09:00:00',
                             location: str = None, is_recurring: bool = False, 
                             recurrence_pattern: str = None, recurrence_day: int = None):
        """Yangi eslatma yaratish"""
        query = """
        INSERT INTO reminders (user_id, reminder_type, title, description, reminder_date, 
                              reminder_time, amount, currency, person_name, location,
                              is_recurring, recurrence_pattern, recurrence_day)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (user_id, reminder_type, title, description, reminder_date, 
                 reminder_time, amount, currency, person_name, location,
                 is_recurring, recurrence_pattern, recurrence_day)
        return await self.execute_insert(query, params)
    
    async def get_today_reminders(self, user_id: int = None):
        """Bugungi eslatmalarni olish"""
        if user_id:
            query = """
            SELECT * FROM reminders 
            WHERE reminder_date = CURDATE() AND is_completed = FALSE
            AND user_id = %s
            ORDER BY reminder_time
            """
            return await self.execute_query(query, (user_id,))
        else:
            query = """
            SELECT * FROM reminders 
            WHERE reminder_date = CURDATE() AND is_completed = FALSE
            ORDER BY reminder_time
            """
            return await self.execute_query(query)
    
    async def get_upcoming_reminders(self, user_id: int, days: int = 7):
        """Keyingi N kundagi eslatmalarni olish"""
        query = """
        SELECT * FROM reminders 
        WHERE user_id = %s 
        AND reminder_date >= CURDATE() 
        AND reminder_date <= DATE_ADD(CURDATE(), INTERVAL %s DAY)
        AND is_completed = FALSE
        ORDER BY reminder_date, reminder_time
        """
        return await self.execute_query(query, (user_id, days))
    
    async def mark_reminder_completed(self, reminder_id: int):
        """Eslatmani bajarilgan deb belgilash"""
        query = """
        UPDATE reminders SET is_completed = TRUE 
        WHERE id = %s
        """
        await self.execute_query(query, (reminder_id,))
    
    async def get_user_reminders(self, user_id: int, include_completed: bool = False):
        """Foydalanuvchining barcha eslatmalarini olish"""
        if include_completed:
            query = """
            SELECT * FROM reminders 
            WHERE user_id = %s
            ORDER BY reminder_date DESC, reminder_time DESC
            """
        else:
            query = """
            SELECT * FROM reminders 
            WHERE user_id = %s AND is_completed = FALSE
            ORDER BY reminder_date, reminder_time
            """
        return await self.execute_query(query, (user_id,))
    
    async def get_reminders_for_30min_notification(self):
        """30 minut ichida bo'ladigan eslatmalarni olish (bildirishnoma yuborilmagan)"""
        query = """
        SELECT r.*, u.first_name, u.name as user_name
        FROM reminders r
        JOIN users u ON r.user_id = u.user_id
        WHERE r.is_completed = FALSE 
        AND r.notification_30min_sent = FALSE
        AND r.reminder_date = CURDATE()
        AND TIMESTAMPDIFF(MINUTE, NOW(), CONCAT(r.reminder_date, ' ', r.reminder_time)) BETWEEN 0 AND 30
        ORDER BY r.reminder_time ASC
        """
        return await self.execute_query(query)
    
    async def get_reminders_for_exact_notification(self):
        """Aniq vaqtda bo'ladigan eslatmalarni olish (bildirishnoma yuborilmagan)"""
        query = """
        SELECT r.*, u.first_name, u.name as user_name
        FROM reminders r
        JOIN users u ON r.user_id = u.user_id
        WHERE r.is_completed = FALSE 
        AND r.notification_exact_sent = FALSE
        AND r.reminder_date = CURDATE()
        AND TIMESTAMPDIFF(MINUTE, NOW(), CONCAT(r.reminder_date, ' ', r.reminder_time)) BETWEEN -5 AND 5
        ORDER BY r.reminder_time ASC
        """
        return await self.execute_query(query)
    
    async def mark_notification_30min_sent(self, reminder_id: int):
        """30 minut oldin bildirishnoma yuborilganini belgilash"""
        query = """
        UPDATE reminders SET notification_30min_sent = TRUE 
        WHERE id = %s
        """
        await self.execute_query(query, (reminder_id,))
    
    async def mark_notification_exact_sent(self, reminder_id: int):
        """Aniq vaqtda bildirishnoma yuborilganini belgilash"""
        query = """
        UPDATE reminders SET notification_exact_sent = TRUE 
        WHERE id = %s
        """
        await self.execute_query(query, (reminder_id,))
    
    async def create_next_recurring_reminder(self, reminder_id: int):
        """Takrorlanadigan eslatma uchun keyingi eslatmani yaratish"""
        # Eslatmani olish
        reminder = await self.execute_one(
            "SELECT * FROM reminders WHERE id = %s", (reminder_id,)
        )
        if not reminder or not reminder.get('is_recurring'):
            return None
        
        from datetime import timedelta
        current_date = reminder.get('reminder_date')
        pattern = reminder.get('recurrence_pattern')
        recurrence_day = reminder.get('recurrence_day')
        
        if pattern == 'daily':
            next_date = current_date + timedelta(days=1)
        elif pattern == 'weekly':
            next_date = current_date + timedelta(weeks=1)
        elif pattern == 'monthly':
            # Keyingi oyning shu kuniga
            month = current_date.month + 1
            year = current_date.year
            if month > 12:
                month = 1
                year += 1
            day = min(current_date.day, 28)  # Fevral uchun
            next_date = current_date.replace(year=year, month=month, day=day)
        elif pattern == 'yearly':
            next_date = current_date.replace(year=current_date.year + 1)
        else:
            return None
        
        # Yangi eslatma yaratish
        query = """
        INSERT INTO reminders (user_id, reminder_type, title, description, reminder_date, 
                              reminder_time, amount, currency, person_name, location,
                              is_recurring, recurrence_pattern, recurrence_day)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        return await self.execute_insert(query, (
            reminder.get('user_id'),
            reminder.get('reminder_type'),
            reminder.get('title'),
            reminder.get('description'),
            next_date,
            reminder.get('reminder_time'),
            reminder.get('amount'),
            reminder.get('currency'),
            reminder.get('person_name'),
            reminder.get('location'),
            True,
            pattern,
            recurrence_day
        ))
    
    # Pro tarifi xarajatlari funksiyalari
    async def get_or_create_pro_usage(self, user_id: int, month_year: str = None):
        """Pro tarifida foydalanuvchining joriy oydagi xarajatlarini olish yoki yaratish"""
        if not month_year:
            from datetime import datetime
            month_year = datetime.now().strftime('%Y-%m')
        
        result = await self.execute_one(
            """
            SELECT id, text_cost, voice_cost, total_cost, text_count, voice_count
            FROM pro_usage_tracking
            WHERE user_id = %s AND month_year = %s
            """,
            (user_id, month_year)
        )
        
        if result:
            return {
                'id': result.get('id'),
                'text_cost': float(result.get('text_cost', 0)) if result.get('text_cost') else 0,
                'voice_cost': float(result.get('voice_cost', 0)) if result.get('voice_cost') else 0,
                'total_cost': float(result.get('total_cost', 0)) if result.get('total_cost') else 0,
                'text_count': result.get('text_count', 0) if result.get('text_count') else 0,
                'voice_count': result.get('voice_count', 0) if result.get('voice_count') else 0,
            }
        
        # Yangi yozuv yaratish
        insert_id = await self.execute_insert(
            """
            INSERT INTO pro_usage_tracking (user_id, month_year, text_cost, voice_cost, total_cost, text_count, voice_count)
            VALUES (%s, %s, 0, 0, 0, 0, 0)
            """,
            (user_id, month_year)
        )
        
        return {
            'id': insert_id,
            'text_cost': 0,
            'voice_cost': 0,
            'total_cost': 0,
            'text_count': 0,
            'voice_count': 0,
        }
    
    async def increment_pro_usage(self, user_id: int, usage_type: str, cost: float, month_year: str = None):
        """Pro tarifida xarajatlarni oshirish"""
        if not month_year:
            from datetime import datetime
            month_year = datetime.now().strftime('%Y-%m')
        
        usage = await self.get_or_create_pro_usage(user_id, month_year)
        
        if usage_type == 'text':
            new_text_cost = usage['text_cost'] + cost
            new_text_count = usage['text_count'] + 1
            new_total = new_text_cost + usage['voice_cost']
            
            await self.execute_query(
                """
                UPDATE pro_usage_tracking
                SET text_cost = %s, text_count = %s, total_cost = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (new_text_cost, new_text_count, new_total, usage['id'])
            )
        elif usage_type == 'voice':
            new_voice_cost = usage['voice_cost'] + cost
            new_voice_count = usage['voice_count'] + 1
            new_total = usage['text_cost'] + new_voice_cost
            
            await self.execute_query(
                """
                UPDATE pro_usage_tracking
                SET voice_cost = %s, voice_count = %s, total_cost = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (new_voice_cost, new_voice_count, new_total, usage['id'])
            )
        
        # Yangilangan xarajatlarni qaytarish
        return await self.get_or_create_pro_usage(user_id, month_year)
    
    # Warehouse (Ombor) funksiyalari - Biznes tarif uchun
    async def add_warehouse_product(self, user_id: int, name: str, category: str = None, 
                                     barcode: str = None, price: float = 0, 
                                     quantity: int = 0, min_quantity: int = 0, 
                                     image_url: str = None) -> int:
        """Omborga yangi tovar qo'shish"""
        query = """
        INSERT INTO warehouse_products (user_id, name, category, barcode, price, quantity, min_quantity, image_url)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        return await self.execute_insert(query, (user_id, name, category, barcode, price, quantity, min_quantity, image_url))
    
    async def get_warehouse_products(self, user_id: int, category: str = None) -> list:
        """Foydalanuvchining barcha tovarlarini olish"""
        if category:
            query = """
            SELECT id, name, category, barcode, price, quantity, min_quantity, image_url, created_at
            FROM warehouse_products
            WHERE user_id = %s AND category = %s
            ORDER BY name
            """
            results = await self.execute_query(query, (user_id, category))
        else:
            query = """
            SELECT id, name, category, barcode, price, quantity, min_quantity, image_url, created_at
            FROM warehouse_products
            WHERE user_id = %s
            ORDER BY name
            """
            results = await self.execute_query(query, (user_id,))
        
        products = []
        for result in results:
            products.append({
                'id': result.get('id'),
                'name': result.get('name'),
                'category': result.get('category'),
                'barcode': result.get('barcode'),
                'price': float(result.get('price', 0)) if result.get('price') else 0,
                'quantity': result.get('quantity', 0) or 0,
                'min_quantity': result.get('min_quantity', 0) or 0,
                'image_url': result.get('image_url'),
                'created_at': result.get('created_at')
            })
        return products
    
    async def get_warehouse_product(self, product_id: int, user_id: int = None) -> dict:
        """Bitta tovarni olish"""
        if user_id:
            query = """
            SELECT id, user_id, name, category, barcode, price, quantity, min_quantity, image_url, created_at
            FROM warehouse_products
            WHERE id = %s AND user_id = %s
            """
            result = await self.execute_one(query, (product_id, user_id))
        else:
            query = """
            SELECT id, user_id, name, category, barcode, price, quantity, min_quantity, image_url, created_at
            FROM warehouse_products
            WHERE id = %s
            """
            result = await self.execute_one(query, (product_id,))
        
        if not result:
            return None
        
        return {
            'id': result.get('id'),
            'user_id': result.get('user_id'),
            'name': result.get('name'),
            'category': result.get('category'),
            'barcode': result.get('barcode'),
            'price': float(result.get('price', 0)) if result.get('price') else 0,
            'quantity': result.get('quantity', 0) or 0,
            'min_quantity': result.get('min_quantity', 0) or 0,
            'image_url': result.get('image_url'),
            'created_at': result.get('created_at')
        }
    
    async def update_warehouse_product(self, product_id: int, user_id: int, **kwargs) -> bool:
        """Tovarni yangilash"""
        allowed_fields = ['name', 'category', 'barcode', 'price', 'quantity', 'min_quantity', 'image_url']
        updates = []
        values = []
        
        for field, value in kwargs.items():
            if field in allowed_fields:
                updates.append(f"{field} = %s")
                values.append(value)
        
        if not updates:
            return False
        
        values.append(product_id)
        values.append(user_id)
        
        query = f"""
        UPDATE warehouse_products
        SET {', '.join(updates)}, updated_at = NOW()
        WHERE id = %s AND user_id = %s
        """
        await self.execute_query(query, tuple(values))
        return True
    
    async def add_warehouse_movement(self, user_id: int, product_id: int, movement_type: str,
                                     quantity: int, unit_price: float = None, 
                                     total_cost: float = None, description: str = None) -> int:
        """Ombor harakatini qo'shish (kirim/chiqim)"""
        query = """
        INSERT INTO warehouse_movements (user_id, product_id, movement_type, quantity, unit_price, total_cost, description)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        movement_id = await self.execute_insert(query, (user_id, product_id, movement_type, quantity, unit_price, total_cost, description))
        
        # Tovarning sonini yangilash
        if movement_type == 'in':
            await self.execute_query(
                "UPDATE warehouse_products SET quantity = quantity + %s WHERE id = %s",
                (quantity, product_id)
            )
        elif movement_type == 'out':
            await self.execute_query(
                "UPDATE warehouse_products SET quantity = GREATEST(0, quantity - %s) WHERE id = %s",
                (quantity, product_id)
            )
        
        return movement_id
    
    async def get_warehouse_movements(self, user_id: int, product_id: int = None, 
                                      movement_type: str = None, limit: int = 50) -> list:
        """Ombor harakatlarini olish"""
        conditions = ["user_id = %s"]
        params = [user_id]
        
        if product_id:
            conditions.append("product_id = %s")
            params.append(product_id)
        
        if movement_type:
            conditions.append("movement_type = %s")
            params.append(movement_type)
        
        query = f"""
        SELECT id, product_id, movement_type, quantity, unit_price, total_cost, description, created_at
        FROM warehouse_movements
        WHERE {' AND '.join(conditions)}
        ORDER BY created_at DESC
        LIMIT %s
        """
        params.append(limit)
        
        results = await self.execute_query(query, tuple(params))
        movements = []
        for result in results:
            movements.append({
                'id': result.get('id'),
                'product_id': result.get('product_id'),
                'movement_type': result.get('movement_type'),
                'quantity': result.get('quantity', 0),
                'unit_price': float(result.get('unit_price', 0)) if result.get('unit_price') else 0,
                'total_cost': float(result.get('total_cost', 0)) if result.get('total_cost') else 0,
                'description': result.get('description'),
                'created_at': result.get('created_at')
            })
        return movements
    
    async def add_warehouse_expense(self, user_id: int, expense_type: str, amount: float,
                                    product_id: int = None, movement_id: int = None,
                                    description: str = None) -> int:
        """Ombor xarajatini qo'shish"""
        query = """
        INSERT INTO warehouse_expenses (user_id, product_id, movement_id, expense_type, amount, description)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        return await self.execute_insert(query, (user_id, product_id, movement_id, expense_type, amount, description))
    
    async def get_warehouse_expenses(self, user_id: int, product_id: int = None, 
                                     expense_type: str = None, limit: int = 50) -> list:
        """Ombor xarajatlarini olish"""
        conditions = ["user_id = %s"]
        params = [user_id]
        
        if product_id:
            conditions.append("product_id = %s")
            params.append(product_id)
        
        if expense_type:
            conditions.append("expense_type = %s")
            params.append(expense_type)
        
        query = f"""
        SELECT id, product_id, movement_id, expense_type, amount, description, created_at
        FROM warehouse_expenses
        WHERE {' AND '.join(conditions)}
        ORDER BY created_at DESC
        LIMIT %s
        """
        params.append(limit)
        
        results = await self.execute_query(query, tuple(params))
        expenses = []
        for result in results:
            expenses.append({
                'id': result.get('id'),
                'product_id': result.get('product_id'),
                'movement_id': result.get('movement_id'),
                'expense_type': result.get('expense_type'),
                'amount': float(result.get('amount', 0)) if result.get('amount') else 0,
                'description': result.get('description'),
                'created_at': result.get('created_at')
            })
        return expenses
    
    async def get_low_stock_products(self, user_id: int) -> list:
        """Kam qolgan tovarlarni olish (quantity <= min_quantity)"""
        query = """
        SELECT id, name, category, quantity, min_quantity
        FROM warehouse_products
        WHERE user_id = %s AND quantity <= min_quantity AND min_quantity > 0
        ORDER BY (quantity - min_quantity) ASC
        """
        results = await self.execute_query(query, (user_id,))
        products = []
        for result in results:
            products.append({
                'id': result.get('id'),
                'name': result.get('name'),
                'category': result.get('category'),
                'quantity': result.get('quantity', 0),
                'min_quantity': result.get('min_quantity', 0)
            })
        return products
    
    async def get_warehouse_statistics(self, user_id: int) -> dict:
        """Ombor statistikalarini olish"""
        # Jami tovarlar soni
        total_products = await self.execute_one(
            "SELECT COUNT(*) as count FROM warehouse_products WHERE user_id = %s",
            (user_id,)
        )
        
        # Jami qoldiq qiymati
        total_value = await self.execute_one(
            "SELECT SUM(price * quantity) as total FROM warehouse_products WHERE user_id = %s",
            (user_id,)
        )
        
        # Kam qolgan tovarlar soni
        low_stock_count = await self.execute_one(
            "SELECT COUNT(*) as count FROM warehouse_products WHERE user_id = %s AND quantity <= min_quantity AND min_quantity > 0",
            (user_id,)
        )
        
        # Oylik kirim/chiqim
        monthly_movements = await self.execute_query("""
            SELECT movement_type, SUM(quantity) as total
            FROM warehouse_movements
            WHERE user_id = %s AND created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            GROUP BY movement_type
        """, (user_id,))
        
        monthly_in = 0
        monthly_out = 0
        for movement in monthly_movements:
            if movement.get('movement_type') == 'in':
                monthly_in = movement.get('total', 0) or 0
            elif movement.get('movement_type') == 'out':
                monthly_out = movement.get('total', 0) or 0
        
        # Oylik xarajatlar
        monthly_expenses = await self.execute_one("""
            SELECT SUM(amount) as total FROM warehouse_expenses
            WHERE user_id = %s AND created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        """, (user_id,))
        
        return {
            'total_products': total_products.get('count', 0) if total_products else 0,
            'total_value': float(total_value.get('total', 0)) if total_value and total_value.get('total') else 0,
            'low_stock_count': low_stock_count.get('count', 0) if low_stock_count else 0,
            'monthly_in': monthly_in,
            'monthly_out': monthly_out,
            'monthly_expenses': float(monthly_expenses.get('total', 0)) if monthly_expenses and monthly_expenses.get('total') else 0
        }

    # ============ VALYUTA FUNKSIYALARI ============
    
    async def get_currency_rates(self) -> dict:
        """Barcha valyuta kurslarini olish"""
        try:
            results = await self.execute_query("SELECT currency_code, rate_to_uzs FROM currency_rates")
            rates = {}
            for row in results:
                rates[row.get('currency_code')] = float(row.get('rate_to_uzs', 1))
            # Default qiymatlar agar topilmasa
            if 'UZS' not in rates:
                rates['UZS'] = 1.0
            if 'USD' not in rates:
                rates['USD'] = 12750.0
            if 'EUR' not in rates:
                rates['EUR'] = 13800.0
            if 'RUB' not in rates:
                rates['RUB'] = 135.0
            if 'TRY' not in rates:
                rates['TRY'] = 370.0
            return rates
        except Exception as e:
            logging.error(f"Valyuta kurslarini olishda xatolik: {e}")
            return {'UZS': 1.0, 'USD': 12750.0, 'EUR': 13800.0, 'RUB': 135.0, 'TRY': 370.0}
    
    async def update_currency_rate(self, currency_code: str, rate_to_uzs: float) -> bool:
        """Valyuta kursini yangilash"""
        try:
            await self.execute_query("""
                INSERT INTO currency_rates (currency_code, rate_to_uzs) 
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE rate_to_uzs = VALUES(rate_to_uzs)
            """, (currency_code, rate_to_uzs))
            return True
        except Exception as e:
            logging.error(f"Valyuta kursini yangilashda xatolik: {e}")
            return False
    
    async def convert_to_uzs(self, amount: float, currency: str) -> float:
        """Istalgan valyutani UZS ga o'girish"""
        if currency == 'UZS':
            return amount
        rates = await self.get_currency_rates()
        rate = rates.get(currency, 1.0)
        return amount * rate
    
    async def get_balance_multi_currency(self, user_id: int) -> dict:
        """Foydalanuvchi balansini har bir valyutada va umumiy so'mda olish"""
        rates = await self.get_currency_rates()
        
        # Har bir valyuta uchun balanslarni olish
        currencies = ['UZS', 'USD', 'EUR', 'RUB', 'TRY']
        result = {
            'by_currency': {},
            'total_uzs': {'income': 0.0, 'expense': 0.0, 'borrowed': 0.0, 'lent': 0.0}
        }
        
        for currency in currencies:
            # COALESCE yordamida NULL valyutalarni UZS deb qabul qilish
            # Kirimlar
            income_query = """
                SELECT COALESCE(SUM(amount), 0) as total 
                FROM transactions 
                WHERE user_id = %s AND transaction_type = 'income' AND COALESCE(currency, 'UZS') = %s
            """
            income_result = await self.execute_one(income_query, (user_id, currency))
            income = float(income_result.get('total', 0)) if income_result else 0.0
            
            # Chiqimlar
            expense_query = """
                SELECT COALESCE(SUM(amount), 0) as total 
                FROM transactions 
                WHERE user_id = %s AND transaction_type = 'expense' AND COALESCE(currency, 'UZS') = %s
            """
            expense_result = await self.execute_one(expense_query, (user_id, currency))
            expense = float(expense_result.get('total', 0)) if expense_result else 0.0
            
            # Qarzlar
            borrowed_query = """
                SELECT COALESCE(SUM(amount), 0) as total 
                FROM transactions 
                WHERE user_id = %s AND transaction_type = 'debt' AND debt_direction = 'borrowed' AND COALESCE(currency, 'UZS') = %s
            """
            borrowed_result = await self.execute_one(borrowed_query, (user_id, currency))
            borrowed = float(borrowed_result.get('total', 0)) if borrowed_result else 0.0
            
            lent_query = """
                SELECT COALESCE(SUM(amount), 0) as total 
                FROM transactions 
                WHERE user_id = %s AND transaction_type = 'debt' AND debt_direction = 'lent' AND COALESCE(currency, 'UZS') = %s
            """
            lent_result = await self.execute_one(lent_query, (user_id, currency))
            lent = float(lent_result.get('total', 0)) if lent_result else 0.0
            
            # Agar bu valyutada hech narsa yo'q bo'lsa, qo'shmaslik
            if income > 0 or expense > 0 or borrowed > 0 or lent > 0:
                balance = income + borrowed - expense - lent
                result['by_currency'][currency] = {
                    'income': income,
                    'expense': expense,
                    'borrowed': borrowed,
                    'lent': lent,
                    'balance': balance
                }
                
                # UZS ga o'girish
                rate = rates.get(currency, 1.0)
                result['total_uzs']['income'] += income * rate
                result['total_uzs']['expense'] += expense * rate
                result['total_uzs']['borrowed'] += borrowed * rate
                result['total_uzs']['lent'] += lent * rate
        
        # Umumiy balans
        result['total_uzs']['balance'] = (
            result['total_uzs']['income'] + 
            result['total_uzs']['borrowed'] - 
            result['total_uzs']['expense'] - 
            result['total_uzs']['lent']
        )
        result['total_uzs']['net_balance'] = result['total_uzs']['income'] - result['total_uzs']['expense']
        
        return result

    async def add_transaction_with_currency(self, user_id, transaction_type, amount, category, 
                                            currency='UZS', description=None):
        """Yangi tranzaksiya qo'shish (valyuta bilan)"""
        query = """
        INSERT INTO transactions (user_id, transaction_type, amount, category, currency, description)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        return await self.execute_insert(query, (user_id, transaction_type, amount, category, currency, description))

# Global database instance
db = Database()