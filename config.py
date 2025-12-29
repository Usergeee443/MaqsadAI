import os
from dotenv import load_dotenv

load_dotenv()

# Bot konfiguratsiyasi
BOT_NAME = "Balans AI"
BOT_TOKEN = os.getenv('BOT_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
GOOGLE_CLOUD_PROJECT = os.getenv('GOOGLE_CLOUD_PROJECT')
GOOGLE_APPLICATION_CREDENTIALS = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
TELEGRAM_PAYMENT_PROVIDER_TOKEN = os.getenv('TELEGRAM_PAYMENT_PROVIDER_TOKEN')

# Telegram Stars sozlamalari
STARS_ENABLED = os.getenv('STARS_ENABLED', 'true').lower() == 'true'
# 1 Star nechchi so'mga tengligini konfiguratsiyalash (masalan, 1 Star = 1000 so'm)
# Admin o'z kursini shu yerda belgilaydi
STARS_SOM_PER_STAR = int(os.getenv('STARS_SOM_PER_STAR', '1000'))

# MySQL konfiguratsiyasi
MYSQL_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'database': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'port': int(os.getenv('DB_PORT', '3306')),
}

# Tariflar
TARIFFS = {
    'FREE': 'Bepul',
    'PLUS': 'Plus',
    'PRO': 'Pro',
    'FAMILY': 'Oila',
    'FAMILY_PLUS': 'Oila Plus',
    'FAMILY_MAX': 'Oila Max',
    'BUSINESS': 'Biznes',
    'BUSINESS_PLUS': 'Biznes Plus',
    'BUSINESS_MAX': 'Biznes Max',
    'EMPLOYEE': 'Xodim'
}

# Plus paketlari
PLUS_PACKAGES = {
    'PLUS_PACK_SMALL': {
        'name': "Starter paket",
        'text_limit': 300,
        'voice_limit': 100,
        'price': 9900
    },
    'PLUS_PACK_MEDIUM': {
        'name': "Growth paket",
        'text_limit': 750,
        'voice_limit': 250,
        'price': 19900
    },
    'PLUS_PACK_LARGE': {
        'name': "Pro paket",
        'text_limit': 1750,
        'voice_limit': 600,
        'price': 39900
    }
}

# Kategoriyalar - kengaytirilgan (10x ko'p)
CATEGORIES = {
    'income': [
        'Ish haqi', 'Bonus', 'Mukofot', 'Biznes', 'Savdo', 'Do\'kon', 
        'Investitsiya', 'Depozit', 'Foiz', 'Dividend', 'Sotuv', 
        'Ijaradan daromad', 'Kvartira ijarasi', 'Grant', 'Yordam', 
        'Sovg\'a', 'Hadyalar', 'Loyiha', 'Freelance', 'Konsultatsiya',
        'Trening', 'Kurs', 'Dars', 'Tavsiya', 'Komissiya', 'Boshqa'
    ],
    'expense': [
        'Ovqat', 'Restoran', 'Kafe', 'Fastfood', 'Non', 'Sut', 'Go\'sht',
        'Transport', 'Taksi', 'Benzin', 'Yoqilg\'i', 'Metro', 'Avtobus',
        'Kiyim', 'Poyabzal', 'Aksessuar', 'Uy', 'Kvartira', 'Mebel', 
        'Uy-ro\'zg\'or', 'Kommunal', 'Elektr', 'Suv', 'Gaz', 'Issiqlik',
        'Sog\'liq', 'Dori', 'Shifokor', 'Klinika', 'Tibbiy xizmat',
        'Ta\'lim', 'Maktab', 'Universitet', 'Kurs', 'Kitob', 'Darslik',
        'O\'yin-kulgi', 'Kino', 'Teatr', 'Konsert', 'O\'yin', 'Sayr',
        'Sayohat', 'Samolyot', 'Mehmonxona', 'Turizm', 'Viza',
        'Kredit', 'Qarz to\'lovi', 'Foiz', 'Internet', 'Telefon', 
        'Mobil aloqa', 'Wi-Fi', 'Sog\'liqni saqlash', 'Sport', 'Fitnes',
        'Masaj', 'Parikmaxona', 'Salon', 'Kitob', 'Jurnal', 'Gazeta',
        'Sovg\'a', 'Hadyalar', 'Tug\'ilgan kun', 'To\'y', 'Tadbir',
        'Boshqa'
    ],
    'debt': ['Qarz berish', 'Qarz olish']
}

# Tarif narxlari (1 oy uchun) - kopeklarda
TARIFF_PRICES = {
    'PLUS': 1999000,  # 19,990 so'm (1,999,000 kopek)
    'BUSINESS': 999900,  # 9,999 so'm (99,990 kopek)
    'PRO': 199900,  # 199,900 so'm
    'FAMILY': 399900,  # 3,999 so'm (39,990 kopek)
    'FAMILY_PLUS': 599900,  # 5,999 so'm (59,990 kopek)
    'FAMILY_MAX': 799900,  # 7,999 so'm (79,990 kopek)
    'BUSINESS_PLUS': 1499900,  # 14,999 so'm (149,990 kopek)
    'BUSINESS_MAX': 1999900,  # 19,999 so'm (199,990 kopek)
}

# Chegirma foizlari (muddat bo'yicha)
DISCOUNT_RATES = {
    1: 0,    # 1 oy - chegirma yo'q
    2: 5,    # 2 oy - 5% chegirma
    3: 10,   # 3 oy - 10% chegirma
    6: 15,   # 6 oy - 15% chegirma
    12: 25,  # 12 oy - 25% chegirma
}

# To'lov usullari
PAYMENT_METHODS = {
    'telegram_stars': 'Telegram Stars',
    'telegram_click': 'Telegram (Click)',
    'click': 'Click',
    'payme': 'Payme',
    'uzum_pay': 'Uzum Pay'
}

# Mini-app URL'lari
PAYMENT_PLUS_WEBAPP_URL = os.getenv('PAYMENT_PLUS_WEBAPP_URL', 'https://balansai.onrender.com/payment-plus')
PAYMENT_PRO_WEBAPP_URL = os.getenv('PAYMENT_PRO_WEBAPP_URL', 'https://balansai.onrender.com/payment-pro')

# Speech-to-Text model sozlamalari
SPEECH_MODELS = {
    'GOOGLE': 'Google Cloud Speech-to-Text',
    'ELEVENLABS': 'ElevenLabs Speech-to-Text'
}

# Hozirgi faol modellar (admin tomonidan boshqariladi)
ACTIVE_SPEECH_MODELS = {
    'GOOGLE': True,  # Google Cloud Speech-to-Text yoqilgan
    'ELEVENLABS': True  # ElevenLabs Speech-to-Text yoqilgan
}

# 1 haftalik sinov holati (admin tomonidan boshqariladi)
FREE_TRIAL_ENABLED = {
    'PLUS': True,        # Plus tarif uchun 1 haftalik sinov yoqilgan
    'PRO': True,         # Pro tarif uchun 1 haftalik sinov yoqilgan
    'FAMILY': True,      # Family tarif uchun 1 haftalik sinov yoqilgan
    'FAMILY_PLUS': True, # Family Plus tarif uchun 1 haftalik sinov yoqilgan
    'FAMILY_MAX': True,  # Family Max tarif uchun 1 haftalik sinov yoqilgan
    'BUSINESS': True,    # Business tarif uchun 1 haftalik sinov yoqilgan
    'BUSINESS_PLUS': True, # Business Plus tarif uchun 1 haftalik sinov yoqilgan
    'BUSINESS_MAX': True  # Business Max tarif uchun 1 haftalik sinov yoqilgan
}
