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
            with open(audio_file_path, "rb") as audio_file:
                # O'zbek tilini qo'llab-quvvatlamasligi sababli bir necha usulni sinab ko'ramiz
                
                # 1-usul: O'zbek tili uchun rus tilida context
                try:
                    transcript = await self.openai_client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        language="ru",  # Rus tili - O'zbek tiliga eng yaqin
                        prompt="Финансовая информация, деньги, сом, тысяча, заработал, потратил, долг, молiyaviy ма'lumot, pul, so'm, ming, ishlab topish, sarflash, qarз, do'кон, darомad, biznes, filyal, xudoga shukur, zo'r bo'ldi, pul tushdi, daromad qildim, sarfladim, qarз oldim",
                        temperature=0.15,
                        response_format="verbose_json"
                    )
                    initial_text = transcript.text
                    logging.info(f"Rus tili bilan transkript: {initial_text}")
                    
                except Exception as e:
                    logging.warning(f"Rus tili bilan transcription xato: {e}")
                    
                    # 2-usul: Avtomatik til aniqlash
                    try:
                        # Faylni qayta o'qish
                        audio_file.seek(0)
                        transcript = await self.openai_client.audio.transcriptions.create(
                            model="whisper-1",
                            file=audio_file,
                            prompt="Financial information, money, currency, income, expense, debt, молiyavий ма'лумот, pul, so'm, ming, деньги, сом, тысяча, do'kon, daromad, biznes, filyal, xudoga shukur, zo'r bo'ldi, pul tushdi, reklamaga sarfladim, qarz berdim, qarz oldim",
                            temperature=0.15,
                            response_format="verbose_json"
                        )
                        initial_text = transcript.text
                        logging.info(f"Avtomatik til aniqlash bilan: {initial_text}")
                        
                    except Exception as e2:
                        logging.warning(f"Avtomatik til aniqlash xato: {e2}")
                        
                        # 3-usul: Ingliz tili bilan
                        audio_file.seek(0)
                        transcript = await self.openai_client.audio.transcriptions.create(
                            model="whisper-1",
                            file=audio_file,
                            language="en",
                            prompt="Financial information, money, som, thousand, earned, spent, debt, shop, income, business, branch, gratitude, amazing day, marketing spend, borrowed money",
                            temperature=0.15,
                            response_format="verbose_json"
                        )
                        initial_text = transcript.text
                        logging.info(f"Ingliz tili bilan transkript: {initial_text}")
                
                # Agar transkript bo'sh bo'lsa
                if not initial_text or len(initial_text.strip()) < 3:
                    return {
                        "success": False,
                        "message": "❌ Audio aniq eshitilmadi. Iltimos, aniqroq va balandroq gapiring."
                    }
                
                logging.info(f"Final transkript: {initial_text}")
            
            # AI orqali transkriptni to'liq yaxshilash va moliyaviy ma'lumotlarni ajratish
            return await self.process_ai_input_advanced(initial_text, user_id)
            
        except Exception as e:
            logging.error(f"Audio qayta ishlashda xatolik: {e}")
            return {
                "success": False,
                "message": "❌ Audio faylni qayta ishlashda xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring."
            }

    async def process_ai_input_advanced(self, text: str, user_id: int) -> Dict[str, Any]:
        """AI orqali matnni to'liq tahlil qilish va moliyaviy ma'lumotlarni ajratish"""
        try:
            # 1-bosqich: Transkriptni yaxshilash va to'g'rilash
            improved_text = await self._improve_transcription_with_ai(text)
            refined_text = await self._refine_transcription_context(improved_text)
            logging.info(f"Refined matn: {refined_text}")
            extract_base = refined_text if refined_text else improved_text
            logging.info(f"Yaxshilangan matn: {improved_text}")
            
            # 2-bosqich: Moliyaviy ma'lumotlarni ajratish - GPT-4 Turbo
            financial_data = await self._extract_financial_data_with_gpt4(extract_base)
            
            # 3-bosqich: Ma'lumotlarni validatsiya qilish
            validation_result = await self._validate_extracted_data(financial_data, extract_base)
            
            if not validation_result['is_valid']:
                return {
                    "success": False,
                    "message": validation_result['message']
                }
            
            # 4-bosqich: Tranzaksiyalarni tahlil qilish va ko'rsatish
            return await self._analyze_and_show_transactions(validation_result['data'], user_id, improved_text)
            
        except Exception as e:
            logging.error(f"AI qayta ishlashda xatolik: {e}")
            return {
                "success": False,
                "message": "❌ Ma'lumotni qayta ishlashda xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring."
            }

    async def _improve_transcription_with_ai(self, text: str) -> str:
        """AI orqali transkriptni yaxshilash va to'g'rilash"""
        try:
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o",  # Eng kuchli model
                messages=[
                    {
                        "role": "system",
                        "content": """Siz audio transkriptni yaxshilovchi professional yordamchi siz. 

VAZIFANGIZ:
1. Audio transkriptdagi xatolarni to'g'rilash
2. O'zbek, qozoq, rus, ingliz tillaridagi aralash so'zlarni to'g'ri o'zbek tiliga o'girish
3. Raqamlar va summalarni to'g'ri yozish (million, ming kabi)
4. Moliyaviy atamalarni to'g'ri qo'llash (daromad, xarajat, qarz, investitsiya)
5. Tabiiy nutq, emotsional iboralar va og'zaki stilni saqlab qolish
6. Bir nechta gapdan iborat nutqlarni mantiqan bo'laklab, izchil matn sifatida qaytarish

QOIDALAR:
- Barcha javoblar FAQAT O'ZBEK TILIDA
- Tabiiy nutqni saqlab qolish ("xudoga shukur", "zo'r bo'ldi", "xullas", "o'zimdan chiqdi" kabi iboralar o'z holicha qoladi)
- Raqamlarni aniq yozing (ming = 1 000, million = 1 000 000, milliard = 1 000 000 000)
- So'm, dollor, euro kabi valyutalarni to'g'ri yozing
- Moliyaviy harakatlarni aniq ifoda eting (ishlab topdim, sarfladim, qarz oldim, investitsiya qildim)
- Biznes atamalarini to'g'rilash (do'kon, filial, savdo, sotish, sotib olish, reklama)
- Emotsional ohangni saqlang, lekin keraksiz takrorlarni kamaytiring
- Faqat yaxshilangan matnni qaytaring, boshqa izoh yozmang

TABIIY NUTQ MISOLLARI:
Kirish: "двадцать пять тысяч сом ишлаб топдим"
Chiqish: "25 ming so'm ishlab topdim"

Kirish: "bugun zor boldi xudoga shukur dokonimda sakkiz yuz ming som pul tushdi, reklama ham qildim"
Chiqish: "bugun zo'r bo'ldi, xudoga shukur, do'konimda 800 ming so'm pul tushdi, reklama ham qildim"

Kirish: "үш лаптоптың алдом"  
Chiqish: "uch ta laptop sotib oldim"

Kirish: "ikki yuz ming filalimdan daromad qildim xullas, yana bir yuz ming reklama uchun ketdi"
Chiqish: "200 ming so'm filyalimdan daromad qildim, xullas, yana 100 ming so'm reklama uchun ketdi"

Kirish: "bugun juda yaxshi o'tdi, ertalab 50 ming so'm nonvoyxonadan daromad bo'ldi, kechgacha 30 mingini mahsulotga sarfladim"
Chiqish: "bugun juda yaxshi o'tdi, ertalab nonvoyxonadan 50 ming so'm daromad bo'ldi, kechgacha 30 mingini mahsulotga sarfladim"

Faqat yaxshilangan matnni bering:"""
                    },
                    {
                        "role": "user", 
                        "content": f"Bu audio transkriptni yaxshilab, to'g'ri o'zbek tiliga o'giring lekin tabiiy nutqni saqlab qoling:\n\n{text}"
                    }
                ],
                temperature=0.3,
                top_p=0.9,
                max_tokens=1200
            )
            
            improved = response.choices[0].message.content.strip()
            return improved if improved else text
            
        except Exception as e:
            logging.error(f"Transkript yaxshilashda xatolik: {e}")
            return text

    async def _refine_transcription_context(self, text: str) -> str:
        """Tabiiy nutqni chuqurroq anglash uchun qo'shimcha kontekstli qayta ishlash"""
        try:
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": """Siz moliyaviy suhbatlar bo'yicha kontekst analizchisi siz. Vazifangiz og'zaki, emotsional va aralash tilli gaplarni 100% tushunish hamda moliyaviy jihatdan mantiqli matnga aylantirish.

