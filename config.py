import os
from dotenv import load_dotenv

load_dotenv()

# Bot konfiguratsiyasi
BOT_NAME = "Balans AI"
BOT_TOKEN = os.getenv('BOT_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
GOOGLE_CLOUD_PROJECT = os.getenv('GOOGLE_CLOUD_PROJECT')
GOOGLE_APPLICATION_CREDENTIALS = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
TELEGRAM_PAYMENT_PROVIDER_TOKEN = os.getenv('TELEGRAM_PAYMENT_PROVIDER_TOKEN')

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
    'MAX': 'Max',
    'FAMILY': 'Family',
    'FAMILY_PLUS': 'Family Plus',
    'FAMILY_MAX': 'Family Max',
    'BUSINESS': 'Business',
    'BUSINESS_PLUS': 'Business Plus',
    'BUSINESS_MAX': 'Business Max',
    'PREMIUM': 'Premium'
}

# Kategoriyalar
CATEGORIES = {
    'income': ['Ish haqi', 'Biznes', 'Investitsiya', 'Boshqa'],
    'expense': ['Ovqat', 'Transport', 'Kiyim', 'Uy', 'Sogʻliq', 'Taʼlim', 'Oʻyin-kulgi', 'Boshqa'],
    'debt': ['Qarz berish', 'Qarz olish']
}

# Tarif narxlari (1 oy uchun) - kopeklarda
TARIFF_PRICES = {
    'PLUS': 299900,  # 2,999 so'm (29,990 kopek)
    'BUSINESS': 999900,  # 9,999 so'm (99,990 kopek)
    'MAX': 499900,  # 4,999 so'm (49,990 kopek)
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
    'telegram_click': 'Telegram (Click)',
    'click': 'Click',
    'payme': 'Payme',
    'uzum_pay': 'Uzum Pay'
}
