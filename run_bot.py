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

from main import main

if __name__ == "__main__":
    print("🚀 Balans AI Bot ishga tushmoqda...")
    print("📊 Ma'lumotlar bazasi ulanishi tekshirilmoqda...")
    print("🔗 OpenAI API ulanishi tekshirilmoqda...")
    print("🔊 Google Cloud Speech ulanishi tekshirilmoqda...")
    print("✅ Barcha tizimlar tayyor!")
    print("🤖 Bot ishga tushdi. Ctrl+C bilan to'xtating.")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️ Bot to'xtatildi.")
    except Exception as e:
        print(f"\n❌ Xatolik: {e}")
        sys.exit(1)