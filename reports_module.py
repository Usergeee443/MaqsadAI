import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from database import db

class ReportsModule:
    def __init__(self):
        pass
    
    async def get_balance_report(self, user_id: int) -> Dict[str, Any]:
        """Balans hisoboti"""
        try:
            # Jami kirim
            income_query = """
            SELECT COALESCE(SUM(amount), 0) FROM transactions 
            WHERE user_id = %s AND transaction_type = 'income'
            """
            income_result = await db.execute_one(income_query, (user_id,))
            total_income = float(income_result[0]) if income_result else 0.0
            
            # Jami chiqim
            expense_query = """
            SELECT COALESCE(SUM(amount), 0) FROM transactions 
            WHERE user_id = %s AND transaction_type = 'expense'
            """
            expense_result = await db.execute_one(expense_query, (user_id,))
            total_expense = float(expense_result[0]) if expense_result else 0.0
            
            # Jami qarz
            debt_query = """
            SELECT COALESCE(SUM(amount), 0) FROM transactions 
            WHERE user_id = %s AND transaction_type = 'debt'
            """
            debt_result = await db.execute_one(debt_query, (user_id,))
            total_debt = float(debt_result[0]) if debt_result else 0.0
            
            balance = total_income - total_expense
            
            return {
                "income": total_income,
                "expense": total_expense,
                "debt": total_debt,
                "balance": balance
            }
        except Exception as e:
            logging.error(f"Balans hisobotini olishda xatolik: {e}")
            return {"income": 0.0, "expense": 0.0, "debt": 0.0, "balance": 0.0}
    
    async def get_category_report(self, user_id: int, days: int = 30) -> Dict[str, Any]:
        """Kategoriyalar bo'yicha hisobot"""
        try:
            # Chiqimlar kategoriyalar bo'yicha
            expense_query = """
            SELECT category, SUM(amount) as total, COUNT(*) as count
            FROM transactions 
            WHERE user_id = %s AND transaction_type = 'expense' 
            AND created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY category
            ORDER BY total DESC
            """
            expense_results = await db.execute_query(expense_query, (user_id, days))
            
            # Kirimlar kategoriyalar bo'yicha
            income_query = """
            SELECT category, SUM(amount) as total, COUNT(*) as count
            FROM transactions 
            WHERE user_id = %s AND transaction_type = 'income' 
            AND created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY category
            ORDER BY total DESC
            """
            income_results = await db.execute_query(income_query, (user_id, days))
            
            expense_categories = {}
            for row in expense_results:
                expense_categories[row[0]] = {
                    "total": float(row[1]),
                    "count": row[2]
                }
            
            income_categories = {}
            for row in income_results:
                income_categories[row[0]] = {
                    "total": float(row[1]),
                    "count": row[2]
                }
            
            return {
                "expense_categories": expense_categories,
                "income_categories": income_categories,
                "period_days": days
            }
        except Exception as e:
            logging.error(f"Kategoriya hisobotini olishda xatolik: {e}")
            return {"expense_categories": {}, "income_categories": {}, "period_days": days}
    
    async def get_time_period_report(self, user_id: int, period: str) -> Dict[str, Any]:
        """Vaqt bo'yicha hisobot"""
        try:
            if period == "daily":
                # Kunlik hisobot
                query = """
                SELECT DATE(created_at) as date, 
                       SUM(CASE WHEN transaction_type = 'income' THEN amount ELSE 0 END) as income,
                       SUM(CASE WHEN transaction_type = 'expense' THEN amount ELSE 0 END) as expense
                FROM transactions 
                WHERE user_id = %s AND created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                GROUP BY DATE(created_at)
                ORDER BY date DESC
                """
            elif period == "weekly":
                # Haftalik hisobot
                query = """
                SELECT YEARWEEK(created_at) as week, 
                       SUM(CASE WHEN transaction_type = 'income' THEN amount ELSE 0 END) as income,
                       SUM(CASE WHEN transaction_type = 'expense' THEN amount ELSE 0 END) as expense
                FROM transactions 
                WHERE user_id = %s AND created_at >= DATE_SUB(NOW(), INTERVAL 12 WEEK)
                GROUP BY YEARWEEK(created_at)
                ORDER BY week DESC
                """
            elif period == "monthly":
                # Oylik hisobot
                query = """
                SELECT DATE_FORMAT(created_at, '%Y-%m') as month, 
                       SUM(CASE WHEN transaction_type = 'income' THEN amount ELSE 0 END) as income,
                       SUM(CASE WHEN transaction_type = 'expense' THEN amount ELSE 0 END) as expense
                FROM transactions 
                WHERE user_id = %s AND created_at >= DATE_SUB(NOW(), INTERVAL 12 MONTH)
                GROUP BY DATE_FORMAT(created_at, '%Y-%m')
                ORDER BY month DESC
                """
            else:
                return {"data": [], "period": period}
            
            results = await db.execute_query(query, (user_id,))
            
            data = []
            for row in results:
                data.append({
                    "period": str(row[0]),
                    "income": float(row[1]),
                    "expense": float(row[2]),
                    "balance": float(row[1]) - float(row[2])
                })
            
            return {
                "data": data,
                "period": period
            }
        except Exception as e:
            logging.error(f"Vaqt bo'yicha hisobotni olishda xatolik: {e}")
            return {"data": [], "period": period}
    
    async def get_recent_transactions(self, user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        """So'nggi tranzaksiyalar"""
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
    
    def format_balance_report(self, balance_data: Dict[str, Any]) -> str:
        """Balans hisobotini formatlash"""
        message = f"""💰 *Balans hisoboti*

📈 *Jami kirim:* {balance_data['income']:,.0f} so'm
📉 *Jami chiqim:* {balance_data['expense']:,.0f} so'm
💳 *Jami qarz:* {balance_data['debt']:,.0f} so'm

💵 *Balans:* {balance_data['balance']:,.0f} so'm

"""
        if balance_data['balance'] > 0:
            message += "✅ Sizda ijobiy balans bor!"
        elif balance_data['balance'] < 0:
            message += "⚠️ Sizda salbiy balans bor. Chiqimlarni kamaytiring."
        else:
            message += "⚖️ Balans nolga teng."
        
        return message
    
    def format_category_report(self, category_data: Dict[str, Any]) -> str:
        """Kategoriya hisobotini formatlash"""
        message = f"📊 *Kategoriyalar bo'yicha hisobot* ({category_data['period_days']} kun)\n\n"
        
        # Chiqimlar
        if category_data['expense_categories']:
            message += "📉 *Chiqimlar:*\n"
            for category, data in category_data['expense_categories'].items():
                message += f"• {category}: {data['total']:,.0f} so'm ({data['count']} ta)\n"
            message += "\n"
        
        # Kirimlar
        if category_data['income_categories']:
            message += "📈 *Kirimlar:*\n"
            for category, data in category_data['income_categories'].items():
                message += f"• {category}: {data['total']:,.0f} so'm ({data['count']} ta)\n"
        
        return message
    
    def format_time_period_report(self, time_data: Dict[str, Any]) -> str:
        """Vaqt bo'yicha hisobotni formatlash"""
        period_names = {
            "daily": "Kunlik",
            "weekly": "Haftalik", 
            "monthly": "Oylik"
        }
        
        message = f"📅 *{period_names.get(time_data['period'], 'Vaqt')} hisobot*\n\n"
        
        if not time_data['data']:
            message += "📋 Ma'lumot mavjud emas."
            return message
        
        for item in time_data['data'][:10]:  # Faqat oxirgi 10 ta
            balance_emoji = "✅" if item['balance'] > 0 else "❌" if item['balance'] < 0 else "⚖️"
            message += f"{balance_emoji} *{item['period']}*\n"
            message += f"   📈 Kirim: {item['income']:,.0f} so'm\n"
            message += f"   📉 Chiqim: {item['expense']:,.0f} so'm\n"
            message += f"   💰 Balans: {item['balance']:,.0f} so'm\n\n"
        
        return message
    
    def format_transactions_report(self, transactions: List[Dict[str, Any]]) -> str:
        """Tranzaksiyalar hisobotini formatlash"""
        if not transactions:
            return "📋 Hozircha tranzaksiyalar mavjud emas."
        
        message = "📋 *So'nggi tranzaksiyalar*\n\n"
        
        for i, trans in enumerate(transactions, 1):
            type_emoji = {
                "income": "📈",
                "expense": "📉",
                "debt": "💳"
            }.get(trans["type"], "❓")
            
            message += f"{i}. {type_emoji} *{trans['amount']:,.0f} so'm*\n"
            message += f"   📂 {trans['category']}\n"
            message += f"   📝 {trans['description']}\n"
            message += f"   📅 {trans['date']}\n\n"
        
        return message
    
    async def get_financial_summary(self, user_id: int) -> str:
        """Moliyaviy xulosa"""
        try:
            # Balans ma'lumotlari
            balance = await self.get_balance_report(user_id)
            
            # Kategoriya ma'lumotlari
            categories = await self.get_category_report(user_id, 30)
            
            # So'nggi tranzaksiyalar
            recent = await self.get_recent_transactions(user_id, 5)
            
            message = "📊 *Moliyaviy xulosa*\n\n"
            
            # Balans
            message += f"💰 *Balans:* {balance['balance']:,.0f} so'm\n"
            message += f"📈 *Kirim:* {balance['income']:,.0f} so'm\n"
            message += f"📉 *Chiqim:* {balance['expense']:,.0f} so'm\n\n"
            
            # Eng ko'p chiqim kategoriyasi
            if categories['expense_categories']:
                top_category = max(categories['expense_categories'].items(), key=lambda x: x[1]['total'])
                message += f"🔥 *Eng ko'p chiqim:* {top_category[0]} ({top_category[1]['total']:,.0f} so'm)\n\n"
            
            # So'nggi tranzaksiyalar
            if recent:
                message += "📋 *So'nggi tranzaksiyalar:*\n"
                for trans in recent[:3]:
                    type_emoji = {"income": "📈", "expense": "📉", "debt": "💳"}.get(trans["type"], "❓")
                    message += f"• {type_emoji} {trans['amount']:,.0f} so'm - {trans['category']}\n"
            
            return message
        except Exception as e:
            logging.error(f"Moliyaviy xulosa yaratishda xatolik: {e}")
            return "❌ Moliyaviy xulosa yaratishda xatolik yuz berdi."
