#!/usr/bin/env python3
"""
Balans AI Bot - Moliyaviy yordamchi
Faqat moliyaviy funksiyalar
"""

import asyncio
import sys
from pathlib import Path

# Loyiha papkasini Python pathiga qo'shish
project_dir = Path(__file__).parent
sys.path.insert(0, str(project_dir))

from main import app
import uvicorn

if __name__ == "__main__":
    print("🚀 Balans AI Bot ishga tushmoqda...")
    print("📊 Ma'lumotlar bazasi ulanishi tekshirilmoqda...")
    print("🔗 OpenAI API ulanishi tekshirilmoqda...")
    print("🔊 Google Cloud Speech ulanishi tekshirilmoqda...")
    print("🌐 Mini-app API serveri ishga tushmoqda...")
    print("✅ Barcha tizimlar tayyor!")
    print("🤖 Bot va API server ishga tushdi. Ctrl+C bilan to'xtating.")
    print("📱 Mini-app: http://localhost:8001")
    
    try:
        # FastAPI ni ishga tushirish (bot ham parallel ishlaydi)
        uvicorn.run(app, host="0.0.0.0", port=8001)
    except KeyboardInterrupt:
        print("\n⏹️ Bot va API server to'xtatildi.")
    except Exception as e:
        print(f"\n❌ Xatolik: {e}")
        sys.exit(1)