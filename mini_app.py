from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import json
import logging
from datetime import datetime, timedelta
from database import db
from financial_module import FinancialModule
import plotly.graph_objects as go
import plotly.express as px
import base64
import io

app = FastAPI(title="HamyonAI Mini App")

# Template va static fayllar
templates = Jinja2Templates(directory="templates")

financial_module = FinancialModule()

@app.get("/", response_class=HTMLResponse)
async def reports_page(request: Request):
    """Hisobotlar sahifasini ko'rsatish"""
    return templates.TemplateResponse("reports.html", {"request": request})

@app.post("/api/reports")
async def get_reports_data(request: Request):
    """Hisobotlar ma'lumotlarini API orqali olish"""
    try:
        data = await request.json()
        user_id = data.get('user_id')
        
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID required")
        
        # Balans ma'lumotlarini olish
        balance_data = await financial_module.get_user_balance(user_id)
        
        # Kategoriyalar bo'yicha chiqimlar
        expense_categories = await financial_module.get_category_expenses(user_id, 30)
        
        # So'nggi tranzaksiyalar
        recent_transactions = await financial_module.get_recent_transactions(user_id, 10)
        
        # Oylik tendensiya (oxirgi 6 oy)
        monthly_trend = await get_monthly_trend(user_id)
        
        return {
            "balance": balance_data['balance'],
            "income": balance_data['income'],
            "expense": balance_data['expense'],
            "debt": balance_data['debt'],
            "expense_categories": expense_categories,
            "recent_transactions": recent_transactions,
            "monthly_trend": monthly_trend
        }
        
    except Exception as e:
        logging.error(f"Reports API xatolik: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

async def get_monthly_trend(user_id: int, months: int = 6):
    """Oylik tendensiya ma'lumotlarini olish"""
    try:
        trend_data = []
        
        for i in range(months):
            # Har bir oy uchun ma'lumotlarni olish
            start_date = datetime.now() - timedelta(days=30 * (i + 1))
            end_date = datetime.now() - timedelta(days=30 * i)
            
            # Kirimlar
            income_query = """
            SELECT COALESCE(SUM(amount), 0) FROM transactions 
            WHERE user_id = %s AND transaction_type = 'income' 
            AND created_at >= %s AND created_at < %s
            """
            income_result = await db.execute_one(income_query, (user_id, start_date, end_date))
            income = income_result[0] if income_result else 0.0
            
            # Chiqimlar
            expense_query = """
            SELECT COALESCE(SUM(amount), 0) FROM transactions 
            WHERE user_id = %s AND transaction_type = 'expense' 
            AND created_at >= %s AND created_at < %s
            """
            expense_result = await db.execute_one(expense_query, (user_id, start_date, end_date))
            expense = expense_result[0] if expense_result else 0.0
            
            trend_data.append({
                "date": start_date.strftime("%Y-%m"),
                "income": float(income),
                "expense": float(expense)
            })
        
        return list(reversed(trend_data))  # Eski oylardan yangi oylarga
        
    except Exception as e:
        logging.error(f"Monthly trend xatolik: {e}")
        return []

@app.get("/api/chart/expense-categories")
async def get_expense_categories_chart(user_id: int):
    """Chiqimlar kategoriyalar grafigi"""
    try:
        categories = await financial_module.get_category_expenses(user_id, 30)
        
        if not categories:
            return {"error": "No data available"}
        
        # Plotly grafigi yaratish
        fig = go.Figure(data=[go.Pie(
            labels=list(categories.keys()),
            values=list(categories.values()),
            hole=0.3
        )])
        
        fig.update_layout(
            title="Chiqimlar kategoriyalar bo'yicha",
            font=dict(size=12)
        )
        
        # Grafikni base64 ga aylantirish
        img_bytes = fig.to_image(format="png", width=400, height=300)
        img_base64 = base64.b64encode(img_bytes).decode()
        
        return {"image": f"data:image/png;base64,{img_base64}"}
        
    except Exception as e:
        logging.error(f"Chart xatolik: {e}")
        return {"error": "Chart generation failed"}

@app.get("/api/chart/monthly-trend")
async def get_monthly_trend_chart(user_id: int):
    """Oylik tendensiya grafigi"""
    try:
        trend_data = await get_monthly_trend(user_id, 6)
        
        if not trend_data:
            return {"error": "No data available"}
        
        dates = [item["date"] for item in trend_data]
        income = [item["income"] for item in trend_data]
        expense = [item["expense"] for item in trend_data]
        
        fig = go.Figure()
        
        fig.add_trace(go.Scatter(
            x=dates,
            y=income,
            mode='lines+markers',
            name='Kirim',
            line=dict(color='#28a745', width=3)
        ))
        
        fig.add_trace(go.Scatter(
            x=dates,
            y=expense,
            mode='lines+markers',
            name='Chiqim',
            line=dict(color='#dc3545', width=3)
        ))
        
        fig.update_layout(
            title="Oylik tendensiya",
            xaxis_title="Oy",
            yaxis_title="Summa (so'm)",
            font=dict(size=12)
        )
        
        # Grafikni base64 ga aylantirish
        img_bytes = fig.to_image(format="png", width=400, height=300)
        img_base64 = base64.b64encode(img_bytes).decode()
        
        return {"image": f"data:image/png;base64,{img_base64}"}
        
    except Exception as e:
        logging.error(f"Trend chart xatolik: {e}")
        return {"error": "Chart generation failed"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
