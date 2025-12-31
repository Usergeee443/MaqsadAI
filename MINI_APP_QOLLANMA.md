# Mini App Dasturchisi uchun Qo'llanma

## Umumiy ma'lumot

Bu qo'llanma mini app dasturchisi uchun yozilgan. Mini app `https://balansai-app.onrender.com/register` URL da joylashgan va foydalanuvchilarning ro'yxatdan o'tish jarayonini boshqaradi.

## Bot bilan integratsiya

### 1. Foydalanuvchi ma'lumotlari

Bot foydalanuvchiga `/start` bosganda birinchi xabar va telefon raqam so'raydi. Telefon raqam yuborilgandan keyin, bot foydalanuvchini mini app ga yo'naltiradi.

### 2. Ma'lumotlar bazasi strukturası

#### `users` jadvali

Asosiy foydalanuvchi ma'lumotlari quyidagi jadvalda saqlanadi:

```sql
CREATE TABLE users (
    user_id BIGINT PRIMARY KEY,           -- Telegram user ID (asosiy kalit)
    username VARCHAR(255),               -- Telegram username
    first_name VARCHAR(255),             -- Telegram first_name
    last_name VARCHAR(255),              -- Telegram last_name
    phone VARCHAR(20),                   -- Telefon raqam (botda to'ldiriladi)
    name VARCHAR(255) DEFAULT 'Xojayin', -- Foydalanuvchi ismi (mini app da to'ldiriladi)
    source VARCHAR(50),                  -- Qayerdan eshitgan (mini app da to'ldiriladi)
    account_type VARCHAR(50),            -- Hisob turi: 'SHI' (Shaxsiy) yoki 'BIZNES' (Biznes) (mini app da to'ldiriladi)
    tariff ENUM('NONE', 'FREE', 'PLUS', 'PRO', 'FAMILY', 'FAMILY_PLUS', 'FAMILY_PRO', 'BUSINESS', 'BUSINESS_PLUS', 'BUSINESS_PRO', 'EMPLOYEE') DEFAULT 'NONE',
    tariff_expires_at DATETIME NULL,
    manager_id BIGINT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
)
```

#### `transactions` jadvali (Onboarding uchun)

Onboarding jarayonida boshlang'ich balans quyidagi kategoriyalar bilan saqlanadi:

- `boshlang_ich_balans` - Umumiy boshlang'ich balans
- `boshlang_ich_naqd` - Naqd pul
- `boshlang_ich_karta` - Karta balansi

```sql
CREATE TABLE transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT,
    transaction_type ENUM('income', 'expense', 'debt'),
    amount DECIMAL(15, 2),
    category VARCHAR(255),
    currency VARCHAR(10) DEFAULT 'UZS',
    description TEXT,
    due_date DATE NULL,
    debt_direction ENUM('lent', 'borrowed') NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
)
```

## Mini App da to'ldirilishi kerak bo'lgan ma'lumotlar

### 1. Ism (`name`)
- **Maydon:** `users.name`
- **Turi:** VARCHAR(255)
- **Majburiy:** Ha
- **Tavsif:** Foydalanuvchi ismi

### 2. Yosh (`age`)
- **Eslatma:** Hozircha bazada alohida maydon yo'q, lekin kelajakda qo'shilishi mumkin
- **Tavsif:** Foydalanuvchi yoshi

### 3. Manba (`source`)
- **Maydon:** `users.source`
- **Turi:** VARCHAR(50)
- **Majburiy:** Ha
- **Qiymatlar:** 
  - 'telegram' - Telegram orqali
  - 'instagram' - Instagram orqali
  - 'youtube' - YouTube orqali
  - 'tanish' - Tanish orqali
  - 'boshqa' - Boshqa
- **Tavsif:** Foydalanuvchi bizni qayerdan eshitgan

### 4. Hisob turi (`account_type`)
- **Maydon:** `users.account_type`
- **Turi:** VARCHAR(50)
- **Majburiy:** Ha
- **Qiymatlar:**
  - 'SHI' - Shaxsiy foydalanish uchun
  - 'BIZNES' - Biznes uchun
- **Tavsif:** Foydalanuvchi hisob turi

### 5. Onboarding ma'lumotlari

#### 5.1. Boshlang'ich balans
- **Jadval:** `transactions`
- **Kategoriyalar:**
  - `boshlang_ich_naqd` - Naqd pul miqdori
  - `boshlang_ich_karta` - Karta balansi
- **Format:**
```sql
INSERT INTO transactions (user_id, transaction_type, amount, category, currency, description) 
VALUES (user_id, 'income', amount, 'boshlang_ich_naqd', 'UZS', 'Boshlang''ich naqd pul');
```

