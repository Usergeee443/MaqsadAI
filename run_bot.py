#!/usr/bin/env python3
"""
HamyonAI&MaqsadAI Bot ishga tushirish skripti
"""

import asyncio
import sys
import os
from pathlib import Path

# Loyiha papkasini Python pathiga qo'shish
project_dir = Path(__file__).parent
sys.path.insert(0, str(project_dir))

from main import main

if __name__ == "__main__":
    print("🤖 HamyonAI&MaqsadAI Bot ishga tushmoqda...")
    print("📊 Ma'lumotlar bazasi ulanishi tekshirilmoqda...")
    print("🔗 OpenAI API ulanishi tekshirilmoqda...")
    print("✅ Barcha tizimlar tayyor!")
    print("🚀 Bot ishga tushdi. Ctrl+C bilan to'xtating.")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Bot to'xtatildi.")
    except Exception as e:
        print(f"❌ Xatolik: {e}")
        sys.exit(1)