QOIDALAR:
- Gaplar o'rtasidagi bog'lanishni tushuning, vaqt tartibini saqlang
- "Bugun", "kecha", "ertalab" kabi vaqt ko'rsatkichlarini aniq yozing
- Emotsional iboralarni saqlang ("zo'r bo'ldi", "xudoga shukur", "hayajondaman")
- Moliyaviy harakatni aniq yozing (daromad keldi, xarajat qildim, qarz berdim)
- Agar summa aytilmagan bo'lsa, aniq summa yozmang, faqat voqeani tushuntiring
- Faqat yaxshilangan, izchil matnni qaytaring"""
                    },
                    {
                        "role": "user",
                        "content": f"Quyidagi matnni yaxshilab, mantiqiy va izchil ko'rinishga keltiring:\n\n{text}"
                    }
                ],
                temperature=0.4,
                top_p=0.9,
                max_tokens=800
            )

            refined = response.choices[0].message.content.strip()
            return refined if refined else text

        except Exception as e:
            logging.warning(f"Refine context xatolik: {e}")
            return text

    async def _extract_financial_data_with_gpt4(self, text: str) -> Dict[str, Any]:
        """GPT-4 orqali moliyaviy ma'lumotlarni ajratish - tabiiy nutqni tushunish bilan"""
        try:
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o",  # Eng kuchli model
                messages=[
                    {
                        "role": "system",
                        "content": """Siz professional moliyaviy tahlilchi AI siz. Siz tabiiy nutqni tushunasiz va hech qachon "TUSHUNMADIM" demasligingiz kerak!

KRITIK MUHIM QOIDALAR:
1. TABIIY NUTQNI TUSHUNISH - odamlar rasmiy gapirmaydi, lekin siz tushunishingiz kerak
2. HAR BIR RAQAM VA SUMMA ANIQ BO'LISHI KERAK
3. BARCHA JAVOBLAR FAQAT O'ZBEK TILIDA
4. HAR BIR TRANZAKSIYA ALOHIDA VA ANIQ AJRATILISHI KERAK
5. RAQAMLARNI TO'G'RI HISOBLANG (ming = 1000, million = 1000000)
6. BIR NECHTA DAROMAD MANBALARINI ALOHIDA TRANZAKSIYA SIFATIDA AJRATISH
7. JAMI SUMMANI HISOBGA OLMANG - faqat alohida tranzaksiyalarni ajrating

TABIIY NUTQ TUSHUNISH:
- "pul tushdi", "daromad qildim", "ishlab topdim" = income
- "sarfladim", "xarajat qildim", "sotib oldim", "to'ladim" = expense  
- "qarz oldim", "qarz berdim" = debt
- "do'konimda 800 ming pul tushdi" = 800000 so'm income biznes kategoriyasida
- "200 ming filyalimdan daromad" = 200000 so'm income biznes kategoriyasida
- "jami 1mln bo'ldi" = bu jami hisobi, alohida tranzaksiya EMAS!

TRANZAKSIYA TURLARI:
- "income" - ishlab topish, maosh olish, pul topish, daromad, kirim, pul tushdi, sotish
- "expense" - sarflash, xarajat qilish, sotib olish, to'lash, chiqim  
- "debt" - qarz olish, qarz berish

KATEGORIYALAR:
- "biznes" - do'kon, filyal, savdo, sotish, biznes daromadi
- "ish haqi" - ishlab topish, maosh, oylik, daromad (agar biznes bo'lmasa)
- "ovqat" - taom, ovqat, restoran, cafe
- "transport" - taksi, benzin, mashina, avtoubus
- "kiyim" - kiyim-kechak, poyabzal, moda
- "uy" - uy harajatlari, kommunal, remont
- "sog'liq" - shifoxona, dori, shifokor
- "ta'lim" - maktab, universitet, kitob, kurs
- "o'yin-kulgi" - kino, o'yinlar, dam olish
- "investitsiya" - investitsiya, aktsiya, biznes qo'yish
- "boshqa" - boshqa barcha xarajatlar

MUHIM MISOLLAR:
"do'konimda 800 ming so'm pul tushdi keyin 200 ming so'm filyalimdan daromad qildim" = 
2 ta ALOHIDA tranzaksiya:
1) 800000 so'm income biznes (do'kondan)
2) 200000 so'm income biznes (filyaldan)

"25 ming so'm ishlab topdim" = 25000 so'm income ish haqi
"20 ming so'm ovqatga sarfladim" = 20000 so'm expense ovqat
"100 ming so'm qarz oldim" = 100000 so'm debt boshqa

JAVOB FORMATI - faqat JSON:
{
    "transactions": [
        {
            "amount": 800000,
            "type": "income", 
            "category": "biznes",
            "description": "do'kon daromadi",
            "confidence": 0.95
        },
        {
            "amount": 200000,
            "type": "income", 
            "category": "biznes",
            "description": "filyal daromadi",
            "confidence": 0.95
        }
    ],
    "total_confidence": 0.95
}

MUHIM: 
- Har bir raqamni to'g'ri hisoblang
- Description o'zbek tilida va qisqa bo'lsin  
- Confidence 0.5 dan yuqori bo'lishi kerak
- JAMI summalarni e'tiborsiz qoldiring - faqat alohida tranzaksiyalarni ajrating
- Bir xil kontekstdagi alohida daromadlarni alohida tranzaksiya qiling
- HECH QACHON bo'sh qaytarmang, har doim kamida 1 ta tranzaksiya qaytaring"""
                    },
                    {
                        "role": "user",
                        "content": f"Bu tabiiy nutqdan moliyaviy ma'lumotlarni ajratib oling va har bir alohida daromad/xarajatni alohida tranzaksiya sifatida ko'rsating:\n\n{text}"
                    }
                ],
                temperature=0.0,
                max_tokens=2000,
                top_p=0.1
            )
            
            ai_response = response.choices[0].message.content
            logging.info(f"AI moliyaviy javob: {ai_response}")
            
            # JSON parse qilish
            try:
                # JSON ni tozalash
                ai_response = ai_response.strip()
                if '```json' in ai_response:
                    ai_response = ai_response.split('```json')[1].split('```')[0]
                elif '```' in ai_response:
                    ai_response = ai_response.split('```')[1]
                
                data = json.loads(ai_response)
                return data
                
            except json.JSONDecodeError as e:
                logging.error(f"JSON parse xatolik: {e}")
                return {"transactions": [], "total_confidence": 0}
                
        except Exception as e:
            logging.error(f"Moliyaviy ma'lumot ajratishda xatolik: {e}")
            return {"transactions": [], "total_confidence": 0}

    async def _validate_extracted_data(self, data: Dict[str, Any], original_text: str) -> Dict[str, Any]:
        """Ajratilgan ma'lumotlarni validatsiya qilish"""
        try:
            # Confidence tekshirish - har doim qabul qilamiz
            total_confidence = data.get('total_confidence', 0)
            # Hech qachon rad etmaymiz, har doim taxmin qilamiz
            # Agar confidence 0 bo'lsa ham, 0.3 qilib qo'yamiz
            if total_confidence == 0:
                total_confidence = 0.3
            
            transactions = data.get('transactions', [])
            if not transactions:
                # Agar tranzaksiya yo'q bo'lsa, fallback qo'shamiz
                transactions = [{
                    "amount": 0,
                    "type": "expense",
                    "category": "boshqa",
                    "description": f"Noaniq kiritish: {original_text[:30]}",
                    "confidence": 0.3
                }]
                data['transactions'] = transactions
                data['total_confidence'] = 0.3
            
            # Har bir tranzaksiyani validatsiya qilish
            validated_transactions = []
            
            for trans in transactions:
                # Amount validatsiya - 0 ham qabul qilamiz
                amount = trans.get('amount', 0)
                if not isinstance(amount, (int, float)):
                    amount = 0
                
                if amount > 10000000000:  # 10 milliard dan ko'p
                    continue
                    
                # Type validatsiya
                trans_type = trans.get('type', '')
                if trans_type not in ['income', 'expense', 'debt']:
                    continue
                
                # Category validatsiya
                category = trans.get('category', 'boshqa')
                valid_categories = [
                    'ovqat', 'transport', 'ish haqi', 'biznes', 'investitsiya',
                    'kiyim', 'uy', 'sog\'liq', 'ta\'lim', 'o\'yin-kulgi', 'boshqa'
                ]
                if category not in valid_categories:
                    category = 'boshqa'
                
                # Description validatsiya  
                description = trans.get('description', '').strip()
                if not description:
                    description = 'Tavsif kiritilmagan'
                elif len(description) > 100:
                    description = description[:100]
                
                # Confidence validatsiya - har doim qabul qilamiz
                trans_confidence = trans.get('confidence', 0)
                # Hech qachon rad etmaymiz, har doim taxmin qilamiz
                
                validated_transactions.append({
                    'amount': float(amount),
                    'type': trans_type,
                    'category': category,
                    'description': description,
                    'confidence': trans_confidence
                })
            
            if not validated_transactions:
                return {
                    'is_valid': False,
                    'message': "❌ Hech qanday to'g'ri tranzaksiya topilmadi. Iltimos, aniqroq yozing.\n\nMisol: 'Bugun do'konimda 500 ming so'm pul tushdi'"
                }
            
            return {
                'is_valid': True,
                'data': {'transactions': validated_transactions}
            }
            
        except Exception as e:
            logging.error(f"Validatsiya xatoligi: {e}")
            return {
                'is_valid': False,
                'message': "❌ Ma'lumotni validatsiya qilishda xatolik yuz berdi."
            }

    async def _analyze_and_show_transactions(self, data: Dict[str, Any], user_id: int, original_text: str) -> Dict[str, Any]:
        """Tranzaksiyalarni tahlil qilish va foydalanuvchiga ko'rsatish"""
        try:
            transactions = data.get('transactions', [])
            
            # Tranzaksiyalarni aniqlik darajasiga qarab ajratish
            confirmed_transactions = []  # Confidence >= 0.7
            suspected_transactions = []   # Confidence 0.4-0.69
            unclear_transactions = []     # Confidence < 0.4
            
            for i, transaction_data in enumerate(transactions):
                confidence = transaction_data.get('confidence', 0)
                
                trans_item = {
                    'index': i + 1,
                    'data': transaction_data,
                    'id': f"trans_{user_id}_{i}_{int(datetime.now().timestamp())}"
                }
                
                if confidence >= 0.7:
                    trans_item['status'] = 'confirmed'
                    confirmed_transactions.append(trans_item)
                elif confidence >= 0.4:
                    trans_item['status'] = 'suspected'
                    suspected_transactions.append(trans_item)
                else:
                    trans_item['status'] = 'unclear'
                    unclear_transactions.append(trans_item)
            
            # Agar hech qanday tranzaksiya yo'q bo'lsa, AI ga qaytadan so'ramiz
            if not (confirmed_transactions or suspected_transactions or unclear_transactions):
                # AI ga qaytadan so'ramiz - har doim taxmin qilishi kerak
                return await self._force_ai_analysis(original_text, user_id)
            
            # Agar faqat aniq tranzaksiyalar bo'lsa
            if confirmed_transactions and not suspected_transactions and not unclear_transactions:
                if len(confirmed_transactions) == 1:
                    return await self._show_single_transaction_confirmation(confirmed_transactions[0], user_id)
                else:
                    # Bir nechta aniq tranzaksiya bo'lsa
                    return await self._show_multiple_confirmed_transactions(confirmed_transactions, user_id, original_text)
                
            # Agar bir nechta tranzaksiya bo'lsa yoki taxminiy/noaniq tranzaksiyalar bo'lsa
            return await self._show_multiple_transactions_preview(
                confirmed_transactions, 
                suspected_transactions, 
                unclear_transactions, 
                user_id, 
                original_text
            )
            
        except Exception as e:
            logging.error(f"Tranzaksiyalarni tahlil qilishda xatolik: {e}")
            return {
                "success": False,
                "message": "❌ Tranzaksiyalarni tahlil qilishda xatolik yuz berdi."
            }

    async def _show_multiple_confirmed_transactions(self, confirmed_transactions: list, user_id: int, original_text: str) -> Dict[str, Any]:
        """Bir nechta aniq tranzaksiyalar uchun tasdiqlash"""
        try:
            message = f"✅ **{len(confirmed_transactions)} ta aniq tranzaksiya aniqlandi!**\n\n"
            
            total_income = 0
            total_expense = 0
            total_debt = 0
            
            for item in confirmed_transactions:
                trans = item['data']
                
                type_emoji = {
                    "income": "📈",
                    "expense": "📉",
                    "debt": "💳"
                }.get(trans['type'], "❓")
                
                message += f"{item['index']}. {type_emoji} **{trans['amount']:,.0f} so'm**\n"
                message += f"   📂 {trans['category']}\n"
                message += f"   📝 {trans['description']}\n"
                message += f"   🎯 {trans['confidence']:.1%}\n\n"
                
                # Jami hisobga qo'shish
                if trans['type'] == 'income':
                    total_income += trans['amount']
                elif trans['type'] == 'expense':
                    total_expense += trans['amount'] 
                elif trans['type'] == 'debt':
                    total_debt += trans['amount']
            
            # Jami ko'rsatish
            if total_income > 0:
                message += f"💰 **Jami kirim:** +{total_income:,.0f} so'm\n"
            if total_expense > 0:
                message += f"💸 **Jami chiqim:** -{total_expense:,.0f} so'm\n"
            if total_debt > 0:
                message += f"💳 **Jami qarz:** {total_debt:,.0f} so'm\n"
            
            message += "\nBarcha tranzaksiyalarni saqlashni xohlaysizmi?"
            
            return {
                "success": True,
                "type": "multiple_confirmed",
                "message": message,
                "transaction_data": {
                    'transactions': confirmed_transactions,
                    'user_id': user_id
                }
            }
            
        except Exception as e:
            logging.error(f"Ko'p aniq tranzaksiyalar ko'rsatishda xatolik: {e}")
            return {
                "success": False,
                "message": "❌ Tranzaksiyalarni ko'rsatishda xatolik yuz berdi."
            }

    async def _force_ai_analysis(self, text: str, user_id: int) -> Dict[str, Any]:
        """AI ga majburiy tahlil qilish - har doim taxmin qilishi kerak"""
        try:
            # AI ga qaytadan so'ramiz - bu safar har doim javob berishi kerak
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": """Siz moliyaviy yordamchi AI siz. SIZ HECH QACHON "TUSHUNMADIM" DEMASLIGINGIZ KERAK!