#### 5.2. Qarzlar (ixtiyoriy)
- **Jadval:** `transactions`
- **Kategoriya:** Qarz kategoriyasi
- **Qo'shimcha maydonlar:**
  - `due_date` - Qaytarish sanasi
  - `debt_direction` - 'lent' (qarz bergan) yoki 'borrowed' (qarz olgan)
  - `description` - Qarz haqida ma'lumot

### 6. Tarif tanlash
- **Maydon:** `users.tariff`
- **Turi:** ENUM
- **Qiymatlar:**
  - 'NONE' - Tarif tanlanmagan
  - 'FREE' - Bepul
  - 'PLUS' - Plus tarif
  - 'PRO' - Pro tarif
  - 'BUSINESS' - Business tarif
  - va boshqalar...

## API Endpoint'lar

### 1. Foydalanuvchi ma'lumotlarini olish

```http
GET /api/user/{user_id}
```

**Javob:**
```json
{
  "user_id": 123456789,
  "username": "username",
  "first_name": "Ism",
  "last_name": "Familiya",
  "phone": "+998901234567",
  "name": "Foydalanuvchi ismi",
  "source": "telegram",
  "account_type": "SHI",
  "tariff": "NONE"
}
```

### 2. Foydalanuvchi ma'lumotlarini yangilash

```http
POST /api/user/{user_id}/update
Content-Type: application/json

{
  "name": "Yangi ism",
  "source": "telegram",
  "account_type": "SHI",
  "age": 25
}
```

### 3. Onboarding ma'lumotlarini saqlash

```http
POST /api/user/{user_id}/onboarding
Content-Type: application/json

{
  "cash_balance": 1000000,
  "card_balance": 500000,
  "debts": [
    {
      "person_name": "Ali",
      "amount": 50000,
      "direction": "lent",
      "due_date": "2025-01-15"
    }
  ]
}
```

### 4. Tarif tanlash

```http
POST /api/user/{user_id}/tariff
Content-Type: application/json

{
  "tariff": "PLUS"
}
```

## Ro'yxatdan o'tishni yakunlash

Barcha ma'lumotlar to'ldirilgandan keyin, bot foydalanuvchiga xabar yuboradi va botdan foydalanishga ruxsat beriladi.

### Tekshiruv mezonlari

