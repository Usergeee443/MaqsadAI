"""
BALANS AI BIZNES — AI-powered Voice & Text Mini CRM
Foydalanuvchi faqat yozish yoki gapirish orqali biznesini boshqaradi
AI esa nima ekanini tushunib, to'g'ri modulga saqlaydi
"""
import logging
import json
import re
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from aiogram import types
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, CallbackQuery
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

logger = logging.getLogger(__name__)

# Business states
class BusinessStates(StatesGroup):
    # AI Chat rejimi
    ai_chat_mode = State()
    
    # Xodim qo'shish
    waiting_for_employee_telegram_id = State()
    waiting_for_employee_name = State()
    waiting_for_employee_role = State()
    
    # Tovar qo'shish (agar kerak bo'lsa)
    waiting_for_product_name = State()
    waiting_for_product_category = State()
    waiting_for_product_price = State()
    waiting_for_product_quantity = State()
    waiting_for_product_min_quantity = State()


class BusinessAIParser:
    """
    AI yordamida foydalanuvchi xabarlarini tahlil qilish.
    Kirim/Chiqim, Qarz, Ombor operatsiyalarini avtomatik aniqlash.
    """
    
    # Kategoriyalar
    EXPENSE_CATEGORIES = {
        'ijara': ['ijara', 'arenda', 'kvartira', 'ofis ijara'],
        'kommunal': ['elektr', 'gaz', 'suv', 'kommunal', 'tok', 'svet'],
        'ish_haqi': ['ish haqi', 'maosh', 'oylik', 'zarplata', 'ishchi'],
        'transport': ['benzin', 'mashina', 'yoqilg\'i', 'taxi', 'transport'],
        'tovar': ['tovar', 'mahsulot', 'zakupka', 'optom'],
        'reklama': ['reklama', 'marketing', 'targetting', 'ads'],
        'boshqa': []
    }
    
    INCOME_CATEGORIES = {
        'savdo': ['savdo', 'sotish', 'sotuv', 'kassa', 'tushum'],
        'xizmat': ['xizmat', 'service', 'buyurtma'],
        'qaytim': ['qaytim', 'vozvrat', 'qaytarildi'],
        'boshqa': []
    }
    
    # Qarz kalit so'zlari
    DEBT_KEYWORDS = {
        'given': ['qarz berdim', 'qarz beraman', 'beruvdim', 'oldim', 'olib ketdi', 'uzatdim'],
        'received': ['qarz oldim', 'qarz', 'qarzdor', 'qarzim bor', 'berishim kerak'],
        'returned': ['qaytardi', 'to\'ladi', 'berdi', 'uzdi', 'yopdi', 'qaytardim', 'to\'ladim']
    }
    
    # Ombor kalit so'zlari  
    WAREHOUSE_KEYWORDS = {
        'in': ['keldi', 'qo\'sh', 'qo\'shish', 'kirim', 'olib keldim', 'oldi', 'qop', 'kg keldi'],
        'out': ['sotildi', 'chiqdi', 'ketdi', 'berildi', 'brak', 'yaroqsiz', 'yo\'qotish', 'chiqim']
    }
    
    def __init__(self, openai_client, db):
        self.openai_client = openai_client
        self.db = db
    
    async def parse_business_message(self, user_id: int, message: str) -> Dict:
        """
        Foydalanuvchi xabarini tahlil qilish va operatsiya turini aniqlash.
        Returns: {
            'type': 'income' | 'expense' | 'debt' | 'warehouse' | 'question' | 'unknown',
            'data': {...},
            'confidence': float
        }
        """
        try:
            # AI orqali tahlil qilish
            system_prompt = """Sen biznes xabarlarini tahlil qiluvchi AI assistentsan.
Foydalanuvchi xabarini tahlil qilib, quyidagi formatda JSON javob ber:

{
    "type": "income" | "expense" | "debt" | "warehouse" | "question" | "unknown",
    "amount": number (agar pul bor bo'lsa),
    "currency": "UZS" | "USD",
    "category": string,
    "description": string,
    "person_name": string (agar qarz bo'lsa),
    "debt_type": "given" | "received" | "returned" (agar qarz bo'lsa),
    "product_name": string (agar ombor bo'lsa),
    "quantity": number (agar ombor bo'lsa),
    "unit": string (kg, dona, qop, litr va h.k.),
    "warehouse_type": "in" | "out" (agar ombor bo'lsa),
    "warehouse_reason": "purchase" | "sale" | "loss" | "defect" (agar chiqim bo'lsa),
    "date": "YYYY-MM-DD" (agar sana bor bo'lsa, bo'lmasa bugun),
    "confidence": 0.0-1.0
}

QOIDALAR:
1. "savdo", "tushum", "daromad", "mijozdan oldim" = income
2. "to'ladim", "xarajat", "chiqim", "berdim" (pul kontekstida) = expense
3. "qarz berdim", "qarz oldim", "qaytardi" = debt
4. "omborga", "sotildi", "keldi" (tovar kontekstida) = warehouse
5. "qancha?", "nima?", "tahlil" = question
6. Summalar: "1.2 mln" = 1200000, "500 ming" = 500000, "2m" = 2000000

O'zbek va rus tillarini tushun. Faqat JSON qaytar, boshqa hech narsa yo'q."""

            user_prompt = f"Xabar: {message}"
            
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=500,
                temperature=0.1
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # JSON parse
            if result_text.startswith("```"):
                result_text = re.sub(r'^```json?\s*', '', result_text)
                result_text = re.sub(r'\s*```$', '', result_text)
            
            result = json.loads(result_text)
            logger.info(f"Business AI parsed: {result}")
            
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}, text: {result_text}")
            return {'type': 'unknown', 'confidence': 0}
        except Exception as e:
            logger.error(f"Business message parse error: {e}")
            return {'type': 'unknown', 'confidence': 0}
    
    async def process_income(self, user_id: int, data: Dict) -> Dict:
        """Kirim qayta ishlash"""
        try:
            amount = data.get('amount', 0)
            category = data.get('category', 'savdo')
            description = data.get('description', '')
            date_str = data.get('date', datetime.now().strftime('%Y-%m-%d'))
            
            # Tranzaksiya saqlash
            transaction_id = await self.db.execute_query(
                """INSERT INTO transactions 
                (user_id, amount, transaction_type, category, description, created_at) 
                VALUES (%s, %s, 'income', %s, %s, %s)""",
                (user_id, amount, category, description, date_str)
            )
            
            return {
                'success': True,
                'type': 'income',
                'message': f"✅ **Kirim saqlandi!**\n\n"
                          f"💰 Summa: **{amount:,.0f}** so'm\n"
                          f"📂 Kategoriya: {category}\n"
                          f"📝 Izoh: {description}\n"
                          f"📅 Sana: {date_str}"
            }
        except Exception as e:
            logger.error(f"Income save error: {e}")
            return {'success': False, 'message': f"❌ Xatolik: {str(e)}"}
    
    async def process_expense(self, user_id: int, data: Dict) -> Dict:
        """Chiqim qayta ishlash"""
        try:
            amount = data.get('amount', 0)
            category = data.get('category', 'boshqa')
            description = data.get('description', '')
            date_str = data.get('date', datetime.now().strftime('%Y-%m-%d'))
            
            # Tranzaksiya saqlash
            await self.db.execute_query(
                """INSERT INTO transactions 
                (user_id, amount, transaction_type, category, description, created_at) 
                VALUES (%s, %s, 'expense', %s, %s, %s)""",
                (user_id, amount, category, description, date_str)
            )
            
            return {
                'success': True,
                'type': 'expense',
                'message': f"✅ **Chiqim saqlandi!**\n\n"
                          f"💸 Summa: **{amount:,.0f}** so'm\n"
                          f"📂 Kategoriya: {category}\n"
                          f"📝 Izoh: {description}\n"
                          f"📅 Sana: {date_str}"
            }
        except Exception as e:
            logger.error(f"Expense save error: {e}")
            return {'success': False, 'message': f"❌ Xatolik: {str(e)}"}
    
    async def process_debt(self, user_id: int, data: Dict) -> Dict:
        """Qarz qayta ishlash"""
        try:
            amount = data.get('amount', 0)
            person_name = data.get('person_name', 'Noma\'lum')
            debt_type = data.get('debt_type', 'given')  # given, received, returned
            description = data.get('description', '')
            date_str = data.get('date', datetime.now().strftime('%Y-%m-%d'))
            
            if debt_type == 'returned':
                # Qarz qaytarildi - mavjud qarzni yangilash
                # Avval o'sha odamning qarzini topish
                existing_debt = await self.db.execute_query(
                    """SELECT id, amount, paid_amount FROM debts 
                    WHERE user_id = %s AND person_name = %s AND status = 'active'
                    ORDER BY created_at DESC LIMIT 1""",
                    (user_id, person_name)
                )
                
                if existing_debt:
                    debt = existing_debt[0]
                    new_paid = (debt.get('paid_amount') or 0) + amount
                    new_status = 'paid' if new_paid >= debt['amount'] else 'active'
                    
                    await self.db.execute_query(
                        """UPDATE debts SET paid_amount = %s, status = %s, updated_at = NOW() 
                        WHERE id = %s""",
                        (new_paid, new_status, debt['id'])
                    )
                    
                    remaining = debt['amount'] - new_paid
                    return {
                        'success': True,
                        'type': 'debt_payment',
                        'message': f"✅ **Qarz to'lovi saqlandi!**\n\n"
                                  f"👤 {person_name}\n"
                                  f"💰 To'landi: **{amount:,.0f}** so'm\n"
                                  f"📊 Qoldiq: **{max(0, remaining):,.0f}** so'm\n"
                                  f"📅 Sana: {date_str}"
                    }
                else:
                    return {
                        'success': False,
                        'message': f"❌ {person_name} nomida aktiv qarz topilmadi"
                    }
            else:
                # Yangi qarz yaratish
                debt_direction = 'lent' if debt_type == 'given' else 'borrowed'
                
                await self.db.execute_query(
                    """INSERT INTO debts 
                    (user_id, person_name, amount, debt_type, status, created_at) 
                    VALUES (%s, %s, %s, %s, 'active', %s)""",
                    (user_id, person_name, amount, debt_direction, date_str)
                )
                
                debt_text = "berildi" if debt_type == 'given' else "olindi"
                return {
                    'success': True,
                    'type': 'debt',
                    'message': f"✅ **Qarz saqlandi!**\n\n"
                              f"👤 {person_name}\n"
                              f"💰 Summa: **{amount:,.0f}** so'm\n"
                              f"📝 Turi: Qarz {debt_text}\n"
                              f"📅 Sana: {date_str}"
                }
                
        except Exception as e:
            logger.error(f"Debt save error: {e}")
            return {'success': False, 'message': f"❌ Xatolik: {str(e)}"}
    
    async def process_warehouse(self, user_id: int, data: Dict) -> Dict:
        """Ombor operatsiyasi qayta ishlash"""
        try:
            product_name = data.get('product_name', '')
            quantity = data.get('quantity', 0)
            unit = data.get('unit', 'dona')
            warehouse_type = data.get('warehouse_type', 'in')  # in, out
            reason = data.get('warehouse_reason', 'purchase' if warehouse_type == 'in' else 'sale')
            
            if not product_name:
                return {'success': False, 'message': "❌ Tovar nomi ko'rsatilmagan"}
            
            # Mavjud tovarni topish yoki yangi yaratish
            existing_product = await self.db.execute_query(
                """SELECT id, quantity FROM warehouse_products 
                WHERE user_id = %s AND LOWER(name) = LOWER(%s) LIMIT 1""",
                (user_id, product_name)
            )
            
            product_id = None
            new_qty = 0
            
            if existing_product and len(existing_product) > 0 and isinstance(existing_product[0], dict):
                product = existing_product[0]
                product_id = product.get('id')
                current_qty = product.get('quantity', 0) or 0
                
                if warehouse_type == 'in':
                    new_qty = current_qty + quantity
                else:
                    new_qty = max(0, current_qty - quantity)
                
                # Qoldiqni yangilash
                await self.db.execute_query(
                    "UPDATE warehouse_products SET quantity = %s, updated_at = NOW() WHERE id = %s",
                    (new_qty, product_id)
                )
            else:
                # Yangi tovar yaratish
                if warehouse_type == 'in':
                    new_qty = quantity
                else:
                    new_qty = 0
                
                await self.db.execute_query(
                    """INSERT INTO warehouse_products (user_id, name, quantity, unit, created_at) 
                    VALUES (%s, %s, %s, %s, NOW())""",
                    (user_id, product_name, new_qty, unit)
                )
                
                # Yangi qo'shilgan tovarning ID sini olish
                new_product = await self.db.execute_query(
                    "SELECT id FROM warehouse_products WHERE user_id = %s AND name = %s ORDER BY id DESC LIMIT 1",
                    (user_id, product_name)
                )
                if new_product and len(new_product) > 0 and isinstance(new_product[0], dict):
                    product_id = new_product[0].get('id')
            
            # Harakat yozish (agar product_id bor bo'lsa)
            if product_id:
                await self.db.execute_query(
                    """INSERT INTO warehouse_movements 
                    (user_id, product_id, movement_type, quantity, reason, created_at) 
                    VALUES (%s, %s, %s, %s, %s, NOW())""",
                    (user_id, product_id, warehouse_type, quantity, reason)
                )
            
            action_text = "Kirim" if warehouse_type == 'in' else "Chiqim"
            reason_text = {
                'purchase': 'Sotib olish',
                'sale': 'Sotuv',
                'loss': 'Yo\'qotish',
                'defect': 'Brak'
            }.get(reason, reason)
            
            return {
                'success': True,
                'type': 'warehouse',
                'message': f"✅ **Ombor yangilandi!**\n\n"
                          f"📦 Tovar: **{product_name}**\n"
                          f"🔄 Amal: {action_text}\n"
                          f"🔢 Miqdor: {quantity} {unit}\n"
                          f"📝 Sabab: {reason_text}\n"
                          f"📊 Yangi qoldiq: **{new_qty}** {unit}"
            }
            
        except Exception as e:
            logger.error(f"Warehouse save error: {e}")
            return {'success': False, 'message': f"❌ Xatolik: {str(e)}"}


