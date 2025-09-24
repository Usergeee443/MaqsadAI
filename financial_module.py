import re
import logging
import json
import aiofiles
from typing import Optional, Dict, Any, List
from datetime import datetime
from openai import AsyncOpenAI
from config import OPENAI_API_KEY, CATEGORIES
from database import db
from models import Transaction, TransactionType

class FinancialModule:
    def __init__(self):
        self.openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        
    async def process_audio_input(self, audio_file_path: str, user_id: int) -> Dict[str, Any]:
        """Audio faylni qayta ishlash va moliyaviy ma'lumotlarni ajratish"""
        try:
            # Audio faylni matnga aylantirish - bir nechta til bilan sinab ko'ramiz
            with open(audio_file_path, "rb") as audio_file:
                # Avval Uzbek tilida sinab ko'ramiz (Whisper Large-v3)
                try:
                    transcript = await self.openai_client.audio.transcriptions.create(
                        model="whisper-1",  # OpenAI API da bu avtomatik ravishda Large-v3 ni ishlatadi
                        file=audio_file,
                        language="uz"
                    )
                    text = transcript.text
                    logging.info(f"Audio transkript (Uzbek): {text}")
                except:
                    # Agar Uzbek ishlamasa, avtomatik aniqlash (Whisper Large-v3)
                    transcript = await self.openai_client.audio.transcriptions.create(
                        model="whisper-1",  # OpenAI API da bu avtomatik ravishda Large-v3 ni ishlatadi
                        file=audio_file
                    )
                    text = transcript.text
                    logging.info(f"Audio transkript (Auto): {text}")
            
            # Audio transkriptni yaxshilash uchun AI dan foydalanamiz
            improved_text = await self.improve_audio_transcript(text)
            logging.info(f"Yaxshilangan transkript: {improved_text}")
            
            # Matnni moliyaviy ma'lumotlar sifatida qayta ishlash
            return await self.process_ai_input(improved_text, user_id)
            
        except Exception as e:
            logging.error(f"Audio qayta ishlashda xatolik: {e}")
            return {
                "success": False,
                "message": "❌ Audio faylni qayta ishlashda xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring."
            }
    
    async def improve_audio_transcript(self, text: str) -> str:
        """Audio transkriptni yaxshilash va to'g'ri tilga o'tkazish"""
        try:
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": """Siz audio transkript yaxshilash mutaxassisisiz. Foydalanuvchi yuborgan audio transkriptni O'ZBEK TILIDA to'g'ri va aniq qilib yozing.

MUHIM:
1. Agar transkript noto'g'ri til yoki noto'g'ri yozilgan bo'lsa, uni O'zbek tilida to'g'ri qilib yozing
2. Raqamlarni to'g'ri aniqlang (masalan: "100 ming" = "100000", "50 bin" = "50000", "100k" = "100000")
3. Moliyaviy atamalarni to'g'ri tarjima qiling
4. Faqat to'g'ri va aniq matn qaytaring
5. NOISY, CHALA, SIFATSIZ gapirilgan audio transkriptlarni ham mukammal tushunish va to'g'ri qayta ishlash
6. Har qanday til yoki lahja bilan gapirilgan bo'lsa ham, O'zbek tilida to'g'ri qilib yozish
7. Raqamlarni har qanday formatda aytilgan bo'lsa ham to'g'ri aniqlash
8. AGAR MATNDA HAR QANDAY RAQAM (summa) VA PUL BILAN BOG'LIQ SO'ZLAR BO'LSA, BU MOLIYAVIY MA'LUMOT HISOBLANADI
9. "ishlab topdim", "topdim", "oldim", "qildim", "ishladim", "ishlash", "pul", "so'm", "dollar", "summa" kabi so'zlar mavjud bo'lsa, bu MOLIYAVIY MA'LUMOT
10. Faqat raqam va pul haqida gapirilgan bo'lsa ham, bu MOLIYAVIY MA'LUMOT

MISOL:
Noto'g'ri: "Бүгін, ең күріме минсуым такси ү总шылатып, 53 минсуым ахат ү гоншылатып"
To'g'ri: "Bugun 100 ming so'm taksi uchun ketdi, 53 ming so'm ovqat uchun ketdi"