Ro'yxatdan o'tish to'liq deb hisoblanadi, agar:
1. ✅ `phone` to'ldirilgan (botda)
2. ✅ `name` to'ldirilgan va 'Xojayin' emas
3. ✅ `source` to'ldirilgan
4. ✅ `account_type` to'ldirilgan
5. ✅ Onboarding yakunlangan (boshlang'ich balans saqlangan)

### Bot tekshiruvi

Bot har bir xabarni qayta ishlashdan oldin `check_registration_complete()` funksiyasini chaqiradi:

```python
async def check_registration_complete(user_id: int) -> bool:
    """Foydalanuvchi ro'yxatdan to'liq o'tganligini tekshirish"""
    user_data = await db.get_user_data(user_id)
    if not user_data or not user_data.get('phone'):
        return False
    
    # Onboarding yakunlanganligini tekshirish
    balance_query = """
    SELECT COUNT(*) as count FROM transactions 
    WHERE user_id = %s AND category IN ('boshlang_ich_balans', 'boshlang_ich_naqd', 'boshlang_ich_karta')
    """
    result = await db.execute_one(balance_query, (user_id,))
    has_initial_balance = result.get('count', 0) > 0 if result else False
    
    # Barcha kerakli ma'lumotlar to'ldirilganligini tekshirish
    is_complete = (
        user_data.get('name') and 
        user_data.get('name') != 'Xojayin' and
        user_data.get('source') and
        user_data.get('account_type') and
        has_initial_balance
    )
    
    return is_complete
```

## Mini App UI/UX tavsiyalari

1. **Telegram Web App API dan foydalanish:**
   - `window.Telegram.WebApp.initData` - Foydalanuvchi ma'lumotlarini olish
   - `window.Telegram.WebApp.ready()` - Mini app tayyor bo'lganda
   - `window.Telegram.WebApp.expand()` - Mini app ni kengaytirish

2. **Forma dizayni:**
   - Har bir maydon uchun aniq label va placeholder
   - Validatsiya xabarlari
   - Loading holati ko'rsatish
   - Muvaffaqiyatli saqlash xabari

3. **Ma'lumotlar saqlash:**
   - Har bir maydon to'ldirilganda darhol saqlash (real-time)
   - Yoki barcha maydonlar to'ldirilgandan keyin "Saqlash" tugmasi

4. **Xatoliklar bilan ishlash:**
   - Network xatoliklari
   - Validatsiya xatoliklari
   - Server xatoliklari

## Muhim eslatmalar

1. **Telegram User ID:**
   - Mini app dan `window.Telegram.WebApp.initData` orqali olinadi
   - Yoki `window.Telegram.WebApp.initDataUnsafe.user.id` orqali

2. **Xavfsizlik:**
   - Barcha so'rovlar Telegram Web App initData bilan autentifikatsiya qilinishi kerak
   - Server tomonida initData ni tekshirish kerak

3. **Ma'lumotlar bazasi:**
   - MySQL ma'lumotlar bazasi ishlatiladi
   - Asinxron operatsiyalar (aiomysql)

4. **Bot integratsiyasi:**
   - Bot foydalanuvchiga xabar yuboradi, agar ro'yxatdan o'tish yakunlanmagan bo'lsa
   - Mini app tugmasi har doim ko'rsatiladi, agar ro'yxatdan o'tish yakunlanmagan bo'lsa

## Misol kod

### React komponenti (misol)

```jsx
import { useEffect, useState } from 'react';

function RegistrationForm() {
  const [userData, setUserData] = useState({
    name: '',
    source: '',
    account_type: '',
    cash_balance: 0,
    card_balance: 0
  });
  
  const [loading, setLoading] = useState(false);
  
  useEffect(() => {
    // Telegram Web App ni ishga tushirish
    if (window.Telegram?.WebApp) {
      window.Telegram.WebApp.ready();
      window.Telegram.WebApp.expand();
      
      // Foydalanuvchi ID ni olish
      const userId = window.Telegram.WebApp.initDataUnsafe?.user?.id;
      if (userId) {
        // Mavjud ma'lumotlarni yuklash
        loadUserData(userId);
      }
    }
  }, []);
  
  const loadUserData = async (userId) => {
    try {
      const response = await fetch(`/api/user/${userId}`);
      const data = await response.json();
      setUserData(data);
    } catch (error) {
      console.error('Error loading user data:', error);
    }
  };
  
  const saveUserData = async () => {
    setLoading(true);
    try {
      const userId = window.Telegram.WebApp.initDataUnsafe?.user?.id;
      
      // Ism, source, account_type ni saqlash
      await fetch(`/api/user/${userId}/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: userData.name,
          source: userData.source,
          account_type: userData.account_type
        })
      });
      
      // Onboarding ma'lumotlarini saqlash
      await fetch(`/api/user/${userId}/onboarding`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          cash_balance: userData.cash_balance,
          card_balance: userData.card_balance
        })
      });
      
      // Muvaffaqiyatli saqlash xabari
      window.Telegram.WebApp.showAlert('Ma\'lumotlar saqlandi!');
      
      // Botga xabar yuborish (ixtiyoriy)
      window.Telegram.WebApp.sendData(JSON.stringify({ action: 'registration_complete' }));
      
    } catch (error) {
      console.error('Error saving user data:', error);
      window.Telegram.WebApp.showAlert('Xatolik yuz berdi. Qayta urinib ko\'ring.');
    } finally {
      setLoading(false);
    }
  };
  
  return (
    <div className="registration-form">
      <h1>Ro'yxatdan o'tish</h1>
      
      <input
        type="text"
        placeholder="Ismingiz"
        value={userData.name}
        onChange={(e) => setUserData({ ...userData, name: e.target.value })}
      />
      
      <select
        value={userData.source}
        onChange={(e) => setUserData({ ...userData, source: e.target.value })}
      >
        <option value="">Qayerdan eshitdingiz?</option>
        <option value="telegram">Telegram</option>
        <option value="instagram">Instagram</option>
        <option value="youtube">YouTube</option>
        <option value="tanish">Tanish</option>
        <option value="boshqa">Boshqa</option>
      </select>
      
      <select
        value={userData.account_type}
        onChange={(e) => setUserData({ ...userData, account_type: e.target.value })}
      >
        <option value="">Hisob turi</option>
        <option value="SHI">Shaxsiy</option>
        <option value="BIZNES">Biznes</option>
      </select>
      
      <input
        type="number"
        placeholder="Naqd pul (so'm)"
        value={userData.cash_balance}
        onChange={(e) => setUserData({ ...userData, cash_balance: parseInt(e.target.value) || 0 })}
      />
      
      <input
        type="number"
        placeholder="Karta balansi (so'm)"
        value={userData.card_balance}
        onChange={(e) => setUserData({ ...userData, card_balance: parseInt(e.target.value) || 0 })}
      />
      
      <button onClick={saveUserData} disabled={loading}>
        {loading ? 'Saqlanmoqda...' : 'Saqlash'}
      </button>
    </div>
  );
}

export default RegistrationForm;
```

## Aloqa

Agar savollar bo'lsa, bot dasturchisi bilan bog'laning.

