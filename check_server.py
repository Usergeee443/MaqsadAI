#!/usr/bin/env python3
"""
Server uchun database connection tekshirish
"""

import asyncio
import aiomysql
import os
from dotenv import load_dotenv

load_dotenv()

async def check_database():
    """Database connection ni tekshirish"""
    try:
        # Environment variables ni tekshirish
        print("🔍 Environment variables tekshirilmoqda...")
        print(f"DB_HOST: {os.getenv('DB_HOST')}")
        print(f"DB_USER: {os.getenv('DB_USER')}")
        print(f"DB_PASSWORD: {'*' * len(os.getenv('DB_PASSWORD', '')) if os.getenv('DB_PASSWORD') else 'None'}")
        print(f"DB_NAME: {os.getenv('DB_NAME')}")
        print(f"DB_PORT: {os.getenv('DB_PORT')}")
        
        # Database connection ni tekshirish
        print("\n🔗 Database connection tekshirilmoqda...")
        conn = await aiomysql.connect(
            host=os.getenv('DB_HOST'),
            port=int(os.getenv('DB_PORT', '3306')),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASSWORD'),
            db=os.getenv('DB_NAME'),
            autocommit=True
        )
        
        print("✅ Database connection muvaffaqiyatli!")
        
        # Test query
        cursor = await conn.cursor()
        await cursor.execute("SELECT 1")
        result = await cursor.fetchone()
        print(f"✅ Test query natijasi: {result}")
        
        await cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Database connection xatolik: {e}")
        return False
    
    return True

async def main():
    """Asosiy funksiya"""
    print("🚀 Server database connection tekshirilmoqda...")
    success = await check_database()
    
    if success:
        print("\n🎉 Barcha narsalar to'g'ri ishlayapti!")
    else:
        print("\n❌ Database connection muammosi bor!")

if __name__ == "__main__":
    asyncio.run(main())