class BusinessModule:
    """Biznes tarif uchun asosiy modul"""
    
    def __init__(self, db, ai_chat):
        self.db = db
        self.ai_chat = ai_chat
        self.parser = None  # OpenAI client keyin o'rnatiladi
    
    def set_openai_client(self, openai_client):
        """OpenAI client o'rnatish"""
        self.parser = BusinessAIParser(openai_client, self.db)
    
    # ================== MENYULAR ==================
    
    @staticmethod
    def get_business_menu() -> ReplyKeyboardMarkup:
        """Business asosiy menyusi - faqat 3 ta tugma + AI Chat"""
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📊 Hisobotlar"), KeyboardButton(text="📦 Ombor")],
                [KeyboardButton(text="🤖 AI Chat"), KeyboardButton(text="👤 Profil")]
            ],
            resize_keyboard=True,
            one_time_keyboard=False
        )
    
    @staticmethod
    def get_ai_chat_menu() -> ReplyKeyboardMarkup:
        """AI Chat rejimidagi menyu"""
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🛑 AI Chatni to'xtatish")]
            ],
            resize_keyboard=True,
            one_time_keyboard=False
        )
    
    @staticmethod
    def get_warehouse_menu() -> InlineKeyboardMarkup:
        """Ombor menyusi"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📦 Tovarlar ro'yxati", callback_data="biz_warehouse_products")],
            [InlineKeyboardButton(text="📊 Ombor statistikasi", callback_data="biz_warehouse_stats")],
            [InlineKeyboardButton(text="⚠️ Kam qolgan tovarlar", callback_data="biz_warehouse_low")],
            [InlineKeyboardButton(text="🤖 AI Ombor tahlili", callback_data="biz_warehouse_ai")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="biz_main")]
        ])
    
    @staticmethod
    def get_reports_menu() -> InlineKeyboardMarkup:
        """Hisobotlar menyusi"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📅 Kunlik hisobot", callback_data="biz_report_daily")],
            [InlineKeyboardButton(text="📆 Haftalik hisobot", callback_data="biz_report_weekly")],
            [InlineKeyboardButton(text="🗓 Oylik hisobot", callback_data="biz_report_monthly")],
            [InlineKeyboardButton(text="💰 Qarzlar holati", callback_data="biz_report_debts")],
            [InlineKeyboardButton(text="🤖 AI Tahlil", callback_data="biz_report_ai")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="biz_main")]
        ])
    
    @staticmethod
    def get_profile_menu() -> InlineKeyboardMarkup:
        """Profil menyusi"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏢 Biznes ma'lumotlari", callback_data="biz_profile_info")],
            [InlineKeyboardButton(text="👥 Xodimlar", callback_data="biz_profile_employees")],
            [InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data="biz_profile_settings")],
            [InlineKeyboardButton(text="📤 Ma'lumotlarni eksport", callback_data="biz_profile_export")],
            [InlineKeyboardButton(text="💬 Yordam", callback_data="biz_profile_help")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="biz_main")]
        ])
    
    @staticmethod
    def get_employees_menu() -> InlineKeyboardMarkup:
        """Xodimlar menyusi"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Xodimlar ro'yxati", callback_data="biz_emp_list")],
            [InlineKeyboardButton(text="➕ Xodim qo'shish", callback_data="biz_emp_add")],
            [InlineKeyboardButton(text="📋 Vazifalar", callback_data="biz_emp_tasks")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="biz_profile_employees")]
        ])
    
    # ================== XABAR QAYTA ISHLASH ==================
    
    async def process_business_message(self, user_id: int, message: str, is_employee: bool = False) -> Dict:
        """
        Biznes xabarini qayta ishlash.
        AI avtomatik operatsiya turini aniqlaydi va saqlaydi.
        """
        if not self.parser:
            return {
                'success': False,
                'message': "❌ AI parser sozlanmagan"
            }
        
        try:
            # AI orqali tahlil
            parsed = await self.parser.parse_business_message(user_id, message)
            
            msg_type = parsed.get('type', 'unknown')
            confidence = parsed.get('confidence', 0)
            
            # Kam ishonch bo'lsa
            if confidence < 0.5 and msg_type != 'question':
                return {
                    'success': False,
                    'type': 'low_confidence',
                    'message': "🤔 Tushunmadim. Iltimos, aniqroq yozing.\n\n"
                              "**Misollar:**\n"
                              "💰 Kirim: \"Bugun 1.2 mln savdo bo'ldi\"\n"
                              "💸 Chiqim: \"Elektrga 350 ming to'ladim\"\n"
                              "📝 Qarz: \"Aliga 500 ming qarz berdim\"\n"
                              "📦 Ombor: \"10 ta yog' sotildi\""
                }
            
            # Operatsiya turiga qarab qayta ishlash
            if msg_type == 'income':
                return await self.parser.process_income(user_id, parsed)
            
            elif msg_type == 'expense':
                return await self.parser.process_expense(user_id, parsed)
            
            elif msg_type == 'debt':
                return await self.parser.process_debt(user_id, parsed)
            
            elif msg_type == 'warehouse':
                return await self.parser.process_warehouse(user_id, parsed)
            
            elif msg_type == 'question':
                # Savol - AI Chat ga yo'naltirish
                return {
                    'success': True,
                    'type': 'question',
                    'question': message,
                    'message': None  # AI Chat javob beradi
                }
            
            else:
                return {
                    'success': False,
                    'type': 'unknown',
                    'message': "🤔 Tushunmadim. Iltimos, aniqroq yozing.\n\n"
                              "💡 **Yordam:** \"Bu oy foydam qancha?\" yoki \"Omborda nima bor?\""
                }
                
        except Exception as e:
            logger.error(f"Business message process error: {e}")
            return {
                'success': False,
                'message': f"❌ Xatolik: {str(e)}"
            }
    
    # ================== HISOBOTLAR ==================
    
    async def get_daily_report(self, user_id: int, date: datetime = None) -> str:
        """Kunlik hisobot"""
        if not date:
            date = datetime.now()
        
        date_str = date.strftime('%Y-%m-%d')
        
        try:
            # Kirimlar
            income_result = await self.db.execute_query(
                """SELECT COALESCE(SUM(amount), 0) as total FROM transactions 
                WHERE user_id = %s AND transaction_type = 'income' AND DATE(created_at) = %s""",
                (user_id, date_str)
            )
            total_income = income_result[0]['total'] if income_result and isinstance(income_result[0], dict) else 0
            
            # Chiqimlar
            expense_result = await self.db.execute_query(
                """SELECT COALESCE(SUM(amount), 0) as total FROM transactions 
                WHERE user_id = %s AND transaction_type = 'expense' AND DATE(created_at) = %s""",
                (user_id, date_str)
            )
            total_expense = expense_result[0]['total'] if expense_result else 0
            
            # Tranzaksiyalar soni
            count_result = await self.db.execute_query(
                """SELECT COUNT(*) as count FROM transactions 
                WHERE user_id = %s AND DATE(created_at) = %s""",
                (user_id, date_str)
            )
            tx_count = count_result[0]['count'] if count_result else 0
            
            # Sof foyda
            profit = total_income - total_expense
            profit_emoji = "📈" if profit >= 0 else "📉"
            
            report = f"📊 **Kunlik Hisobot**\n"
            report += f"📅 {date.strftime('%d.%m.%Y')}\n\n"
            report += f"💰 Kirim: **{total_income:,.0f}** so'm\n"
            report += f"💸 Chiqim: **{total_expense:,.0f}** so'm\n"
            report += f"{profit_emoji} Sof foyda: **{profit:,.0f}** so'm\n\n"
            report += f"📝 Tranzaksiyalar: {tx_count} ta"
            
            return report
            
        except Exception as e:
            logger.error(f"Daily report error: {e}")
            return "❌ Hisobot yuklashda xatolik"
    
    async def get_weekly_report(self, user_id: int) -> str:
        """Haftalik hisobot"""
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)
            
            # Kirimlar
            income_result = await self.db.execute_query(
                """SELECT COALESCE(SUM(amount), 0) as total FROM transactions 
                WHERE user_id = %s AND transaction_type = 'income' 
                AND created_at BETWEEN %s AND %s""",
                (user_id, start_date, end_date)
            )
            total_income = income_result[0]['total'] if income_result and isinstance(income_result[0], dict) else 0
            
            # Chiqimlar
            expense_result = await self.db.execute_query(
                """SELECT COALESCE(SUM(amount), 0) as total FROM transactions 
                WHERE user_id = %s AND transaction_type = 'expense' 
                AND created_at BETWEEN %s AND %s""",
                (user_id, start_date, end_date)
            )
            total_expense = expense_result[0]['total'] if expense_result else 0
            
            profit = total_income - total_expense
            profit_emoji = "📈" if profit >= 0 else "📉"
            
            report = f"📊 **Haftalik Hisobot**\n"
            report += f"📅 {start_date.strftime('%d.%m')} - {end_date.strftime('%d.%m.%Y')}\n\n"
            report += f"💰 Kirim: **{total_income:,.0f}** so'm\n"
            report += f"💸 Chiqim: **{total_expense:,.0f}** so'm\n"
            report += f"{profit_emoji} Sof foyda: **{profit:,.0f}** so'm"
            
            return report
            
        except Exception as e:
            logger.error(f"Weekly report error: {e}")
            return "❌ Hisobot yuklashda xatolik"
    
    async def get_monthly_report(self, user_id: int) -> str:
        """Oylik hisobot"""
        try:
            now = datetime.now()
            start_date = now.replace(day=1)
            
            # Kirimlar
            income_result = await self.db.execute_query(
                """SELECT COALESCE(SUM(amount), 0) as total FROM transactions 
                WHERE user_id = %s AND transaction_type = 'income' 
                AND created_at >= %s""",
                (user_id, start_date)
            )
            total_income = income_result[0]['total'] if income_result and isinstance(income_result[0], dict) else 0
            
            # Chiqimlar kategoriya bo'yicha
            expense_result = await self.db.execute_query(
                """SELECT category, COALESCE(SUM(amount), 0) as total FROM transactions 
                WHERE user_id = %s AND transaction_type = 'expense' 
                AND created_at >= %s
                GROUP BY category ORDER BY total DESC""",
                (user_id, start_date)
            )
            
            total_expense = sum(e['total'] for e in expense_result) if expense_result else 0
            profit = total_income - total_expense
            profit_emoji = "📈" if profit >= 0 else "📉"
            
            report = f"📊 **Oylik Hisobot**\n"
            report += f"📅 {start_date.strftime('%B %Y')}\n\n"
            report += f"💰 Kirim: **{total_income:,.0f}** so'm\n"
            report += f"💸 Chiqim: **{total_expense:,.0f}** so'm\n"
            report += f"{profit_emoji} Sof foyda: **{profit:,.0f}** so'm\n\n"
            
            if expense_result:
                report += "📂 **Chiqimlar kategoriyasi:**\n"
                for exp in expense_result[:5]:
                    report += f"  • {exp['category']}: {exp['total']:,.0f} so'm\n"
            
            return report
            
        except Exception as e:
            logger.error(f"Monthly report error: {e}")
            return "❌ Hisobot yuklashda xatolik"
    
    async def get_debts_report(self, user_id: int) -> str:
        """Qarzlar holati"""
        try:
            # Berilgan qarzlar
            lent_result = await self.db.execute_query(
                """SELECT person_name, amount 
                FROM debts WHERE user_id = %s AND debt_type = 'lent' AND status = 'active'""",
                (user_id,)
            )
            
            # Olingan qarzlar
            borrowed_result = await self.db.execute_query(
                """SELECT person_name, amount 
                FROM debts WHERE user_id = %s AND debt_type = 'borrowed' AND status = 'active'""",
                (user_id,)
            )
            
            total_lent = sum(d['amount'] for d in lent_result) if lent_result and isinstance(lent_result[0], dict) else 0
            total_borrowed = sum(d['amount'] for d in borrowed_result) if borrowed_result and isinstance(borrowed_result[0], dict) else 0
            
            report = "💳 **Qarzlar Holati**\n\n"
            
            report += f"📤 **Berilgan qarzlar:** {total_lent:,.0f} so'm\n"
            if lent_result and isinstance(lent_result[0], dict):
                for d in lent_result[:5]:
                    report += f"  • {d['person_name']}: {d['amount']:,.0f} so'm\n"
            else:
                report += "  Yo'q\n"
            
            report += f"\n📥 **Olingan qarzlar:** {total_borrowed:,.0f} so'm\n"
            if borrowed_result and isinstance(borrowed_result[0], dict):
                for d in borrowed_result[:5]:
                    report += f"  • {d['person_name']}: {d['amount']:,.0f} so'm\n"
            else:
                report += "  Yo'q\n"
            
            balance = total_lent - total_borrowed
            balance_emoji = "✅" if balance >= 0 else "⚠️"
            report += f"\n{balance_emoji} **Balans:** {balance:,.0f} so'm"
            
            return report
            
        except Exception as e:
            logger.error(f"Debts report error: {e}")
            return "❌ Qarzlar hisobotini yuklashda xatolik"
    
    # ================== OMBOR ==================
    
    async def get_warehouse_products(self, user_id: int) -> str:
        """Ombordagi tovarlar ro'yxati"""
        try:
            products = await self.db.execute_query(
                """SELECT name, quantity, unit, min_quantity 
                FROM warehouse_products WHERE user_id = %s ORDER BY name""",
                (user_id,)
            )
            
            if not products or len(products) == 0:
                return "📦 **Ombor**\n\nHozircha tovarlar yo'q.\n\n💡 Tovar qo'shish uchun yozing:\n\"Omborga 50 kg shakar qo'sh\""
            
            # Dict yoki tuple ekanini tekshirish
            if not isinstance(products[0], dict):
                return "📦 **Ombor**\n\nHozircha tovarlar yo'q.\n\n💡 Tovar qo'shish uchun yozing:\n\"Omborga 50 kg shakar qo'sh\""
            
            report = f"📦 **Ombor** ({len(products)} ta tovar)\n\n"
            
            for p in products:
                if isinstance(p, dict):
                    qty = p.get('quantity', 0) or 0
                    min_qty = p.get('min_quantity', 0) or 0
                    status = "⚠️" if qty <= min_qty else "✅"
                    unit = p.get('unit') or 'dona'
                    name = p.get('name', 'Nomsiz')
                    report += f"{status} **{name}**: {qty} {unit}\n"
            
            return report
            
        except Exception as e:
            logger.error(f"Warehouse products error: {e}")
            return "❌ Ombor ma'lumotlarini yuklashda xatolik"
    
    async def get_warehouse_stats(self, user_id: int) -> str:
        """Ombor statistikasi"""
        try:
            # Jami tovarlar
            products_result = await self.db.execute_query(
                """SELECT COUNT(*) as count, COALESCE(SUM(quantity * COALESCE(price, 0)), 0) as value 
                FROM warehouse_products WHERE user_id = %s""",
                (user_id,)
            )
            
            # Kam qolgan tovarlar
            low_result = await self.db.execute_query(
                """SELECT COUNT(*) as count FROM warehouse_products 
                WHERE user_id = %s AND quantity <= COALESCE(min_quantity, 5)""",
                (user_id,)
            )
            
            # Oylik harakatlar
            movements_result = await self.db.execute_query(
                """SELECT movement_type, COUNT(*) as count, SUM(quantity) as total 
                FROM warehouse_movements 
                WHERE user_id = %s AND created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                GROUP BY movement_type""",
                (user_id,)
            )
            
            # Natijalarni xavfsiz olish
            total_products = 0
            total_value = 0
            if products_result and len(products_result) > 0:
                if isinstance(products_result[0], dict):
                    total_products = products_result[0].get('count', 0) or 0
                    total_value = products_result[0].get('value', 0) or 0
            
            low_count = 0
            if low_result and len(low_result) > 0:
                if isinstance(low_result[0], dict):
                    low_count = low_result[0].get('count', 0) or 0
            
            monthly_in = 0
            monthly_out = 0
            if movements_result:
                for m in movements_result:
                    if isinstance(m, dict):
                        if m.get('movement_type') == 'in':
                            monthly_in = m.get('total', 0) or 0
                        else:
                            monthly_out = m.get('total', 0) or 0
            
            report = "📊 **Ombor Statistikasi**\n\n"
            report += f"📦 Jami tovarlar: **{total_products}** ta\n"
            report += f"💰 Umumiy qiymat: **{total_value:,.0f}** so'm\n"
            report += f"⚠️ Kam qolgan: **{low_count}** ta\n\n"
            report += f"📥 Oylik kirim: {monthly_in} birlik\n"
            report += f"📤 Oylik chiqim: {monthly_out} birlik"
            
            return report
            
        except Exception as e:
            logger.error(f"Warehouse stats error: {e}")
            return "❌ Statistika yuklashda xatolik"
    
    async def get_low_stock_products(self, user_id: int) -> str:
        """Kam qolgan tovarlar"""
        try:
            products = await self.db.execute_query(
                """SELECT name, quantity, unit, min_quantity 
                FROM warehouse_products 
                WHERE user_id = %s AND quantity <= COALESCE(min_quantity, 5)
                ORDER BY quantity ASC""",
                (user_id,)
            )
            
            if not products or len(products) == 0:
                return "✅ Barcha tovarlar yetarli miqdorda!"
            
            # Dict yoki tuple ekanini tekshirish
            if not isinstance(products[0], dict):
                return "✅ Barcha tovarlar yetarli miqdorda!"
            
            report = "⚠️ **Kam Qolgan Tovarlar**\n\n"
            for p in products:
                if isinstance(p, dict):
                    unit = p.get('unit') or 'dona'
                    min_qty = p.get('min_quantity') or 5
                    name = p.get('name', 'Nomsiz')
                    qty = p.get('quantity', 0) or 0
                    report += f"🔴 **{name}**\n"
                    report += f"   Qoldiq: {qty} {unit} (min: {min_qty})\n\n"
            
            return report
            
        except Exception as e:
            logger.error(f"Low stock error: {e}")
            return "❌ Ma'lumot yuklashda xatolik"
    
    # ================== AI CHAT ==================
    
    async def ai_chat_response(self, user_id: int, question: str) -> str:
        """AI Chat - biznes savollarga javob"""
        try:
            # Biznes ma'lumotlarini yig'ish
            daily_report = await self.get_daily_report(user_id)
            monthly_report = await self.get_monthly_report(user_id)
            debts_report = await self.get_debts_report(user_id)
            warehouse_stats = await self.get_warehouse_stats(user_id)
            
            context = f"""Biznes ma'lumotlari:

{daily_report}

{monthly_report}

{debts_report}

{warehouse_stats}
"""
            
            # AI dan javob olish
            response = await self.ai_chat.generate_business_response(user_id, question, context)
            
            return response or "🤔 Javob berishda xatolik. Qaytadan urinib ko'ring."
            
        except Exception as e:
            logger.error(f"AI chat error: {e}")
            return "❌ AI javob berishda xatolik"
    
    async def ai_warehouse_analysis(self, user_id: int) -> str:
        """AI Ombor tahlili"""
        try:
            warehouse_products = await self.get_warehouse_products(user_id)
            warehouse_stats = await self.get_warehouse_stats(user_id)
            low_stock = await self.get_low_stock_products(user_id)
            
            context = f"""Ombor ma'lumotlari:

{warehouse_products}

{warehouse_stats}

{low_stock}
"""
            
            question = """Ombor tahlilini qil:
1. Qaysi mahsulotlar tez tugayapti?
2. Qanday tavsiyalar bera olasan?
3. Qaysi mahsulotlarni ko'proq olib kelish kerak?

Qisqa va aniq javob ber."""

            response = await self.ai_chat.generate_business_response(user_id, question, context)
            
            return f"🤖 **AI Ombor Tahlili**\n\n{response}" if response else "❌ Tahlil qilishda xatolik"
            
        except Exception as e:
            logger.error(f"AI warehouse analysis error: {e}")
            return "❌ Tahlil qilishda xatolik"
    
    async def ai_business_analysis(self, user_id: int) -> str:
        """AI Biznes tahlili"""
        try:
            daily_report = await self.get_daily_report(user_id)
            monthly_report = await self.get_monthly_report(user_id)
            debts_report = await self.get_debts_report(user_id)
            
            context = f"""Biznes ma'lumotlari:

{daily_report}

{monthly_report}

{debts_report}
"""
            
            question = """Biznes tahlilini qil:
1. Moliyaviy holat qanday?
2. Qayerda tejash mumkin?
3. Qanday tavsiyalar berasan?
4. Xavflar bormi?

Qisqa, aniq va amaliy javob ber."""

            response = await self.ai_chat.generate_business_response(user_id, question, context)
            
            return f"🤖 **AI Biznes Tahlili**\n\n{response}" if response else "❌ Tahlil qilishda xatolik"
            
        except Exception as e:
            logger.error(f"AI business analysis error: {e}")
            return "❌ Tahlil qilishda xatolik"
    
    # ================== XODIMLAR ==================
    
    async def get_employees_list(self, user_id: int) -> str:
        """Xodimlar ro'yxati"""
        try:
            employees = await self.db.execute_query(
                """SELECT e.id, e.name, e.role, e.telegram_id, u.name as telegram_name
                FROM business_employees e
                LEFT JOIN users u ON e.telegram_id = u.user_id
                WHERE e.owner_id = %s AND e.is_active = 1""",
                (user_id,)
            )
            
            if not employees:
                return "👥 **Xodimlar**\n\nHozircha xodimlar yo'q.\n\n➕ Xodim qo'shish uchun tugmani bosing."
            
            report = f"👥 **Xodimlar** ({len(employees)} ta)\n\n"
            
            for emp in employees:
                role_emoji = "👔" if emp['role'] == 'manager' else "👤"
                role_text = "Menejer" if emp['role'] == 'manager' else "Xodim"
                report += f"{role_emoji} **{emp['name']}**\n"
                report += f"   Rol: {role_text}\n"
                report += f"   Telegram ID: {emp['telegram_id']}\n\n"
            
            return report
            
        except Exception as e:
            logger.error(f"Employees list error: {e}")
            return "❌ Xodimlar ro'yxatini yuklashda xatolik"
    
    async def add_employee(self, owner_id: int, telegram_id: int, name: str, role: str = 'employee') -> Dict:
        """Xodim qo'shish"""
        try:
            # Tekshirish - foydalanuvchi mavjudmi
            user = await self.db.execute_query(
                "SELECT user_id, name FROM users WHERE user_id = %s",
                (telegram_id,)
            )
            
            if not user:
                return {
                    'success': False,
                    'message': "❌ Bu foydalanuvchi botda ro'yxatdan o'tmagan.\nAvval /start bosishi kerak."
                }
            
            # Tekshirish - allaqachon xodimmi
            existing = await self.db.execute_query(
                "SELECT id FROM business_employees WHERE owner_id = %s AND telegram_id = %s AND is_active = 1",
                (owner_id, telegram_id)
            )
            
            if existing:
                return {
                    'success': False,
                    'message': "❌ Bu foydalanuvchi allaqachon xodim sifatida qo'shilgan."
                }
            
            # Qo'shish
            await self.db.execute_query(
                """INSERT INTO business_employees (owner_id, telegram_id, name, role, is_active, created_at) 
                VALUES (%s, %s, %s, %s, 1, NOW())""",
                (owner_id, telegram_id, name, role)
            )
            
            role_text = "Menejer" if role == 'manager' else "Xodim"
            return {
                'success': True,
                'message': f"✅ **Xodim qo'shildi!**\n\n"
                          f"👤 Ism: {name}\n"
                          f"📋 Rol: {role_text}\n"
                          f"🆔 Telegram ID: {telegram_id}"
            }
            
        except Exception as e:
            logger.error(f"Add employee error: {e}")
            return {'success': False, 'message': f"❌ Xatolik: {str(e)}"}
    
    async def is_employee(self, user_id: int) -> Optional[Dict]:
        """Foydalanuvchi xodimmi tekshirish"""
        try:
            result = await self.db.execute_query(
                """SELECT e.id, e.owner_id, e.name, e.role 
                FROM business_employees e
                WHERE e.telegram_id = %s AND e.is_active = 1""",
                (user_id,)
            )
            
            return result[0] if result else None
            
        except Exception as e:
            logger.error(f"Is employee check error: {e}")
            return None


# Global instance yaratish uchun factory function
def create_business_module(db, ai_chat):
    return BusinessModule(db, ai_chat)
