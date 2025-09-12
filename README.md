# HamyonAI&MaqsadAI Bot

Telegram bot moliyaviy yordamchi va maqsad boshqaruv tizimi.

## Xususiyatlar

### 🆓 Bepul tarif
- Moliyaviy yordamchi (qo'lda kiritish)
- To-Do boshqaruvchi
- Hisobotlar

### ⭐ Pro tarif
- Moliyaviy yordamchi (AI yordamida)
- To-Do boshqaruvchi
- Hisobotlar

### 💎 Max tarif
- Moliyaviy yordamchi (AI yordamida)
- To-Do boshqaruvchi
- Hisobotlar
- Maqsad AI (AI yordamida maqsad yaratish va boshqarish)

## O'rnatish

1. Repository ni klonlang:
```bash
git clone <repository-url>
cd Maqsad-AI
```

2. Virtual environment yarating va faollashtiring:
```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# yoki
.venv\Scripts\activate  # Windows
```

3. Kerakli paketlarni o'rnating:
```bash
pip install -r requirements.txt
```

4. `.env` faylini yarating:
```bash
cp env_example.txt .env
```

5. `.env` faylini tahrirlang va kerakli ma'lumotlarni kiriting:
```env
BOT_TOKEN=your_bot_token_here
OPENAI_API_KEY=your_openai_api_key_here
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_db_password_here
DB_NAME=MaqsadAiBot
```

6. Ma'lumotlar bazasini sozlang:
```bash
mysql -u root -p < database_schema.sql
```

7. Botni ishga tushiring:
```bash
python run_bot.py
```

## Konfiguratsiya

Bot `.env` faylidan konfiguratsiyani o'qiydi. `env_example.txt` faylini `.env` ga nusxalang va quyidagi parametrlarni to'ldiring:

- `BOT_TOKEN` - Telegram bot tokeni (@BotFather dan oling)
- `OPENAI_API_KEY` - OpenAI API kaliti
- `DB_HOST` - MySQL server manzili
- `DB_PORT` - MySQL port (default: 3306)
- `DB_USER` - MySQL foydalanuvchi nomi
- `DB_PASSWORD` - MySQL parol
- `DB_NAME` - Ma'lumotlar bazasi nomi

## Ma'lumotlar bazasi

Bot quyidagi jadvallardan foydalanadi:
- `users` - Foydalanuvchilar
- `transactions` - Moliyaviy tranzaksiyalar
- `todos` - To-Do vazifalar
- `goals` - Maqsadlar
- `daily_tasks` - Kunlik vazifalar
- `ai_conversations` - AI suhbatlar

## Foydalanish

1. `/start` buyrug'ini yuboring
2. Tarifingizni tanlang
3. Kerakli xizmatni tanlang va foydalaning

## Texnik talablar

- Python 3.8+
- MySQL 5.7+
- OpenAI API kaliti
- Telegram Bot Token
