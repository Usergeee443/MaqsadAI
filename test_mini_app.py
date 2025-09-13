#!/usr/bin/env python3
"""
Mini App test serveri
Oddiy HTTP server (HTTPS emas)
"""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import uvicorn

app = FastAPI(title="HamyonAI Mini App Test")

# Template fayllar
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def test_page(request: Request):
    """Test sahifasi"""
    return """
    <!DOCTYPE html>
    <html lang="uz">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>HamyonAI - Test Mini App</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 20px;
                margin: 0;
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            .container {
                text-align: center;
                max-width: 400px;
                background: rgba(255, 255, 255, 0.1);
                padding: 40px;
                border-radius: 20px;
                backdrop-filter: blur(10px);
            }
            h1 {
                font-size: 32px;
                margin-bottom: 20px;
            }
            p {
                font-size: 18px;
                line-height: 1.6;
                margin-bottom: 30px;
            }
            .status {
                background: rgba(255, 255, 255, 0.2);
                padding: 20px;
                border-radius: 10px;
                margin: 20px 0;
            }
            .emoji {
                font-size: 48px;
                margin-bottom: 20px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="emoji">📊</div>
            <h1>HamyonAI Mini App</h1>
            <p>Mini App muvaffaqiyatli ishga tushdi!</p>
            
            <div class="status">
                <h3>✅ Server holati</h3>
                <p>HTTP server ishlamoqda</p>
                <p>Port: 8000</p>
            </div>
            
            <div class="status">
                <h3>🔧 Keyingi qadamlar</h3>
                <p>1. Ngrok o'rnating</p>
                <p>2. HTTPS tunnel yarating</p>
                <p>3. Bot faylida URL yangilang</p>
            </div>
            
            <p><strong>Mini App tayyor!</strong></p>
        </div>
    </body>
    </html>
    """

@app.get("/api/test")
async def test_api():
    """Test API endpoint"""
    return {
        "status": "success",
        "message": "Mini App API ishlamoqda!",
        "data": {
            "balance": 1500000,
            "income": 2000000,
            "expense": 500000,
            "transactions": [
                {"type": "income", "amount": 1000000, "category": "Ish haqi", "description": "Oylik maosh"},
                {"type": "expense", "amount": 200000, "category": "Ovqat", "description": "Oziq-ovqat"},
                {"type": "expense", "amount": 100000, "category": "Transport", "description": "Taksi"},
                {"type": "expense", "amount": 200000, "category": "Uy", "description": "Kommunal to'lovlar"}
            ]
        }
    }

if __name__ == "__main__":
    print("🚀 Mini App test serverini ishga tushirish...")
    print("🌐 URL: http://localhost:8000")
    print("📊 Test API: http://localhost:8000/api/test")
    print("⏹️  To'xtatish uchun Ctrl+C")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
