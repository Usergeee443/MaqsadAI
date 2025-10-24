#!/usr/bin/env python3
"""
Server uchun bot setup
"""

import asyncio
import logging
from aiogram import Bot
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
import ssl
import os

# Bot token
BOT_TOKEN = os.getenv("BOT_TOKEN", "8087310424:AAGn99-GObyu8cU7ADPNTt950K3scdtGXUQ")

# Webhook sozlamalari
WEBHOOK_HOST = "https://your-domain.com"  # O'z domain ingizni kiriting
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

# Local server sozlamalari
WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = 8001

async def setup_webhook(bot: Bot):
    """Webhook ni sozlash"""
    try:
        # Webhook ni o'rnatish
        await bot.set_webhook(
            url=WEBHOOK_URL,
            drop_pending_updates=True,
        )
        print(f"✅ Webhook o'rnatildi: {WEBHOOK_URL}")
    except Exception as e:
        print(f"❌ Webhook o'rnatishda xatolik: {e}")

async def delete_webhook(bot: Bot):
    """Webhook ni o'chirish"""
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        print("✅ Webhook o'chirildi")
    except Exception as e:
        print(f"❌ Webhook o'chirishda xatolik: {e}")

async def main():
    """Asosiy funksiya"""
    # Bot yaratish
    bot = Bot(token=BOT_TOKEN)
    
    # Webhook ni o'chirish (polling uchun)
    await delete_webhook(bot)
    
    # Bot session ni yopish
    await bot.session.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
