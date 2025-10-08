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
