# Balans AI - Moliyaviy Yordamchi Bot

Telegram boti orqali shaxsiy moliyaviy ma'lumotlaringizni boshqarish va AI yordamida moliyaviy maslahatlar olish.

## 🚀 Asosiy funksiyalar

- **💰 Moliyaviy ma'lumotlar**: Kirim, chiqim va qarzlar
- **📊 Hisobotlar**: Batafsil moliyaviy tahlil va statistikalar
- **🎯 AI yordamchi**: Moliyaviy maslahatlar va tavsiyalar
- **🎵 Audio qo'llab-quvvatlash**: Ovozli xabarlar orqali ma'lumot kiritish (Pro/Max)

## 📱 Tariflar

- **🆓 Bepul**: Asosiy moliyaviy hisobotlar, 10 ta tranzaksiya/oy
- **⭐ Plus**: 500 text, 250 voice tranzaksiya/oy - 19,990 so'm/oy
- **💎 Pro**: 1,000 text, 500 voice tranzaksiya/oy - 199,900 so'm/oy

## 🛠️ O'rnatish

1. **Kerakli kutubxonalarni o'rnating:**
```bash
pip3 install -r requirements.txt
```

2. **Environment faylini yarating:**
```bash
cp .env.example .env
```

3. **`.env` faylini to'ldiring:**
```
BOT_TOKEN=your_telegram_bot_token
OPENAI_API_KEY=your_openai_api_key
DB_HOST=localhost
DB_NAME=balans_ai
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_PORT=3306
```

4. **Ma'lumotlar bazasini yarating:**
```sql
CREATE DATABASE balans_ai;
```

5. **Botni ishga tushiring:**
```bash
python3 run_bot.py
```

### Payment Notify Server

Mini ilova uchun alohida Flask server ishga tushiring:

```bash
python3 payment_notify_server.py
```

Server 5005-portda ishlaydi va mini ilovadan to'lov ma'lumotlarini qabul qiladi.
Batafsil: [PAYMENT_NOTIFY_SERVER.md](PAYMENT_NOTIFY_SERVER.md)

## 📊 Ma'lumotlar bazasi

Bot MySQL ma'lumotlar bazasidan foydalanadi. Avtomatik ravishda quyidagi jadvallar yaratiladi:
- `users` - Foydalanuvchilar
- `transactions` - Moliyaviy tranzaksiyalar
- `categories` - Kategoriyalar

## 🤖 AI funksiyalari

- **GPT-4o/4o-mini** - Moliyaviy ma'lumotlarni tahlil qilish (PRO tarif)
- **GPT-3.5-turbo** - Tezkor va arzon tranzaksiya qayta ishlash (Plus tarif)
- **Mistral-7B-Instruct** - Arzon AI model (Plus tarif fallback)
- **Google Cloud Speech** - Audio xabarlarni matnga aylantirish
- **Ko'p tilli qo'llab-quvvatlash** - Uzbek, Rus, Turk, Qozoq tillari

## 📝 Foydalanish

1. `/start` - Botni ishga tushirish
2. Matn yoki ovozli xabar yuboring:
   - "Bugun 50 ming so'm ovqatga ketdi"
   - "100 ming so'm ish haqi oldim"
   - "30 ming so'm qarz berdim"
3. `📊 Hisobotlar` - Moliyaviy hisobotlarni ko'rish
4. `👤 Profil` - Profil va tarif sozlamalari

## 🔧 Texnik xususiyatlar

- **Python 3.8+**
- **aiogram 3.4.1** - Telegram Bot API
- **OpenAI API** - AI funksiyalari
- **MySQL** - Ma'lumotlar bazasi
- **Asyncio** - Asinxron dasturlash

## 📄 Litsenziya

MIT License