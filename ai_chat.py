import os
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from openai import OpenAI
from database import Database
import json

# OpenAI API key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "your_api_key_here")
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Initialize logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AIChat:
    """AI chat klassi - moliyaviy savollar va maslahatlar uchun (MAX tarif uchun)"""
    
    def __init__(self, db=None):
        # Agar db berilmasa, yangi Database yaratish
        self.db = db if db else Database()
        self.system_prompt = """Sen Balans AI ning shaxsiy buxgalter yordamchisisan.

🎯 **Asosiy vazifang:**
- Foydalanuvchining moliyaviy savollariga **do'stona, professional** javob ber
- Xarajat/daromad/qarz yozsa - avtomatik aniqlab takrorlash va tasdiqlash so'rash
- Javoblarni **1-4 bosqichli** qilib tuzat

📋 **Javob tuzishi:**
1. **Asosiy javob** - real moliyaviy tahlil (qisqa va aniq)
2. **Tahlil** - kamchiliklar va tavsiyalar (kerak bo'lsa)
3. **Ruhlantiruvchi gap** - ijobiy natijalar bo'lsa (ixtiyoriy)
4. **Taklif/Tugma** - keyingi qadam taklifi (ixtiyoriy)

🔄 **Replay:**
- "Ha", "ok", "go" → keyingi bosqichni boshlash
- "Yo'q", "bekor" → yumshoq boshqa yechim taklif

💬 **Uslub:**
- Do'stona, professional
- Qisqa (max 3-4 qator)
- Foydalanuvchi ismini eslab qol
- Emoji: minimal (1-2 ta max)

🌍 **Tillar:**
- Asosiy: O'zbek tili (lotin)
- Ingliz yoki rus tilida savol → shu til bilan javob"""

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
            
            # OpenAI API chaqiruvi (async emas - sync)
            from asyncio import run_in_executor
            
            def call_openai():
                response = openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    max_tokens=1000,
                    temperature=0.7
                )
                return response.choices[0].message.content
            
            ai_response = await run_in_executor(None, call_openai)
            
            # Tarixga saqlash
            await self.save_to_history(user_id, "user", question)
            await self.save_to_history(user_id, "assistant", ai_response)
            
            return ai_response
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return "Kechirasiz, javob berishda xatolik yuz berdi. Iltimos, qayta urinib ko'ring."
    
    def _format_context(self, context: Dict) -> str:
        """Kontekstni matn shakliga o'tkazish"""
        text = "📊 **Foydalanuvchi moliyaviy holati**\n\n"
        
        # Balanslar
        balances = context.get("balances", {})
        if balances:
            if isinstance(balances, dict):
                cash = balances.get('cash_balance', 0) or 0
                net = balances.get('net_balance', 0) or 0
                income = balances.get('total_income', 0) or 0
                expense = balances.get('total_expense', 0) or 0
                
                text += f"💰 **Balans:** {net:,.0f} so'm\n"
                text += f"💵 **Naqd:** {cash:,.0f} so'm\n"
                text += f"📈 **Jami kirim:** {income:,.0f} so'm\n"
                text += f"📉 **Jami chiqim:** {expense:,.0f} so'm\n\n"
        
        # Oy statistikasi
        month_stats = context.get("month_stats", {})
        if month_stats:
            mi = month_stats.get('total_income', 0) or 0
            me = month_stats.get('total_expense', 0) or 0
            mc = month_stats.get('transaction_count', 0) or 0
            
            text += f"📅 **Bu oy:**\n"
            text += f"- Kirim: {mi:,.0f} so'm\n"
            text += f"- Chiqim: {me:,.0f} so'm\n"
            text += f"- Tranzaksiyalar: {mc} ta\n\n"
        
        # Oxirgi tranzaksiyalar
        transactions = context.get("recent_transactions", [])
        if transactions and len(transactions) > 0:
            text += "📝 **Oxirgi xarajat/daromadlar:**\n"
            for idx, t in enumerate(transactions[:7], 1):
                try:
                    if isinstance(t, dict):
                        t_type = "kirim" if t.get('type') == 'income' else "chiqim"
                        amount = float(t.get('amount', 0))
                        category = t.get('category_name', 'Nomalum')
                        desc = t.get('description', '')[:30] if t.get('description') else ''
                        
                        text += f"{idx}. {t_type}: {amount:,.0f} so'm"
                        if category and category != 'Nomalum':
                            text += f" ({category})"
                        if desc:
                            text += f" - {desc}"
                        text += "\n"
                except Exception as e:
                    logger.error(f"Error formatting transaction: {e}")
                    continue
            text += "\n"
        
        # Qarzlar
        debts = context.get("debts", [])
        if debts and len(debts) > 0:
            text += "💳 **Qarzlar:**\n"
            for idx, d in enumerate(debts[:5], 1):
                try:
                    if isinstance(d, dict):
                        debt_type = "berilgan" if d.get('type') == 'lent' else "olingan"
                        amount = float(d.get('amount', 0))
                        person = d.get('person', '')[:20] if d.get('person') else 'Nomalum'
                        
                        text += f"{idx}. {debt_type}: {amount:,.0f} so'm"
                        if person and person != 'Nomalum':
                            text += f" ({person})"
                        text += "\n"
                except Exception as e:
                    logger.error(f"Error formatting debt: {e}")
                    continue
            text += "\n"
        
        return text