MISOL:
Noto'g'ri: "Bugün 50 bin lira yemek, 30 bin lira ulaşım"
To'g'ri: "Bugun 50 ming so'm ovqat, 30 ming so'm transport"

MISOL (ishlab topish):
Noto'g'ri: "Bugun 100000 ishlab topdim"
To'g'ri: "Bugun 100000 so'm ishlab topdim"

MISOL (pul haqida):
Noto'g'ri: "Bugun 50000 pul oldim"
To'g'ri: "Bugun 50000 so'm pul oldim"

Faqat to'g'ri va aniq matn qaytaring, boshqa izoh bermang."""
                    },
                    {
                        "role": "user",
                        "content": f"Bu audio transkriptni O'zbek tilida to'g'ri qilib yozing (agar moliyaviy ma'lumot bo'lsa, uni saqlang): {text}"
                    }
                ],
                temperature=0.0,
                max_tokens=2000,
                top_p=0.1,
                frequency_penalty=0.0,
                presence_penalty=0.0
            )
            
            improved_text = response.choices[0].message.content.strip()
            logging.info(f"Yaxshilangan transkript: {improved_text}")
            return improved_text
            
        except Exception as e:
            logging.error(f"Audio transkript yaxshilashda xatolik: {e}")
            return text  # Agar yaxshilash ishlamasa, asl matnni qaytaramiz
    
    async def process_ai_input(self, text: str, user_id: int) -> Dict[str, Any]:
        """AI yordamida moliyaviy ma'lumotni qayta ishlash - ko'p tranzaksiyalarni qo'llab-quvvatlash"""
        try:
            # OpenAI API orqali matnni tahlil qilish - eng kuchli model
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o",  # Eng kuchli va eng yangi model
                
                messages=[
                    {
                        "role": "system",
                        "content": """Siz professional moliyaviy yordamchi AI siz. Foydalanuvchi yuborgan matndan (O'zbek, Qozoq, Rus, Turk, Arab yoki boshqa tillarda) BARCHA moliyaviy ma'lumotlarni 100% aniq ajratib oling.

MUHIM QOIDALAR: 
1. Matn bir nechta tranzaksiyani o'z ichiga olishi mumkin. Har bir summa va uning maqsadini alohida tranzaksiya sifatida ajrating.
2. BARCHA javoblarni O'ZBEK TILIDA bering.
3. Description (tafsilot) maydonida faqat O'ZBEK tilida yozing.
4. Kategoriya nomlari ham O'ZBEK tilida bo'lishi kerak.
5. Sifatli yoki sifatsiz gapirilgan bo'lsa ham, barcha moliyaviy ma'lumotlarni toping.
6. NOISY, CHALA, SIFATSIZ gapirilgan matnlarni ham mukammal tushunish va to'g'ri qayta ishlash.
7. Raqamlarni har qanday formatda yozilgan bo'lsa ham to'g'ri aniqlash (ming, bin, тыс, k, so'm, сом, руб, лира, ريال, dollar).
8. Har qanday til yoki lahja bilan yozilgan bo'lsa ham, moliyaviy ma'lumotlarni topish.
9. MUHIM: "ishlab topdim", "topdim", "oldim", "qildim" kabi so'zlar PUL ISHLAB TOPISHNI anglatadi va KIRIM tranzaksiyasi hisoblanadi.
10. "ketdi", "sarfladim", "to'ladim", "berdim" kabi so'zlar CHIQIM tranzaksiyasi hisoblanadi.
11. "qarz", "qarzni qaytardim", "qarz berdim" kabi so'zlar QARZ tranzaksiyasi hisoblanadi.

KRITIK MUHIM: 
- AGAR MATNDA HAR QANDAY RAQAM (summa) VA PUL BILAN BOG'LIQ SO'ZLAR BO'LSA, BU MOLIYAVIY MA'LUMOT HISOBLANADI
- "ishlab topdim", "topdim", "oldim", "qildim", "ishladim", "ishlash", "pul", "so'm", "dollar", "summa" kabi so'zlar mavjud bo'lsa, bu MOLIYAVIY MA'LUMOT
- Faqat raqam va pul haqida gapirilgan bo'lsa ham, bu MOLIYAVIY MA'LUMOT
- Hech qachon "Bu moliyaviy ma'lumot emas" deb javob bermang - har doim moliyaviy ma'lumotlarni toping

Har bir tranzaksiya uchun:
1. Summa (raqam) - faqat raqam
2. Tranzaksiya turi - "income" (kirim), "expense" (chiqim), "debt" (qarz)
3. Kategoriya - "ovqat", "transport", "ish haqi", "biznes", "investitsiya", "kiyim", "uy", "sog'liq", "ta'lim", "o'yin-kulgi", "boshqa"
4. Tafsilot - O'ZBEK tilida qisqa tavsif (masalan: "taksi uchun", "ovqat uchun", "ish haqi")

MISOL:
Matn: "Bugun 100 ming so'm taksi uchun ketdi, 120 ming so'm oziq-ovqatga sarfladim, 200 ming so'm ish haqi oldim, 50 ming so'm telefon uchun to'ladim, 100 ming so'm qarzni qaytardim, 50 ming so'm qarz berdim"

YANA MISOL (ishlab topish):
Matn: "Bugun 100000 ishlab topdim, 50000 qo'shimcha ish qildim"

Javob:
{
    "transactions": [
        {
            "amount": 100000,
            "type": "expense",
            "category": "transport",
            "description": "taksi uchun"
        },
        {
            "amount": 120000,
            "type": "expense",
            "category": "ovqat",
            "description": "oziq-ovqatga"
        },
        {
            "amount": 200000,
            "type": "income",
            "category": "ish haqi",
            "description": "ish haqi"
        },
        {
            "amount": 50000,
            "type": "expense",
            "category": "boshqa",
            "description": "telefon uchun"
        },
        {
            "amount": 100000,
            "type": "debt",
            "category": "boshqa",
            "description": "qarzni qaytarish"
        },
        {
            "amount": 50000,
            "type": "debt",
            "category": "boshqa",
            "description": "qarz berish"
        }
    ]
}

YANA MISOL JAVOBI (ishlab topish):
Matn: "Bugun 100000 ishlab topdim, 50000 qo'shimcha ish qildim"

Javob:
{
    "transactions": [
        {
            "amount": 100000,
            "type": "income",
            "category": "ish haqi",
            "description": "ishlab topish"
        },
        {
            "amount": 50000,
            "type": "income",
            "category": "ish haqi",
            "description": "qo'shimcha ish"
        }
    ]
}

YANA MISOL (Turk tilida):
Matn: "Bugün 50 bin lira yemek, 30 bin lira ulaşım, 100 bin lira maaş aldım"

Javob:
{
    "transactions": [
        {
            "amount": 50000,
            "type": "expense",
            "category": "ovqat",
            "description": "ovqat uchun"
        },
        {
            "amount": 30000,
            "type": "expense",
            "category": "transport",
            "description": "transport uchun"
        },
        {
            "amount": 100000,
            "type": "income",
            "category": "ish haqi",
            "description": "ish haqi"
        }
    ]
}

YANA MISOL (Qozoq tilida):
Matn: "Бүгін 50 мың теңге тамақ, 30 мың теңге көлік, 100 мың теңге жалақы алдым"

Javob:
{
    "transactions": [
        {
            "amount": 50000,
            "type": "expense",
            "category": "ovqat",
            "description": "ovqat uchun"
        },
        {
            "amount": 30000,
            "type": "expense",
            "category": "transport",
            "description": "transport uchun"
        },
        {
            "amount": 100000,
            "type": "income",
            "category": "ish haqi",
            "description": "ish haqi"
        }
    ]
}

YANA MISOL (Sifatli gapirilgan):
Matn: "Бүгін, ең күріме минсуым такси ү总шылатып, 53 минсуым ахат ү гоншылатып 100 минсуум целефонүң і жинауыншылатып"

Javob:
{
    "transactions": [
        {
            "amount": 1000000,
            "type": "expense",
            "category": "transport",
            "description": "taksi uchun"
        },
        {
            "amount": 530000,
            "type": "expense",
            "category": "ovqat",
            "description": "ovqat uchun"
        },
        {
            "amount": 1000000,
            "type": "expense",
            "category": "boshqa",
            "description": "telefon uchun"
        }
    ]
}

YANA MISOL (Arab tilida):
Matn: "اليوم 50 ألف ريال للطعام، 30 ألف ريال للنقل، 100 ألف ريال راتب"

Javob:
{
    "transactions": [
        {
            "amount": 50000,
            "type": "expense",
            "category": "ovqat",
            "description": "ovqat uchun"
        },
        {
            "amount": 30000,
            "type": "expense",
            "category": "transport",
            "description": "transport uchun"
        },
        {
            "amount": 100000,
            "type": "income",
            "category": "ish haqi",
            "description": "ish haqi"
        }
    ]
}

MUHIM: 
- Barcha description (tafsilot) maydonlari O'ZBEK tilida bo'lishi kerak!
- Sifatli yoki sifatsiz gapirilgan bo'lsa ham, barcha moliyaviy ma'lumotlarni toping!
- Faqat JSON formatda javob bering, boshqa matn yozmang!
- Agar moliyaviy ma'lumot bo'lmasa, null qaytaring!"""
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ],
                temperature=0.0,  # Eng aniq javob uchun
                max_tokens=3000,  # Katta javoblar uchun
                top_p=0.1,  # Eng aniq variantlarni tanlash
                frequency_penalty=0.0,  # Takrorlanishni oldini olish
                presence_penalty=0.0  # Mavjudlik penalizatsiyasi
            )
            
            # JSON javobni parse qilish
            ai_response = response.choices[0].message.content
            if not ai_response:
                return {
                    "success": False,
                    "message": "❌ AI javob bermadi. Iltimos, qaytadan urinib ko'ring."
                }
            
            try:
                # AI javobini tozalash - faqat JSON qismini olish
                ai_response = ai_response.strip()
                if ai_response.startswith('```json'):
                    ai_response = ai_response[7:]
                if ai_response.endswith('```'):
                    ai_response = ai_response[:-3]
                if ai_response.startswith('```'):
                    ai_response = ai_response[3:]
                
                # JSON ni parse qilish
                data = json.loads(ai_response)
            except json.JSONDecodeError as e:
                logging.error(f"JSON parse xatolik: {e}")
                logging.error(f"AI javob: {ai_response}")
                
                # Agar JSON parse qilishda xatolik bo'lsa, oddiy matn sifatida qayta ishlash
                return await self.fallback_text_processing(text, user_id)
            
            # Agar moliyaviy ma'lumot bo'lmasa
            if not data or not data.get('transactions'):
                return {
                    "success": False,
                    "message": "❌ Bu moliyaviy ma'lumot emas. Iltimos, kirim/chiqim haqida yozing."
                }
            
            # Ko'p tranzaksiyalarni qayta ishlash
            transactions = data.get('transactions', [])
            if not transactions:
                return {
                    "success": False,
                    "message": "❌ Moliyaviy ma'lumot topilmadi. Iltimos, aniqroq yozing."
                }
            
            # Har bir tranzaksiyani saqlash
            saved_transactions = []
            failed_count = 0
            
            for transaction_data in transactions:
                try:
                    transaction_id = await self.save_transaction(
                        user_id=user_id,
                        amount=float(transaction_data.get('amount', 0)),
                        category=transaction_data.get('category', 'boshqa'),
                        description=transaction_data.get('description', ''),
                        transaction_type=TransactionType(transaction_data.get('type', 'expense'))
                    )
                    if transaction_id:
                        saved_transactions.append({
                            'id': transaction_id,
                            'amount': transaction_data.get('amount', 0),
                            'type': transaction_data.get('type', 'expense'),
                            'category': transaction_data.get('category', 'boshqa'),
                            'description': transaction_data.get('description', '')
                        })
                except Exception as e:
                    logging.error(f"Tranzaksiya saqlashda xatolik: {e}")
                    failed_count += 1
            
            # Natijalarni formatlash
            if not saved_transactions:
                return {
                    "success": False,
                    "message": "❌ Hech qanday tranzaksiya saqlanmadi. Iltimos, qaytadan urinib ko'ring."
                }
            
            # Xabar tuzish
            message = f"✅ {len(saved_transactions)} ta tranzaksiya saqlandi!\n\n"
            
            for i, trans in enumerate(saved_transactions, 1):
                type_emoji = {
                    "income": "📈",
                    "expense": "📉", 
                    "debt": "💳"
                }.get(trans['type'], "❓")
                
                message += f"{i}. {type_emoji} {trans['amount']:,.0f} so'm\n"
                message += f"   📂 {trans['category']}\n"
                message += f"   📝 {trans['description']}\n\n"
            
            if failed_count > 0:
                message += f"⚠️ {failed_count} ta tranzaksiya saqlanmadi."
            
            return {
                "success": True,
                "transactions": saved_transactions,
                "message": message
            }
            
        except Exception as e:
            logging.error(f"AI qayta ishlashda xatolik: {e}")
            return {
                "success": False,
                "message": "❌ Ma'lumotni qayta ishlashda xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring."
            }
    
    async def fallback_text_processing(self, text: str, user_id: int) -> Dict[str, Any]:
        """AI JSON bermasa, oddiy regex bilan qayta ishlash"""
        try:
            import re
            
            # Raqamlarni topish (ko'proq tilli qo'llab-quvvatlash va sifatsiz matnlar uchun)
            amounts = re.findall(r'(\d+(?:\.\d+)?)\s*(?:ming|тысяч|тыс|k|so\'m|сом|руб|рублей|bin|мың|тың|лира|ريال|دولار|dollar|мин|тыс|к|млн|миллион|миллиард)', text, re.IGNORECASE)
            
            if not amounts:
                # Agar aniq raqam topilmasa, barcha raqamlarni qidirish
                all_numbers = re.findall(r'\d+(?:\.\d+)?', text)
                if not all_numbers:
                    return {
                        "success": False,
                        "message": "❌ Moliyaviy ma'lumot topilmadi. Iltimos, summa va maqsadni aniq yozing."
                    }
                amounts = all_numbers
            
            # Kategoriyalarni aniqlash (ko'p tilli qo'llab-quvvatlash va sifatsiz matnlar uchun)
            categories = {
                'ovqat': ['ovqat', 'oziq', 'tushlik', 'non', 'sut', 'go\'sht', 'sabzavot', 'meva', 'yemek', 'еда', 'тамак', 'еда', 'тамак', 'ахат', 'аш', 'тамак'],
                'transport': ['taksi', 'avtobus', 'metro', 'mashina', 'yo\'l', 'bilet', 'ulaşım', 'транспорт', 'көлік', 'транспорт', 'көлік', 'ү总шылатып'],
                'ish haqi': ['ish haqi', 'maosh', 'oylik', 'ish', 'ishchi', 'maaş', 'зарплата', 'жалақы', 'жалақы', 'мааш', 'иш', 'ishlab topdim', 'topdim', 'oldim', 'qildim'],
                'biznes': ['biznes', 'savdo', 'sotish', 'sotuv', 'iş', 'бизнес', 'сауда', 'бизнес', 'сауда'],
                'investitsiya': ['investitsiya', 'invest', 'aksiya', 'obligatsiya', 'yatırım', 'инвестиция', 'инвестиция'],
                'kiyim': ['kiyim', 'ko\'ylak', 'shim', 'oyoq kiyim', 'kostyum', 'giyim', 'одежда', 'киім', 'одежда', 'киім'],
                'uy': ['uy', 'kvartira', 'kommunal', 'elektr', 'gaz', 'suv', 'ev', 'дом', 'үй', 'дом', 'үй'],
                'sog\'liq': ['sog\'liq', 'doktor', 'dori', 'shifoxona', 'tibbiyot', 'sağlık', 'здоровье', 'денсаулық', 'здоровье', 'денсаулық'],
                'ta\'lim': ['ta\'lim', 'maktab', 'universitet', 'kitob', 'kurs', 'eğitim', 'образование', 'білім', 'образование', 'білім'],
                'o\'yin-kulgi': ['o\'yin', 'kino', 'teatr', 'restoran', 'kafe', 'kulgi', 'eğlence', 'развлечение', 'көңіл-көтеру', 'развлечение', 'көңіл-көтеру']
            }
            
            transactions = []
            
            for amount in amounts:
                amount_num = float(amount.replace(',', '.'))
                
                # Kategoriyani aniqlash
                category = 'boshqa'
                description = 'mavjud emas'
                
                for cat, keywords in categories.items():
                    for keyword in keywords:
                        if keyword.lower() in text.lower():
                            category = cat
                            # Uzbek tilida description berish
                            uzbek_descriptions = {
                                'ovqat': 'ovqat uchun',
                                'transport': 'transport uchun', 
                                'ish haqi': 'ish haqi',
                                'biznes': 'biznes',
                                'investitsiya': 'investitsiya',
                                'kiyim': 'kiyim uchun',
                                'uy': 'uy uchun',
                                'sog\'liq': 'sog\'liq uchun',
                                'ta\'lim': 'ta\'lim uchun',
                                'o\'yin-kulgi': 'o\'yin-kulgi uchun'
                            }
                            description = uzbek_descriptions.get(cat, 'boshqa')
                            break
                    if category != 'boshqa':
                        break
                
                # Tranzaksiya turini aniqlash (ko'p tilli va sifatsiz matnlar uchun)
                transaction_type = 'expense'
                income_words = ['oldim', 'keldi', 'kirim', 'ish haqi', 'maosh', 'aldım', 'aldim', 'алдым', 'жалақы', 'мааш', 'жалақы', 'мааш', 'иш', 'алдым', 'келді', 'ishlab topdim', 'topdim', 'qildim', 'qozondim', 'ishladim', 'ishlash', 'pul', 'so\'m', 'dollar', 'summa', 'ish', 'ishchi', 'ishlash', 'qozonish', 'topish', 'olish', 'kiritish', 'kirim', 'daromad', 'foyda', 'qozonish', 'qozondim', 'qozondi', 'qozonish', 'qozonish', 'qozonish']
                debt_words = ['qarz', 'berdim', 'qaytardim', 'verdım', 'verdim', 'қарз', 'бердім', 'қайтардым', 'қарз', 'бердім', 'қайтардым', 'бердім', 'қайтардым']
                
                if any(word in text.lower() for word in income_words):
                    transaction_type = 'income'
                elif any(word in text.lower() for word in debt_words):
                    transaction_type = 'debt'
                
                # Tranzaksiyani saqlash
                transaction_id = await self.save_transaction(
                    user_id=user_id,
                    amount=amount_num,
                    category=category,
                    description=description,
                    transaction_type=TransactionType(transaction_type)
                )
                
                if transaction_id:
                    transactions.append({
                        'id': transaction_id,
                        'amount': amount_num,
                        'type': transaction_type,
                        'category': category,
                        'description': description
                    })
            
            if not transactions:
                return {
                    "success": False,
                    "message": "❌ Hech qanday tranzaksiya saqlanmadi."
                }
            
            # Xabar tuzish
            message = f"✅ {len(transactions)} ta tranzaksiya saqlandi!\n\n"
            
            for i, trans in enumerate(transactions, 1):
                type_emoji = {
                    "income": "📈",
                    "expense": "📉", 
                    "debt": "💳"
                }.get(trans['type'], "❓")
                
                message += f"{i}. {type_emoji} {trans['amount']:,.0f} so'm\n"
                message += f"   📂 {trans['category']}\n"
                message += f"   📝 {trans['description']}\n\n"
            
            return {
                "success": True,
                "transactions": transactions,
                "message": message
            }
            
        except Exception as e:
            logging.error(f"Fallback qayta ishlashda xatolik: {e}")
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