MUHIM QOIDALAR:
1. Foydalanuvchi har qanday gapirsa ham, siz HAR DOIM moliyaviy ma'lumot toping
2. Agar noaniq gapirsa, uning gapiga yaqin ma'lumotni taxmin qiling
3. Har qanday matnni moliyaviy tranzaksiyaga aylantiring
4. Tabiiy nutqni tushunish - "zo'r bo'ldi", "xudoga shukur", "pul tushdi" kabi
5. Agar aniq bo'lmasa, "boshqa" kategoriyasida saqlang
6. Har doim kamida 1 ta tranzaksiya qaytaring
7. Confidence har doim 0.5 dan yuqori bo'lsin
8. Raqamlarni to'g'ri tushuning: "25 ming" = 25000, "100 ming" = 100000, "1 mln" = 1000000
9. "Ishlab topdim", "pul tushdi", "daromad qildim" = income
10. "xarajat", "sarfladim", "sotib oldim" = expense
11. "qarz" = debt

MISOL:
- "Salom" → 0 so'm boshqa kategoriya, "Salomlashish" tavsifi
- "Tushunmadim" → 0 so'm boshqa kategoriya, "Noaniq kiritish" tavsifi
- "25 ming ishlab topdim" → 25000 so'm income, "ish haqi" kategoriya
- "100 ming xarajat" → 100000 so'm expense, "boshqa" kategoriya
- "bugun zo'r bo'ldi xudoga shukur do'konimda pul tushdi" → taxminan 50000-100000 so'm income biznes kategoriyada

