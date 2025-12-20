# BALANS AI — MINI ILOVA TEXNIK TOPSHIRIQ (TZ)

## 1. UMUMIY MA'LUMOT

### 1.1. Maqsad
Telegram Mini App orqali foydalanuvchilarga moliyaviy hisobotlar va tranzaksiyalarni ko'rish, qo'shish va boshqarish imkoniyatini berish.

### 1.2. Texnologiyalar
- **Backend**: Python Flask (to'g'ridan-to'g'ri MySQL bilan ishlaydi)
- **Frontend**: HTML + Tailwind CSS + JavaScript
- **Ma'lumotlar bazasi**: MySQL (mavjud - bot bilan bir xil database)
- **Integratsiya**: Telegram Mini App API

**MUHIM**: Flask server to'g'ridan-to'g'ri MySQL ga ulanadi. API layer yo'q. Flask route'lar to'g'ridan-to'g'ri database bilan ishlaydi.

---

## 2. DATABASE STRUKTURA

### 2.1. Users jadvali
```sql
users (
    user_id BIGINT PRIMARY KEY,
    username VARCHAR(255),
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    phone VARCHAR(20),
    name VARCHAR(255) DEFAULT 'Xojayin',
    source VARCHAR(50),
    tariff ENUM('NONE', 'FREE', 'PLUS', 'PRO', 'FAMILY', 'FAMILY_PLUS', 'FAMILY_PRO', 'BUSINESS', 'BUSINESS_PLUS', 'BUSINESS_PRO', 'EMPLOYEE'),
    tariff_expires_at DATETIME NULL,
    manager_id BIGINT NULL,
    account_type VARCHAR(20) DEFAULT 'SHI',
    created_at TIMESTAMP,
    updated_at TIMESTAMP
)
```

### 2.2. Transactions jadvali (MUHIM - VALYUTA QO'SHILGAN)
```sql
transactions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT,
    transaction_type ENUM('income', 'expense', 'debt') NOT NULL,
    amount DECIMAL(15,2) NOT NULL,
    currency VARCHAR(10) DEFAULT 'UZS',  -- UZS, USD, EUR, RUB, TRY
    category VARCHAR(100),
    description TEXT,
    due_date DATE NULL,
    debt_direction ENUM('lent','borrowed') NULL,
    created_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
)
```

### 2.3. Currency_rates jadvali
```sql
currency_rates (
    id INT PRIMARY KEY AUTO_INCREMENT,
    currency_code VARCHAR(10) UNIQUE,  -- UZS, USD, EUR, RUB, TRY
    rate_to_uzs DECIMAL(20,6) NOT NULL,  -- 1 valyuta = ? so'm
    updated_at TIMESTAMP
)
```

**Default kurslar:**
- UZS: 1.0
- USD: 12750.0
- EUR: 13800.0
- RUB: 135.0
- TRY: 370.0

### 2.4. Debts jadvali
```sql
debts (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT,
    debt_type ENUM('lent', 'borrowed') NOT NULL,
    amount DECIMAL(15,2) NOT NULL,
    paid_amount DECIMAL(15,2) DEFAULT 0,  -- to'langan summa
    person_name VARCHAR(255),
    due_date DATE NULL,
    status ENUM('active', 'paid') DEFAULT 'active',
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
)
```

### 2.5. Reminders jadvali
```sql
reminders (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT,
    reminder_type ENUM('debt_give', 'debt_receive', 'payment', 'meeting', 'event', 'task', 'other'),
    title VARCHAR(255),
    description TEXT,
    reminder_date DATE,
    reminder_time TIME DEFAULT '09:00:00',
    amount DECIMAL(15,2) NULL,
    currency VARCHAR(10) DEFAULT 'UZS',
    person_name VARCHAR(255) NULL,
    location VARCHAR(255) NULL,
    is_recurring BOOLEAN DEFAULT FALSE,
    recurrence_pattern ENUM('daily', 'weekly', 'monthly', 'yearly') NULL,
    is_completed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
)
```
