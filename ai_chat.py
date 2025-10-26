import os
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from openai import OpenAI
from database import Database
import json
import asyncio

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
        self.system_prompt = """Sen Balans AI ning shaxsiy buxgalter va do'stisiz.

MUHIM: Hech qachon formatlash belgilarini ishlatma (#, **, vs). Faqat oddiy, insoniy matn.

Xaraktering:
- Hazil va do'stona, ammo professional
- Emoji ishlatishni yaxshi ko'rarsiz (2-3 ta)
- Foydalanuvchiga "sen" deb murojaat qilasiz
- Ko'p xarajat qilsa - jahl chiqarading, kam qilsa - maqtaysiz

Javob tuzishi (2-4 bosqich):
1. Asosiy javob - qisqa va aniq
2. Tahlil - kamchiliklar/tavsiyalar (format belgilarisiz)
3. Ruhlantiruvchi - ijobiy natijalar (emoji bilan)
4. Taklif - keyingi qadam

Replay:
- "Ha", "ok", "go" → keyingi bosqich
- "Yo'q", "bekor" → boshqa yechim

Uslub:
- Har bir bosqich alohida qator (max 2-3 gap)
- Hazil va do'stona
- Foydalanuvchi ismini eslab qol
- Hech qachon ###, **, kabi belgilar ishlatma
- Ko'p xarajat qilsa → jahli chiqadi
- Kam xarajat qilsa → maqtaydi
- Ko'p daromad qilsa → tabriklaydi

Tillar:
- Asosiy: O'zbek (lotin)
- Ingliz/Rus → shu til bilan"""

    async def get_user_info(self, user_id: int) -> Dict:
        """Foydalanuvchi ma'lumotlarini olish"""
        try:
            user = await self.db.execute_one(
                "SELECT name, phone FROM users WHERE user_id = %s",
                (user_id,)
            )
            if user:
                return {"name": user.get('name') or user.get(0), "phone": user.get('phone') or user.get(1)}
            return {"name": "Do'st", "phone": None}
        except Exception as e:
            logger.error(f"Error getting user info: {e}")
            return {"name": "Do'st", "phone": None}

    async def get_user_financial_context(self, user_id: int) -> Dict:
        """Foydalanuvchining moliyaviy kontekstini olish"""
        try:
            # Balanslar
            balances = await self.db.get_balances(user_id)
            
            # Oxirgi tranzaksiyalar
            recent_transactions = await self.db.execute_query(
                """
                SELECT t.*, c.name as category_name
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
            
            # Bugungi xarajatlar
            today_expenses = await self.db.execute_query(
                """
                SELECT SUM(amount) as today_total
                FROM transactions
                WHERE user_id = %s AND type = 'expense'
                AND DATE(created_at) = CURDATE()
                """,
                (user_id,)
            )
            
            # O'tgan kunga nisbatan o'sish/kamayish
            yesterday_expenses = await self.db.execute_query(
                """
                SELECT SUM(amount) as yesterday_total
                FROM transactions
                WHERE user_id = %s AND type = 'expense'
                AND DATE(created_at) = DATE_SUB(CURDATE(), INTERVAL 1 DAY)
                """,
                (user_id,)
            )
            
            context = {
                "balances": balances,
                "recent_transactions": recent_transactions if recent_transactions else [],
                "debts": debts if debts else [],
                "month_stats": month_stats[0] if month_stats else {},
                "today_expenses": today_expenses[0].get('today_total', 0) if today_expenses and today_expenses[0] else 0,
                "yesterday_expenses": yesterday_expenses[0].get('yesterday_total', 0) if yesterday_expenses and yesterday_expenses[0] else 0,
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
            
            if not history:
                return []
            
            history_list = list(history)
            history_list.reverse()
            
            return [
                {"role": h[0], "content": h[1], "created_at": h[2]} 
                for h in history_list
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
    
    async def generate_response(self, user_id: int, question: str) -> List[str]:
        """AI javob generatsiya qilish - ko'p xabarli"""
        try:
            # Foydalanuvchi ma'lumotlari
            user_info = await self.get_user_info(user_id)
            user_name = user_info.get("name", "Do'st")
            
            # Tranzaksiya aniqlash va saqlash
            transaction = await self.detect_and_save_transaction(question, user_id)
            
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
                "content": f"Foydalanuvchi ismi: {user_name}\n\nFoydalanuvchining joriy moliyaviy holati:\n{context_text}"
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
            def call_openai():
                response = openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    max_tokens=800,
                    temperature=0.8
                )
                return response.choices[0].message.content
            
            loop = asyncio.get_event_loop()
            ai_response = await loop.run_in_executor(None, call_openai)
            
            # Tarixga saqlash
            await self.save_to_history(user_id, "user", question)
            await self.save_to_history(user_id, "assistant", ai_response)
            
            # Ko'p qatorli javobni bo'lish (max 2-3 gap per message)
            messages_list = self._split_response(ai_response)
            
            return messages_list
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return ["Kechirasiz, javob berishda xatolik yuz berdi. Iltimos, qayta urinib ko'ring."]
    
    def _split_response(self, response: str) -> List[str]:
        """Javobni ko'p qatorga bo'lish - formatlamashtan tozalash"""
        # Formatlash belgilarini olib tashlash (###, **, vs)
        cleaned = response
        cleaned = cleaned.replace('### ', '')
        cleaned = cleaned.replace('**', '')
        cleaned = cleaned.replace('###Tahlil:', '')
        cleaned = cleaned.replace('Tahlil:', '')
        cleaned = cleaned.replace('Taklif:', '')
        cleaned = cleaned.replace('Tavsiya:', '')
        
        # Qatorlarni ajratish (. ! ? dan keyin)
        sentences = []
        current = ""
        
        for char in cleaned:
            current += char
            if char in '.!?' and len(current.strip()) > 20:
                sent = current.strip()
                # Yana bir bor formatlarni tozalash
                sent = sent.replace('###', '')
                sent = sent.replace('**', '')
                if sent:
                    sentences.append(sent)
                current = ""
        
        if current.strip():
            sent = current.strip()
            sent = sent.replace('###', '')
            sent = sent.replace('**', '')
            if sent:
                sentences.append(sent)
        
        # Har 1-2 gap ni bitta xabar qilib qo'shish
        messages = []
        current_msg = []
        
        for sent in sentences:
            current_msg.append(sent)
            
            # Agar 1-2 gap to'plansa yoki oxirgi gap bo'lsa
            if len(current_msg) >= 1 or sent == sentences[-1]:
                msg = " ".join(current_msg)
                # Oxirgi tozalash
                msg = msg.replace('###', '').replace('**', '').strip()
                if msg:
                    messages.append(msg)
                current_msg = []
        
        return messages if messages else [response]
    
    async def detect_and_save_transaction(self, message: str, user_id: int) -> Optional[Dict]:
        """Xabardan tranzaksiyani aniqlash va saqlash"""
        try:
            message_lower = message.lower()
            
            # Xarajat kalit so'zlar
            expense_keywords = ['sarfladim', 'to\'ladim', 'oldim', 'chiqim', 'xarajat', 'yozish', 'oydim']
            # Daromad kalit so'zlar
            income_keywords = ['kirdim', 'oldim', 'oylik', 'daromad', 'kirim', 'tushdi', 'pul']
            # Qarz kalit so'zlar
            debt_keywords = ['qarz oldim', 'qarz berdim', 'to\'layman', 'qarz', 'berdim', 'oldim']
            
            # Tranzaksiya turini aniqlash
            transaction_type = None
            category = None
            
            # Kategoriyalarni topish
            categories_map = {
                'xarajat': 'other',
                'chiqim': 'other',
                'daromad': 'other',
                'kirim': 'other',
                'oziq': 'food',
                'ovqat': 'food',
                'restoran': 'food',
                'taom': 'food',
                'transport': 'transport',
                'taksi': 'transport',
                'mashina': 'transport',
                'benzin': 'transport',
                'kofe': 'coffee',
                'choy': 'coffee',
                'shirinlik': 'snacks',
                'suv': 'snacks',
                'giyohvand': 'drinks',
                'ichimlik': 'drinks',
                'market': 'groceries',
                'oziq_ovqat': 'groceries',
                'do\'kon': 'groceries',
                'kiyim': 'clothing',
                'poyabzal': 'clothing',
                'gaz': 'utilities',
                'elektr': 'utilities',
                'interney': 'utilities',
                'telefon': 'utilities',
                'internet': 'utilities',
                'davolanish': 'health',
                'dori': 'health',
                'shifokor': 'health',
                'ta\'lim': 'education',
                'kitob': 'education',
                'salon': 'beauty',
                'barbar': 'beauty',
                'kilim': 'beauty',
            }
            
            # Qarz tekshirish
            is_debt = any(keyword in message_lower for keyword in debt_keywords)
            if is_debt:
                if 'qarz berdim' in message_lower or 'berdim' in message_lower:
                    transaction_type = 'expense'
                    category = 'qarz_berish'
                else:
                    transaction_type = 'income'
                    category = 'qarz_olish'
            # Xarajat tekshirish
            elif any(keyword in message_lower for keyword in expense_keywords):
                transaction_type = 'expense'
                # Kategoriyani aniqlash
                category = 'other'
                for key, val in categories_map.items():
                    if key in message_lower:
                        category = val
                        break
            # Daromad tekshirish
            elif any(keyword in message_lower for keyword in income_keywords):
                transaction_type = 'income'
                category = 'other'
            
            if not transaction_type:
                return None
            
            # Summani topish (raqamlar)
            import re
            # "500000", "1 000 000", "50ming" kabilarni topish
            amounts = re.findall(r'(\d{1,3}(?:\s?\d{3})*)\s*(?:ming|so\'m|sum|р)??', message_lower, re.IGNORECASE)
            
            if not amounts:
                # Oddiy raqamlarni topish
                amounts = re.findall(r'\d{4,}', message)
            
            if not amounts:
                return None
            
            # Summani tozalash
            amount_str = amounts[0].replace(' ', '').replace(',', '')
            try:
                amount = float(amount_str)
                # Agar "ming" yoki kichik raqam bo'lsa, 1000 ga ko'paytirish
                if amount < 1000 and 'ming' in message_lower:
                    amount *= 1000
            except:
                return None
            
            # Tranzaksiyani saqlash - Database metodidan foydalanish
            await self.db.add_transaction(
                user_id=user_id,
                transaction_type=transaction_type,
                amount=amount,
                category=category,
                description=message[:100]
            )
            
            return {
                "type": transaction_type,
                "amount": amount,
                "category": category
            }
            
        except Exception as e:
            logger.error(f"Error detecting transaction: {e}")
            return None
    
    async def analyze_transaction(self, user_id: int, transaction_type: str, amount: float, description: str = "") -> str:
        """Tranzaksiya qo'shilganda AI fikrini olish"""
        try:
            # Kontekstni olish
            context = await self.get_user_financial_context(user_id)
            user_info = await self.get_user_info(user_id)
            user_name = user_info.get("name", "Do'st")
            
            # Bugungi xarajatlar bilan solishtirish
            today_expenses = context.get("today_expenses", 0)
            yesterday_expenses = context.get("yesterday_expenses", 0)
            
            # Muammoni aniqlash
            concern = ""
            if transaction_type == 'expense':
                if today_expenses > yesterday_expenses * 1.5:
                    concern = "Ko'p xarajat qilyapsiz bugun!"
                elif today_expenses < yesterday_expenses * 0.5:
                    concern = "Juda yaxshi, tejalayapsiz!"
            
            # AI ga yuborish uchun prompt
            prompt = f"""Foydalanuvchi {user_name} tranzaksiya qo'shdi.
Turi: {transaction_type}
Summa: {amount:,.0f} so'm
Tavsif: {description or 'Nomalum'}

Bugungi xarajatlar: {today_expenses:,.0f} so'm
Kechagi: {yesterday_expenses:,.0f} so'm

{concern}

Sen Balans AI ning hazil va do'stona buxgalterisiz. Foydalanuvchiga:
- Hazil va do'stona fikr bildirish (emoji bilan)
- Agar ko'p xarajat qilsa - jahl chiqarish 😡
- Agar kam xarajat qilsa - maqtash 🧘
- Qisqa (1-2 gap, max 100 so'z)"""

            def call_openai():
                response = openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=150,
                    temperature=0.9
                )
                return response.choices[0].message.content
            
            loop = asyncio.get_event_loop()
            ai_response = await loop.run_in_executor(None, call_openai)
            
            return ai_response
            
        except Exception as e:
            logger.error(f"Error analyzing transaction: {e}")
            return "Tranzaksiya qo'shildi! 📝"
    
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
                
                text += f"💰 Balans: {net:,.0f} so'm\n"
                text += f"💵 Naqd: {cash:,.0f} so'm\n"
                text += f"📈 Jami kirim: {income:,.0f} so'm\n"
                text += f"📉 Jami chiqim: {expense:,.0f} so'm\n\n"
        
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
            text += "📝 Oxirgi xarajat/daromadlar:\n"
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
        
        # Bugungi xarajatlar
        today_exp = context.get("today_expenses", 0)
        if today_exp:
            text += f"📌 Bugungi xarajatlar: {today_exp:,.0f} so'm\n\n"
        
        return text