JSON formatida qaytaring:
{
    "transactions": [
        {
            "amount": 25000,
            "type": "income", 
            "category": "ish haqi",
            "description": "ishlab topish",
            "confidence": 0.8
        }
    ],
    "total_confidence": 0.8
}"""
                    },
                    {
                        "role": "user", 
                        "content": f"Bu matnni tahlil qiling va har qanday holatda ham moliyaviy tranzaksiya toping: {text}"
                    }
                ],
                max_tokens=1000,
                temperature=0.7,
                frequency_penalty=0.1,
                presence_penalty=0.1
            )
            
            ai_response = response.choices[0].message.content.strip()
            logging.info(f"Force AI response: {ai_response}")
            
            # JSON ni parse qilish
            try:
                data = json.loads(ai_response)
            except json.JSONDecodeError:
                # Agar JSON bo'lmasa, fallback
                data = {
                    "transactions": [{
                        "amount": 0,
                        "type": "expense",
                        "category": "boshqa", 
                        "description": f"Noaniq kiritish: {text[:50]}",
                        "confidence": 0.2
                    }],
                    "total_confidence": 0.2
                }
            
            # Validatsiya
            validation_result = await self._validate_extracted_data(data, text)
            if not validation_result['is_valid']:
                # Agar validatsiya o'tmasa ham, majburiy saqlash
                data = {
                    "transactions": [{
                        "amount": 0,
                        "type": "expense",
                        "category": "boshqa",
                        "description": f"Noaniq kiritish: {text[:50]}",
                        "confidence": 0.1
                    }],
                    "total_confidence": 0.1
                }
            
            # Tranzaksiyalarni ko'rsatish
            return await self._analyze_and_show_transactions(data, user_id, text)
            
        except Exception as e:
            logging.error(f"Force AI analysis xatolik: {e}")
            # Oxirgi fallback - har doim bitta tranzaksiya
            fallback_data = {
                "transactions": [{
                    "amount": 0,
                    "type": "expense",
                    "category": "boshqa",
                    "description": f"Xatolik: {text[:30]}",
                    "confidence": 0.1
                }],
                "total_confidence": 0.1
            }
            return await self._analyze_and_show_transactions(fallback_data, user_id, text)

    async def _show_single_transaction_confirmation(self, transaction_item: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        """Bitta aniq tranzaksiya uchun tasdiqlash"""
        try:
            trans = transaction_item['data']
            
            type_emoji = {
                "income": "📈 Kirim",
                "expense": "📉 Chiqim", 
                "debt": "💳 Qarz"
            }.get(trans['type'], "❓")
            
            message = f"💡 *Tranzaksiya aniqlandi*\n\n"
            message += f"{type_emoji}: **{trans['amount']:,.0f} so'm**\n"
            message += f"📂 Kategoriya: {trans['category']}\n"
            message += f"📝 Tavsif: {trans['description']}\n"
            message += f"🎯 Aniqlik: {trans['confidence']:.1%}\n\n"
            message += "Tranzaksiyani saqlashni xohlaysizmi?"
            
            return {
                "success": True,
                "type": "single_confirmation",
                "message": message,
                "transaction_data": {
                    'transactions': [transaction_item],
                    'user_id': user_id
                }
            }
            
        except Exception as e:
            logging.error(f"Bitta tranzaksiya ko'rsatishda xatolik: {e}")
            return {
                "success": False,
                "message": "❌ Tranzaksiyani ko'rsatishda xatolik yuz berdi."
            }

    async def _show_multiple_transactions_preview(self, confirmed: list, suspected: list, unclear: list, user_id: int, original_text: str) -> Dict[str, Any]:
        """Bir nechta tranzaksiyalar uchun oldindan ko'rinish"""
        try:
            # Barcha tranzaksiyalarni birlashtirish
            all_transactions = confirmed + suspected + unclear
            all_transactions.sort(key=lambda x: x['index'])
            
            message = "📋 *Aniqlangan tranzaksiyalar*\n\n"
            
            # Har bir tranzaksiyani ko'rsatish
            for item in all_transactions:
                trans = item['data']
                status = item['status']
                
                type_emoji = {
                    "income": "📈",
                    "expense": "📉",
                    "debt": "💳"
                }.get(trans['type'], "❓")
                
                # Status belgisi
                if status == 'confirmed':
                    status_emoji = "✅"
                elif status == 'suspected': 
                    status_emoji = "⚠️"
                else:
                    status_emoji = "❓"
                
                message += f"{item['index']}. {status_emoji} {type_emoji} **{trans['amount']:,.0f} so'm**\n"
                message += f"   📂 {trans['category']}\n"
                message += f"   📝 {trans['description']}\n"
                
                # Status izoh
                if status == 'suspected':
                    message += f"   💭 *Taxminiy:* Bu ma'lumot taxminiy, agar xato bo'lsa, o'chirib tashlang!\n"
                elif status == 'unclear':
                    message += f"   ⚠️ *Noaniq:* Ushbu ma'lumot taxminiy va aniq emas.\n"
                
                message += "\n"
            
            # Tugmalar uchun ma'lumot
            buttons_data = {
                'confirmed_count': len(confirmed),
                'suspected_count': len(suspected), 
                'unclear_count': len(unclear),
                'total_count': len(all_transactions),
                'transactions': all_transactions,
                'user_id': user_id,
                'original_text': original_text
            }
            
            return {
                "success": True,
                "type": "multiple_preview",
                "message": message,
                "buttons_data": buttons_data
            }
            
        except Exception as e:
            logging.error(f"Ko'p tranzaksiyalar ko'rsatishda xatolik: {e}")
            return {
                "success": False,
                "message": "❌ Tranzaksiyalarni ko'rsatishda xatolik yuz berdi."
            }

    async def save_confirmed_transactions(self, transaction_items: list, user_id: int) -> Dict[str, Any]:
        """Tasdiqlangan tranzaksiyalarni saqlash"""
        try:
            saved_transactions = []
            failed_transactions = []
            
            for item in transaction_items:
                trans = item['data']
                try:
                    transaction_id = await self.save_transaction(
                        user_id=user_id,
                        amount=trans['amount'],
                        category=trans['category'],
                        description=trans['description'],
                        transaction_type=TransactionType(trans['type'])
                    )
                    
                    if transaction_id:
                        saved_transactions.append({
                            'id': transaction_id,
                            'index': item['index'],
                            'amount': trans['amount'],
                            'type': trans['type'],
                            'category': trans['category'],
                            'description': trans['description'],
                            'confidence': trans.get('confidence', 0)
                        })
                    else:
                        failed_transactions.append(item['index'])
                        
                except Exception as e:
                    logging.error(f"Tranzaksiya {item['index']} saqlashda xatolik: {e}")
                    failed_transactions.append(item['index'])
            
            # Xabar tuzish
            if not saved_transactions:
                return {
                    "success": False,
                    "message": "❌ Hech qanday tranzaksiya saqlanmadi."
                }
            
            message = f"✅ **{len(saved_transactions)} ta tranzaksiya saqlandi!**\n\n"
            
            total_income = 0
            total_expense = 0
            total_debt = 0
            
            for trans in saved_transactions:
                type_emoji = {
                    "income": "📈",
                    "expense": "📉",
                    "debt": "💳"
                }.get(trans['type'], "❓")
                
                message += f"#{trans['index']} {type_emoji} {trans['amount']:,.0f} so'm - {trans['category']}\n"
                
                # Jami hisobga qo'shish
                if trans['type'] == 'income':
                    total_income += trans['amount']
                elif trans['type'] == 'expense':
                    total_expense += trans['amount'] 
                elif trans['type'] == 'debt':
                    total_debt += trans['amount']
            
            # Jami ko'rsatish - faqat 1 tadan ko'p bo'lsa
            if len(saved_transactions) > 1:
                if total_income > 0:
                    message += f"\n💰 Jami kirim: +{total_income:,.0f} so'm"
                if total_expense > 0:
                    message += f"\n💸 Jami chiqim: -{total_expense:,.0f} so'm"
                if total_debt > 0:
                    message += f"\n💳 Jami qarz: {total_debt:,.0f} so'm"
            
            # Xato bo'lgan tranzaksiyalar haqida
            if failed_transactions:
                message += f"\n\n⚠️ #{', #'.join(map(str, failed_transactions))} tranzaksiyalar saqlanmadi."
            
            return {
                "success": True,
                "message": message,
                "saved_count": len(saved_transactions),
                "failed_count": len(failed_transactions),
                "transactions": saved_transactions
            }
            
        except Exception as e:
            logging.error(f"Tranzaksiyalarni saqlashda xatolik: {e}")
            return {
                "success": False,
                "message": "❌ Tranzaksiyalarni saqlashda xatolik yuz berdi."
            }

    async def process_ai_input(self, text: str, user_id: int) -> Dict[str, Any]:
        """Matnli kiritish uchun - ham audio ham matn uchun umumiy"""
        return await self.process_ai_input_advanced(text, user_id)
    
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

    # Callback handler va qolgan funksiyalar
    async def handle_transaction_action(self, callback_data: str, user_id: int, transaction_data: Dict[str, Any]) -> Dict[str, Any]:
        """Tranzaksiya tugmalari bosilganda ishlov berish"""
        try:
            action_parts = callback_data.split('_')
            action = action_parts[1]
            
            if action == "save" and len(action_parts) == 3:
                trans_index = int(action_parts[2]) - 1
                transactions = transaction_data.get('transactions', [])
                
                if trans_index < len(transactions):
                    result = await self.save_confirmed_transactions([transactions[trans_index]], user_id)
                    return result
            
            elif action == "all":
                transactions = transaction_data.get('transactions', [])
                result = await self.save_confirmed_transactions(transactions, user_id)
                result['type'] = 'completed'
                return result
            
            elif action == "single":
                transactions = transaction_data.get('transactions', [])
                if transactions:
                    result = await self.save_confirmed_transactions([transactions[0]], user_id)
                    result['type'] = 'completed'
                    return result
            
            elif action == "cancel":
                return {
                    "success": True,
                    "message": "❌ Barcha tranzaksiyalar bekor qilindi.",
                    "type": "completed"
                }
            
            return {
                "success": False,
                "message": "❌ Noto'g'ri amal."
            }
                
        except Exception as e:
            logging.error(f"Tranzaksiya amali ishlov berishda xatolik: {e}")
            return {
                "success": False,
                "message": "❌ Amal bajarilmadi."
            }

    # Balance va reporting funksiyalari
    async def get_user_balance(self, user_id: int) -> Dict[str, float]:
        """Foydalanuvchi balansini hisoblash"""
        try:
            # Kirimlar
            income_query = "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE user_id = %s AND transaction_type = 'income'"
            income_result = await db.execute_one(income_query, (user_id,))
            total_income = income_result[0] if income_result else 0.0
            
            # Chiqimlar
            expense_query = "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE user_id = %s AND transaction_type = 'expense'"
            expense_result = await db.execute_one(expense_query, (user_id,))
            total_expense = expense_result[0] if expense_result else 0.0
            
            # Qarzlar
            debt_query = "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE user_id = %s AND transaction_type = 'debt'"
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

    def generate_transaction_buttons(self, transactions_data: Dict[str, Any]) -> list:
        """Tranzaksiyalar uchun tugmalarni yaratish"""
        try:
            transactions = transactions_data.get('transactions', [])
            transaction_type = transactions_data.get('type', 'multiple_preview')
            
            if transaction_type == 'single_confirmation':
                return [
                    [
                        {"text": "💾 Saqlash", "callback_data": "trans_single"},
                        {"text": "🗑️ Bekor qilish", "callback_data": "trans_cancel"}
                    ]
                ]
            
            elif transaction_type == 'multiple_confirmed':
                return [
                    [
                        {"text": "✅ Hammasini saqlash", "callback_data": "trans_all"},
                        {"text": "❌ Bekor qilish", "callback_data": "trans_cancel"}
                    ]
                ]
            
            else:  # multiple_preview
                buttons = []
                
                # Har bir tranzaksiya uchun alohida tugmalar
                for item in transactions:
                    index = item['index']
                    status = item.get('status', 'confirmed')
                    
                    if status == 'confirmed':
                        status_icon = "✅"
                    elif status == 'suspected':
                        status_icon = "⚠️"
                    else:
                        status_icon = "❓"
                    
                    buttons.append([
                        {"text": f"💾 {status_icon} #{index}", "callback_data": f"trans_save_{index}"},
                        {"text": f"🗑️ #{index}", "callback_data": f"trans_delete_{index}"}
                    ])
                
                # Umumiy tugmalar
                buttons.append([
                    {"text": "✅ Hammasini saqlash", "callback_data": "trans_all"},
                    {"text": "❌ Hammasini bekor qilish", "callback_data": "trans_cancel"}
                ])
                
                return buttons
            
        except Exception as e:
            logging.error(f"Tugmalar yaratishda xatolik: {e}")
            return []