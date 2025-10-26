import os
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import openai
from database import Database
import json

# OpenAI API key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "your_api_key_here")
openai.api_key = OPENAI_API_KEY

# Initialize logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AIChat:
    """AI chat klassi - moliyaviy savollar va maslahatlar uchun (MAX tarif uchun)"""
    
    def __init__(self):
        self.db = Database()
        self.system_prompt = """Sen Balans AI ning shaxsiy buxgalter AI yordamchisisan. 

Vazifang:
1. Foydalanuvchining moliyaviy savollariga qisqa, aniq, foydali javob ber
2. Xarajat/daromad/qarz yozsa - avtomatik aniqlab takrorlash va tasdiqlash so'rash
3. Javoblarni 1-4 bosqichli qilib tuzat: Asosiy javob → Tahlil → Ruhlantiruvchi gap → Tugma taklif
4. "Ha", "ok", "go" deb yozsa → keyingi bosqichni boshlash  
5. "Yo'q", "bekor" deb yozsa → yumshoq uslubda boshqa yechim taklif etish

Uslub: Do'stona, lekin professional. Qisqa, aniq. Foydalanuvchi ismini eslab qolish.
Til: O'zbek tili (lotin), lekin ingliz yoki rus tilida savol bo'lsa shu til bilan javob ber."""

    async def get_user_financial_context(self, user_id: int) -> Dict:
        """Foydalanuvchining moliyaviy kontekstini olish"""
        try:
            # Balanslar
            balances = await self.db.get_balances(user_id)
            
            # Oxirgi tranzaksiyalar
            recent_transactions = await self.db.execute_query(
                """
                SELECT t.*, c.name as category_name, c.icon 
                FROM transactions t
                LEFT JOIN categories c ON t.category_id = c.id
                WHERE t.user_id = %s
                ORDER BY t.created_at DESC
                LIMIT 20
                """,
                (user_id,)
            )
            
            # Qarzlar
            debts = await self.db.execute_query(
                """
                SELECT * FROM debts 
                WHERE user_id = %s AND status != 'paid'
                ORDER BY created_at DESC
                """,
                (user_id,)
            )
            
            # Oy statistikasi
            month_stats = await self.db.execute_query(
                """
                SELECT 
                    SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END) as total_income,
                    SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END) as total_expense,
                    COUNT(*) as transaction_count
                FROM transactions
                WHERE user_id = %s 
                AND MONTH(created_at) = MONTH(CURRENT_DATE)
                AND YEAR(created_at) = YEAR(CURRENT_DATE)
                """,
                (user_id,)
            )
            
            context = {
                "balances": balances,
                "recent_transactions": recent_transactions if recent_transactions else [],
                "debts": debts if debts else [],
                "month_stats": month_stats[0] if month_stats else {},
            }
            
            return context
            
        except Exception as e:
            logger.error(f"Error getting financial context: {e}")
            return {}
    
    async def get_chat_history(self, user_id: int, limit: int = 10) -> List[Dict]:
        """Chat tarixini olish"""
        try:
            history = await self.db.execute_query(
                """
                SELECT role, content, created_at
                FROM ai_chat_history
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (user_id, limit)
            )
            
            history.reverse()
            return [
                {"role": h[0], "content": h[1], "created_at": h[2]} 
                for h in history
            ]
            
        except Exception as e:
            logger.error(f"Error getting chat history: {e}")
            return []
    
    async def save_to_history(self, user_id: int, role: str, content: str):
        """Chat tarixiga saqlash"""
        try:
            await self.db.execute_query(
                """
                INSERT INTO ai_chat_history (user_id, role, content, created_at)
                VALUES (%s, %s, %s, NOW())
                """,
                (user_id, role, content)
            )
        except Exception as e:
            logger.error(f"Error saving to history: {e}")
    
    async def generate_response(self, user_id: int, question: str) -> str:
        """AI javob generatsiya qilish"""
        try:
            # Moliyaviy kontekstni olish
            context = await self.get_user_financial_context(user_id)
            
            # Chat tarixini olish
            history = await self.get_chat_history(user_id, limit=10)
            
            # Kontekstni matn shakliga o'tkazish
            context_text = self._format_context(context)
            
            # Messages tayyorlash
            messages = [{"role": "system", "content": self.system_prompt}]
            
            # Kontekstni qo'shish
            messages.append({
                "role": "system", 
                "content": f"Foydalanuvchining joriy moliyaviy holati:\n{context_text}"
            })
            
            # Chat tarixini qo'shish
            for msg in history[-6:]:
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
            
            # Foydalanuvchi savolini qo'shish
            messages.append({"role": "user", "content": question})
            
            # OpenAI API chaqiruvi
            response = await openai.ChatCompletion.acreate(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=1000,
                temperature=0.7
            )
            
            ai_response = response.choices[0].message.content
            
            # Tarixga saqlash
            await self.save_to_history(user_id, "user", question)
            await self.save_to_history(user_id, "assistant", ai_response)
            
            return ai_response
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return "Kechirasiz, javob berishda xatolik yuz berdi. Iltimos, qayta urinib ko'ring."
    
    def _format_context(self, context: Dict) -> str:
        """Kontekstni matn shakliga o'tkazish"""
        text = "=== Moliyaviy Ma'lumotlar ===\n\n"
        
        # Balanslar
        balances = context.get("balances", {})
        text += f"Balanslar:\n"
        text += f"- Naqd pul: {balances.get('cash_balance', 0):,.0f} so'm\n"
        text += f"- Sof balans: {balances.get('net_balance', 0):,.0f} so'm\n"
        text += f"- Jami kirim: {balances.get('total_income', 0):,.0f} so'm\n"
        text += f"- Jami chiqim: {balances.get('total_expense', 0):,.0f} so'm\n\n"
        
        # Oy statistikasi
        month_stats = context.get("month_stats", {})
        if month_stats:
            text += f"Oy statistikasi:\n"
            text += f"- Oyli kirim: {month_stats.get('total_income', 0):,.0f} so'm\n"
            text += f"- Oyli chiqim: {month_stats.get('total_expense', 0):,.0f} so'm\n"
            text += f"- Tranzaksiyalar soni: {month_stats.get('transaction_count', 0)}\n\n"
        
        # Oxirgi tranzaksiyalar
        transactions = context.get("recent_transactions", [])
        if transactions:
            text += "Oxirgi tranzaksiyalar:\n"
            for t in transactions[:5]:
                t_type = "kirim" if t['type'] == 'income' else "chiqim"
                amount = t.get('amount', 0)
                category = t.get('category_name', 'Nomalum')
                created_at = t.get('created_at', datetime.now())
                
                text += f"- {t_type}: {amount:,.0f} so'm ({category}) - {created_at.strftime('%d.%m.%Y')}\n"
            text += "\n"
        
        # Qarzlar
        debts = context.get("debts", [])
        if debts:
            text += "Qarzlar:\n"
            for d in debts[:3]:
                debt_type = "berilgan" if d['type'] == 'lent' else "olingan"
                amount = d.get('amount', 0)
                text += f"- {debt_type}: {amount:,.0f} so'm\n"
            text += "\n"
        
        return text
