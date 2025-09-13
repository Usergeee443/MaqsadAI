import os
from dotenv import load_dotenv

load_dotenv()

# Bot konfiguratsiyasi
BOT_NAME = "Balans AI"
BOT_TOKEN = os.getenv('BOT_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

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
    'PRO': 'Pro',
    'MAX': 'Max',
    'PREMIUM': 'Premium'
}

# Kategoriyalar
CATEGORIES = {
    'income': ['Ish haqi', 'Biznes', 'Investitsiya', 'Boshqa'],
    'expense': ['Ovqat', 'Transport', 'Kiyim', 'Uy', 'Sogʻliq', 'Taʼlim', 'Oʻyin-kulgi', 'Boshqa'],
    'debt': ['Qarz berish', 'Qarz olish']
}
