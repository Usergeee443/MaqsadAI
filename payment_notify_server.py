#!/usr/bin/env python3
"""
Mini ilova uchun payment notify server
5005-portda ishlaydi
"""

from flask import Flask, request, jsonify
import asyncio
import sys
import threading
from pathlib import Path

# Project root ni path ga qo'shish
project_dir = Path(__file__).parent
sys.path.insert(0, str(project_dir))

from aiogram import Bot
from config import BOT_TOKEN

app = Flask(__name__)
bot = Bot(token=BOT_TOKEN)


@app.route('/payment-notify', methods=['POST'])
def payment_notify():
    """Mini ilovadan keladigan to'lov ma'lumotlarini qabul qilish"""
    try:
        data = request.get_json()
        
        # Ma'lumotlarni tekshirish
        user_id = data.get('user_id')
        amount = data.get('amount')
        status = data.get('status')
        
        if not user_id or not amount or not status:
            return jsonify({"ok": False, "error": "Missing required fields"}), 400
        
        # Status ga qarab xabar yuborish
        def send_message_sync():
            try:
                # Yangi event loop yaratish va ishga tushirish
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    if status == "success":
                        message = f"✅ To'lov {amount:,} so'm muvaffaqiyatli amalga oshirildi!"
                    else:
                        message = f"⚠️ To'lov amalga oshmadi. Status: {status}"
                    
                    loop.run_until_complete(bot.send_message(chat_id=user_id, text=message))
                    print(f"✅ Xabar yuborildi: user_id={user_id}, status={status}")
                finally:
                    loop.close()
            except Exception as e:
                print(f"❌ Xatolik: {e}")
        
        # Background da ishga tushirish (Flask thread pool)
        threading.Thread(target=send_message_sync, daemon=True).start()
        
        return jsonify({"ok": True}), 200
        
    except Exception as e:
        print(f"❌ Server xatolik: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Server holatini tekshirish"""
    return jsonify({"status": "ok", "message": "Payment notify server is running"}), 200


if __name__ == '__main__':
    print("🚀 Payment Notify Server ishga tushmoqda...")
    print("📡 Port: 5005")
    print("🔗 Endpoint: http://0.0.0.0:5005/payment-notify")
    app.run(host='0.0.0.0', port=5005, debug=False)
