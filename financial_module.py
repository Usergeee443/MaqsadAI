import re
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from openai import AsyncOpenAI
from config import OPENAI_API_KEY, CATEGORIES
from database import db
from models import Transaction, TransactionType

class FinancialModule:
    def __init__(self):
        self.openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        
    async def process_ai_input(self, text: str, user_id: int) -> Dict[str, Any]:
        """AI yordamida moliyaviy ma'lumotni qayta ishlash"""
        try:
            # OpenAI API orqali matnni tahlil qilish
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": """Siz moliyaviy yordamchi AI siz. Foydalanuvchi yuborgan matndan quyidagi ma'lumotlarni ajratib oling:

1. Summa (raqam) - faqat raqam
2. Tranzaksiya turi - "income" (kirim), "expense" (chiqim), "debt" (qarz)
3. Kategoriya - "ovqat", "transport", "ish haqi", "biznes", "investitsiya", "kiyim", "uy", "sog'liq", "ta'lim", "o'yin-kulgi", "boshqa"
4. Tafsilot - qisqa tavsif

Faqat JSON formatda javob bering, boshqa matn yozmang:
{
    "amount": 50000,
    "type": "expense",
    "category": "ovqat",
    "description": "tushlik uchun"
}

Agar moliyaviy ma'lumot bo'lmasa, null qaytaring."""
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ],
                temperature=0.3
            )
            
            # JSON javobni parse qilish
            ai_response = response.choices[0].message.content
            if not ai_response:
                return {
                    "success": False,
                    "message": "❌ AI javob bermadi. Iltimos, qaytadan urinib ko'ring."
                }
            
            import json
            try:
                data = json.loads(ai_response)
            except json.JSONDecodeError:
                return {
                    "success": False,
                    "message": "❌ AI javobini tushunib bo'lmadi. Iltimos, aniqroq yozing."
                }
            
            # Agar moliyaviy ma'lumot bo'lmasa
            if not data or data.get('amount') is None:
                return {
                    "success": False,
                    "message": "❌ Bu moliyaviy ma'lumot emas. Iltimos, kirim/chiqim haqida yozing."
                }
            
            # Ma'lumotni saqlash
            transaction_id = await self.save_transaction(
                user_id=user_id,
                amount=float(data.get('amount', 0)),
                category=data.get('category', 'boshqa'),
                description=data.get('description', ''),
                transaction_type=TransactionType(data.get('type', 'expense'))
            )
            
            return {
                "success": True,
                "transaction_id": transaction_id,
                "message": f"✅ Ma'lumot saqlandi!\n"
                          f"💰 Summa: {data['amount']:,} so'm\n"
                          f"📂 Kategoriya: {data['category']}\n"
                          f"📝 Tafsilot: {data.get('description', 'Mavjud emas')}"
            }
            
        except Exception as e:
            logging.error(f"AI qayta ishlashda xatolik: {e}")
            return {
                "success": False,
                "message": "❌ Ma'lumotni qayta ishlashda xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring."
            }
    
    async def save_transaction(self, user_id: int, amount: float, category: str, 
                             description: str, transaction_type: TransactionType) -> int:
        """Tranzaksiyani ma'lumotlar bazasiga saqlash"""
        try:
            query = """
            INSERT INTO transactions (user_id, amount, category, description, transaction_type, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            """
            transaction_id = await db.execute_insert(query, (
                user_id, amount, category, description, transaction_type.value
            ))
            return transaction_id
        except Exception as e:
            logging.error(f"Tranzaksiya saqlashda xatolik: {e}")
            return None
    
    async def get_user_balance(self, user_id: int) -> Dict[str, float]:
        """Foydalanuvchi balansini hisoblash"""
        try:
            # Kirimlar
            income_query = """
            SELECT COALESCE(SUM(amount), 0) FROM transactions 
            WHERE user_id = %s AND transaction_type = 'income'
            """
            income_result = await db.execute_one(income_query, (user_id,))
            total_income = income_result[0] if income_result else 0.0
            
            # Chiqimlar
            expense_query = """
            SELECT COALESCE(SUM(amount), 0) FROM transactions 
            WHERE user_id = %s AND transaction_type = 'expense'
            """
            expense_result = await db.execute_one(expense_query, (user_id,))
            total_expense = expense_result[0] if expense_result else 0.0
            
            # Qarzlar
            debt_query = """
            SELECT COALESCE(SUM(amount), 0) FROM transactions 
            WHERE user_id = %s AND transaction_type = 'debt'
            """
            debt_result = await db.execute_one(debt_query, (user_id,))
            total_debt = debt_result[0] if debt_result else 0.0
            
            balance = total_income - total_expense
            
            return {
                "income": total_income,
                "expense": total_expense,
                "debt": total_debt,
                "balance": balance
            }
        except Exception as e:
            logging.error(f"Balans hisoblashda xatolik: {e}")
            return {"income": 0.0, "expense": 0.0, "debt": 0.0, "balance": 0.0}
    
    async def get_category_expenses(self, user_id: int, days: int = 30) -> Dict[str, float]:
        """Kategoriyalar bo'yicha chiqimlarni olish"""
        try:
            query = """
            SELECT category, SUM(amount) as total
            FROM transactions 
            WHERE user_id = %s AND transaction_type = 'expense' 
            AND created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY category
            ORDER BY total DESC
            """
            results = await db.execute_query(query, (user_id, days))
            
            categories = {}
            for row in results:
                categories[row[0]] = float(row[1])
            
            return categories
        except Exception as e:
            logging.error(f"Kategoriya chiqimlarini olishda xatolik: {e}")
            return {}
    
    async def get_recent_transactions(self, user_id: int, limit: int = 10) -> list:
        """So'nggi tranzaksiyalarni olish"""
        try:
            query = """
            SELECT amount, category, description, transaction_type, created_at
            FROM transactions 
            WHERE user_id = %s 
            ORDER BY created_at DESC 
            LIMIT %s
            """
            results = await db.execute_query(query, (user_id, limit))
            
            transactions = []
            for row in results:
                transactions.append({
                    "amount": float(row[0]),
                    "category": row[1],
                    "description": row[2] or "Mavjud emas",
                    "type": row[3],
                    "date": row[4].strftime("%d.%m.%Y %H:%M")
                })
            
            return transactions
        except Exception as e:
            logging.error(f"So'nggi tranzaksiyalarni olishda xatolik: {e}")
            return []
    
    def format_balance_message(self, balance_data: Dict[str, float]) -> str:
        """Balans ma'lumotini formatlash"""
        message = f"""💰 *Balans hisoboti*

📈 *Jami kirim:* {balance_data['income']:,.0f} so'm
📉 *Jami chiqim:* {balance_data['expense']:,.0f} so'm
💳 *Qarzlar:* {balance_data['debt']:,.0f} so'm

💵 *Balans:* {balance_data['balance']:,.0f} so'm
"""
        return message
    
    def format_transactions_message(self, transactions: list) -> str:
        """Tranzaksiyalar ro'yxatini formatlash"""
        if not transactions:
            return "📋 Hozircha tranzaksiyalar mavjud emas."
        
        message = "📋 *So'nggi tranzaksiyalar*\n\n"
        
        for i, trans in enumerate(transactions, 1):
            type_emoji = {
                "income": "📈",
                "expense": "📉", 
                "debt": "💳"
            }.get(trans["type"], "❓")
            
            message += f"{i}. {type_emoji} {trans['amount']:,.0f} so'm\n"
            message += f"   📂 {trans['category']}\n"
            message += f"   📝 {trans['description']}\n"
            message += f"   📅 {trans['date']}\n\n"
        
        return message
