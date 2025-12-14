"""
Warehouse (Ombor) moduli - Biznes tarif uchun
Ombor boshqaruvi, tovarlar, kirim/chiqim, AI tahlil
"""
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)


class WarehouseModule:
    def __init__(self, db, ai_chat):
        self.db = db
        self.ai_chat = ai_chat
    
    async def add_product(self, user_id: int, name: str, category: str = None,
                          barcode: str = None, price: float = 0, quantity: int = 0,
                          min_quantity: int = 0, image_url: str = None) -> Dict:
        """Tovar qo'shish"""
        try:
            product_id = await self.db.add_warehouse_product(
                user_id, name, category, barcode, price, quantity, min_quantity, image_url
            )
            return {
                'success': True,
                'product_id': product_id,
                'message': f"✅ Tovar qo'shildi: {name}"
            }
        except Exception as e:
            logger.error(f"Tovar qo'shishda xatolik: {e}")
            return {
                'success': False,
                'message': f"❌ Xatolik: {str(e)}"
            }
    
    async def add_movement(self, user_id: int, product_id: int, movement_type: str,
                           quantity: int, unit_price: float = None,
                           description: str = None) -> Dict:
        """Kirim/chiqim qo'shish"""
        try:
            # Tovarni olish
            product = await self.db.get_warehouse_product(product_id, user_id)
            if not product:
                return {
                    'success': False,
                    'message': "❌ Tovar topilmadi"
                }
            
            # Chiqim bo'lsa, qoldiqni tekshirish
            if movement_type == 'out' and product['quantity'] < quantity:
                return {
                    'success': False,
                    'message': f"❌ Yetarli tovar yo'q. Qoldiq: {product['quantity']}"
                }
            
            # Xarajatni hisoblash
            total_cost = None
            if unit_price:
                total_cost = unit_price * quantity
            
            # Harakatni qo'shish
            movement_id = await self.db.add_warehouse_movement(
                user_id, product_id, movement_type, quantity, unit_price, total_cost, description
            )
            
            # Xarajatni qo'shish (agar kirim bo'lsa)
            expense_id = None
            if movement_type == 'in' and total_cost:
                expense_id = await self.db.add_warehouse_expense(
                    user_id, 'purchase', total_cost, product_id, movement_id,
                    f"Tovar kirimi: {product['name']}"
                )
            
            # Yangilangan tovarni olish
            updated_product = await self.db.get_warehouse_product(product_id, user_id)
            
            movement_text = "Kirim" if movement_type == 'in' else "Chiqim"
            return {
                'success': True,
                'movement_id': movement_id,
                'expense_id': expense_id,
                'product': updated_product,
                'message': f"✅ {movement_text} qo'shildi\n\n"
                          f"📦 Tovar: {product['name']}\n"
                          f"🔢 Miqdor: {quantity}\n"
                          f"💰 Narx: {unit_price:,.0f} so'm" if unit_price else f"💰 Narx: -" + "\n"
                          f"📊 Qoldiq: {updated_product['quantity']}"
            }
        except Exception as e:
            logger.error(f"Harakat qo'shishda xatolik: {e}")
            return {
                'success': False,
                'message': f"❌ Xatolik: {str(e)}"
            }
    
    async def get_products_list(self, user_id: int, category: str = None) -> str:
        """Tovarlar ro'yxatini formatlangan ko'rinishda olish"""
        try:
            products = await self.db.get_warehouse_products(user_id, category)
            
            if not products:
                return "📦 Hozircha tovarlar yo'q"
            
            text = f"📦 **Tovarlar ro'yxati** ({len(products)} ta)\n\n"
            
            for idx, product in enumerate(products, 1):
                status = "⚠️" if product['quantity'] <= product['min_quantity'] else "✅"
                text += f"{status} **{idx}. {product['name']}**\n"
                if product['category']:
                    text += f"   📂 Kategoriya: {product['category']}\n"
                text += f"   🔢 Qoldiq: {product['quantity']}"
                if product['min_quantity'] > 0:
                    text += f" (min: {product['min_quantity']})\n"
                else:
                    text += "\n"
                if product['price'] > 0:
                    text += f"   💰 Narx: {product['price']:,.0f} so'm\n"
                if product['barcode']:
                    text += f"   📊 Shtrix kod: {product['barcode']}\n"
                text += "\n"
            
            return text
        except Exception as e:
            logger.error(f"Tovarlar ro'yxatini olishda xatolik: {e}")
            return "❌ Xatolik yuz berdi"
    
    async def get_low_stock_alert(self, user_id: int) -> Optional[str]:
        """Kam qolgan tovarlar haqida bildirishnoma"""
        try:
            low_stock = await self.db.get_low_stock_products(user_id)
            
            if not low_stock:
                return None
            
            text = "⚠️ **Tovar kamayib qoldi!**\n\n"
            for product in low_stock:
                text += f"📦 **{product['name']}**\n"
                text += f"   Qoldiq: {product['quantity']} (min: {product['min_quantity']})\n\n"
            
            return text
        except Exception as e:
            logger.error(f"Kam qolgan tovarlarni olishda xatolik: {e}")
            return None
    
    async def get_warehouse_statistics(self, user_id: int) -> str:
        """Ombor statistikalarini olish"""
        try:
            stats = await self.db.get_warehouse_statistics(user_id)
            
            text = "📊 **Ombor statistikasi**\n\n"
            text += f"📦 Jami tovarlar: {stats['total_products']} ta\n"
            text += f"💰 Jami qiymat: {stats['total_value']:,.0f} so'm\n"
            text += f"⚠️ Kam qolgan: {stats['low_stock_count']} ta\n\n"
            text += f"📈 Oylik kirim: {stats['monthly_in']} birlik\n"
            text += f"📉 Oylik chiqim: {stats['monthly_out']} birlik\n"
            text += f"💸 Oylik xarajatlar: {stats['monthly_expenses']:,.0f} so'm\n"
            
            return text
        except Exception as e:
            logger.error(f"Statistikani olishda xatolik: {e}")
            return "❌ Xatolik yuz berdi"
    
    async def ai_warehouse_analysis(self, user_id: int) -> str:
        """AI tomonidan ombor tahlili"""
        try:
            # Ma'lumotlarni olish
            products = await self.db.get_warehouse_products(user_id)
            movements = await self.db.get_warehouse_movements(user_id, limit=100)
            expenses = await self.db.get_warehouse_expenses(user_id, limit=100)
            stats = await self.db.get_warehouse_statistics(user_id)
            low_stock = await self.db.get_low_stock_products(user_id)
            
            # AI uchun kontekst yaratish
            context = {
                'total_products': stats['total_products'],
                'total_value': stats['total_value'],
                'low_stock_count': stats['low_stock_count'],
                'monthly_in': stats['monthly_in'],
                'monthly_out': stats['monthly_out'],
                'monthly_expenses': stats['monthly_expenses'],
                'products': products[:20],  # Eng ko'p 20 ta
                'low_stock_products': low_stock[:10],  # Eng ko'p 10 ta
                'recent_movements': movements[:20]  # Eng ko'p 20 ta
            }
            
            # AI prompt
            prompt = f"""Ombor tahlili qilish kerak:

Statistikalar:
- Jami tovarlar: {stats['total_products']} ta
- Jami qiymat: {stats['total_value']:,.0f} so'm
- Kam qolgan tovarlar: {stats['low_stock_count']} ta
- Oylik kirim: {stats['monthly_in']} birlik
- Oylik chiqim: {stats['monthly_out']} birlik
- Oylik xarajatlar: {stats['monthly_expenses']:,.0f} so'm

Kam qolgan tovarlar:
{json.dumps([{'name': p['name'], 'quantity': p['quantity'], 'min': p['min_quantity']} for p in low_stock[:10]], ensure_ascii=False, indent=2)}

Eng ko'p sotilgan tovarlar (oxirgi 20 ta harakat):
{json.dumps([{'product_id': m['product_id'], 'type': m['movement_type'], 'quantity': m['quantity']} for m in movements[:20] if m['movement_type'] == 'out'], ensure_ascii=False, indent=2)}

Quyidagi savollarga javob bering:
1. Qaysi mahsulotlar eng tez tugayapti?
2. Qaysi mahsulotlar zarar bilan sotilmoqda?
3. Ombor samaradorligi qanday?
4. Qanday tavsiyalar bera olasiz?

Javobni o'zbek tilida, qisqa va aniq bering."""

            # AI javob olish
            ai_response = await self.ai_chat.generate_response(user_id, prompt)
            
            if ai_response and len(ai_response) > 0:
                analysis_text = "\n".join(ai_response)
                return f"🤖 **AI Ombor Tahlili**\n\n{analysis_text}"
            else:
                return "❌ AI tahlil olishda xatolik"
                
        except Exception as e:
            logger.error(f"AI tahlil olishda xatolik: {e}")
            return "❌ Xatolik yuz berdi"
    
    async def get_fastest_selling_products(self, user_id: int, days: int = 30) -> List[Dict]:
        """Eng tez sotiladigan tovarlarni olish"""
        try:
            movements = await self.db.get_warehouse_movements(user_id, movement_type='out', limit=1000)
            
            # Oxirgi N kun ichidagi harakatlar
            cutoff_date = datetime.now() - timedelta(days=days)
            recent_movements = [
                m for m in movements 
                if m['created_at'] and m['created_at'] >= cutoff_date
            ]
            
            # Tovar bo'yicha guruhlash
            product_stats = {}
            for movement in recent_movements:
                product_id = movement['product_id']
                if product_id not in product_stats:
                    product_stats[product_id] = {
                        'product_id': product_id,
                        'total_quantity': 0,
                        'movement_count': 0
                    }
                product_stats[product_id]['total_quantity'] += movement['quantity']
                product_stats[product_id]['movement_count'] += 1
            
            # Tovarlarni olish
            fastest_products = []
            for product_id, stats in sorted(product_stats.items(), key=lambda x: x[1]['total_quantity'], reverse=True):
                product = await self.db.get_warehouse_product(product_id)
                if product:
                    fastest_products.append({
                        'product': product,
                        'total_sold': stats['total_quantity'],
                        'movement_count': stats['movement_count']
                    })
            
            return fastest_products[:10]  # Top 10
        except Exception as e:
            logger.error(f"Eng tez sotiladigan tovarlarni olishda xatolik: {e}")
            return []
    
    async def get_loss_products(self, user_id: int) -> List[Dict]:
        """Zarar bilan sotiladigan tovarlarni olish"""
        try:
            products = await self.db.get_warehouse_products(user_id)
            movements = await self.db.get_warehouse_movements(user_id, movement_type='out', limit=1000)
            expenses = await self.db.get_warehouse_expenses(user_id, limit=1000)
            
            # Har bir tovar uchun xarajat va daromadni hisoblash
            loss_products = []
            
            for product in products:
                # Tovar uchun xarajatlar
                product_expenses = [
                    e for e in expenses 
                    if e.get('product_id') == product['id']
                ]
                total_expenses = sum(e['amount'] for e in product_expenses)
                
                # Tovar uchun chiqimlar
                product_movements = [
                    m for m in movements 
                    if m['product_id'] == product['id']
                ]
                
                # Chiqimdan olingan daromad
                total_revenue = 0
                for movement in product_movements:
                    if movement['unit_price']:
                        total_revenue += movement['unit_price'] * movement['quantity']
                    elif product['price']:
                        total_revenue += product['price'] * movement['quantity']
                
                # Zarar hisoblash
                if total_expenses > 0 and total_revenue < total_expenses:
                    loss = total_expenses - total_revenue
                    loss_products.append({
                        'product': product,
                        'total_expenses': total_expenses,
                        'total_revenue': total_revenue,
                        'loss': loss
                    })
            
            # Zarar bo'yicha tartiblash
            loss_products.sort(key=lambda x: x['loss'], reverse=True)
            
            return loss_products[:10]  # Top 10
        except Exception as e:
            logger.error(f"Zarar bilan sotiladigan tovarlarni olishda xatolik: {e}")
            return []

