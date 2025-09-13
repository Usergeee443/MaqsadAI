#!/usr/bin/env python3
"""
Mini App serverini ishga tushirish uchun script
HTTPS tunnel bilan
"""

import subprocess
import time
import requests
import json
import os
from mini_app import app
import uvicorn

def get_ngrok_url():
    """Ngrok tunnel URLini olish"""
    try:
        response = requests.get("http://localhost:4040/api/tunnels")
        data = response.json()
        
        for tunnel in data['tunnels']:
            if tunnel['proto'] == 'https':
                return tunnel['public_url']
        
        return None
    except:
        return None

def start_ngrok():
    """Ngrok tunnel ishga tushirish"""
    try:
        # Ngrok ishga tushirish
        subprocess.Popen(['ngrok', 'http', '8000'], 
                        stdout=subprocess.DEVNULL, 
                        stderr=subprocess.DEVNULL)
        
        # Ngrok ishga tushishini kutish
        for i in range(30):  # 30 soniya kutish
            time.sleep(1)
            url = get_ngrok_url()
            if url:
                print(f"✅ Ngrok tunnel tayyor: {url}")
                return url
        
        print("❌ Ngrok tunnel ishga tushmadi")
        return None
        
    except FileNotFoundError:
        print("❌ Ngrok o'rnatilmagan. Iltimos, https://ngrok.com/ dan o'rnating")
        return None

def update_bot_webapp_url(webapp_url):
    """Bot faylida Web App URLini yangilash"""
    try:
        # main.py faylini o'qish
        with open('main.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # URLni yangilash
        old_url = 'web_app=WebAppInfo(url="http://localhost:8000")'
        new_url = f'web_app=WebAppInfo(url="{webapp_url}")'
        
        if old_url in content:
            content = content.replace(old_url, new_url)
            
            # Faylni saqlash
            with open('main.py', 'w', encoding='utf-8') as f:
                f.write(content)
            
            print(f"✅ Bot faylida Web App URL yangilandi: {webapp_url}")
            return True
        else:
            print("⚠️ Web App URL topilmadi")
            return False
            
    except Exception as e:
        print(f"❌ Bot faylini yangilashda xatolik: {e}")
        return False

def main():
    print("🚀 Mini App serverini ishga tushirish...")
    
    # Ngrok tunnel ishga tushirish
    webapp_url = start_ngrok()
    
    if not webapp_url:
        print("❌ Ngrok tunnel ishga tushmadi. Oddiy HTTP server ishga tushiramiz...")
        print("📝 Eslatma: Telegram Web App faqat HTTPS URLlarni qabul qiladi")
        print("🌐 Mini App: http://localhost:8000")
        
        # Oddiy server ishga tushirish
        uvicorn.run(app, host="0.0.0.0", port=8000)
        return
    
    # Bot faylida URLni yangilash
    update_bot_webapp_url(webapp_url)
    
    print(f"🌐 Mini App URL: {webapp_url}")
    print("🤖 Endi botni qayta ishga tushiring")
    print("📱 Mini App server ishga tushmoqda...")
    
    # Mini App serverini ishga tushirish
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main()
