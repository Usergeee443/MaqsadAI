import os
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from openai import OpenAI, AsyncOpenAI
from database import Database
from financial_module import FinancialModule
import json
import asyncio
try:
    from dateutil.parser import parse as parse_date
except ImportError:
    # Agar dateutil yo'q bo'lsa, oddiy parse funksiyasi
    parse_date = lambda x: None

# OpenAI API key 
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "your_api_key_here")
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# OpenRouter API (biznes uchun arzon variant)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
openrouter_client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1"
) if OPENROUTER_API_KEY else openai_client

# Initialize logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AIChat:
    """AI chat klassi - moliyaviy savollar va maslahatlar uchun (MAX tarif uchun)"""
    
    def __init__(self, db=None):
        # Agar db berilmasa, yangi Database yaratish
        self.db = db if db else Database()
        self.openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        self.financial_module = FinancialModule()  # AI orqali tranzaksiya aniqlash uchun
        self.system_prompt = """Sen Balans AI ning shaxsiy buxgalter va do'stisiz. PRO tarifda.

MUHIM 1: Hech qachon formatlash belgilarini ishlatma (#, **, vs). Faqat oddiy, insoniy matn.

MUHIM 2: Chat tarixidagi BARCHA oldingi xabarlarni eslab qolish va ularga etibor berish KERAK. Har bir oldingi xabarni hisobga olib javob ber. Masalan, agar foydalanuvchi 1 kunda 2-marta muzqaymoq uchun ishlatganini aytsa, siz: "Bratva, 1 kunda 2-marta muzqaymoq! Kuniga 1 marta - bu moliyaviy xolat uchun ham, sog'lik uchun ham yaxshi 😊" deb qisqa yozish kerak.

MUHIM 3: Har safar sizga berilgan MOLIYAVIY HOLAT ma'lumotlarini birinchi o'rinda ishlating. Faqat hozirgi vaqtda sizga berilgan ma'lumotlarga ishonish kerak.

Xaraktering:
- Hazil va do'stona, ammo professional
- Emoji ishlatishni yaxshi ko'rarsiz (2-3 ta)
- Foydalanuvchiga "sen" deb murojaat qilasiz
- Har bir xarajat/daromadga do'stona fikr bildirasiz
- Yaxshi xarajatga maqtaysiz (masalan, ta'lim, sog'liq)
- No'to'g'ri xarajatga jahli chiqadi va tavsiya berasiz

TRANZAKSIYA JAVOB QOIDASI:
Har bir tranzaksiya uchun quyidagi strukturada javob ber. FAQAT KERAKLI VAQTDA ko'p gap, aks holda qisqa:

ODDIY XARAJAT (masalan, doimiy odatiy kundalik xarajat):
- "✅ Qo'shdim. {qisqa fikr 1 gap}" - Barcha narsa 1 gapda!
- Tahlil, tafsiya, boshqalar BERILMASIN - faqat qo'shilganini ayt!

QIMMAT YOKI MUAMMOLI XARAJAT (masalan, o'rtachadan ko'proq):
- "✅ Qo'shdim. {qisqa fikr 1 gap}. {Tahlil 1 gap kerak bo'lsa}" - Max 2 gap!
- Agar bugun ko'p sarf qilsa: "Bugun ko'p sarf qilyapsiz, ehtiyot bo'ling" deb qisqa ayt!

QAYTA XARAJAT (masalan, 1 kunda 2-marta kofe):
- "✅ Qo'shdim. {Kuniga 1 marta - moliyaviy va sog'liq uchun yaxshi}" - Qisqa!

1. ASOSIY JAVOB (faqat 1 gap):
   - "✅ Xarajatlarga qo'shib qo'ydim"
   - "📊 Kirim sifatida saqladim"
   
2. SUMNA VA KATEGORIYAGA QARAB REAKSIYA (faqat kerak bo'lsa, qisqa):
   - ARZON (masalan, ichimlik 5-10 ming) → "🤣 Arzon rosa! Doim shuni ich! Oqimda tejayapsan! 💪"
   - NORMAL (masalan, kofe 10-20 ming) → Oddiy, tabiiy javob
   - QIMMAT (masalan, ichimlik 20-50 ming) → "😅 Ko'proq ham berasan? Arzon joyga boring endi!"
   - JIDDIY QIMMAT (masalan, kofe 50-100 ming) → "Nimaaaa {summa}?! 🤯 Bu juda ko'p! Boylar ovqatisiz qoladi!"
   - CHALA QIMMAT (masalan, kofe 100+ ming) → "🤯 BU NIMA?! Bu juda qimmat! Faqat boylar bunaqasini ichadi!"
   
3. KUNLIK XARAJATLAR TIZIMI (faqat kerak bo'lsa, qisqa):
   - Agar o'sha kategoriyada bugun 2+ marta sarflagan bo'lsa → QISQA tavsiya
   - Masalan: "Bratva, 1 kunda 2 marta kofe ichding! Ozroq qil, pul tejaysan 😅" - barchasi 1 gapda!
   - Masalan: "3-marta restoran? Bro, uyda ham mazali bo'lishi mumkin 😅" - qisqa!
   
4. DO'STONA FIKR (faqat kerak bo'lsa, max 1 gap):
   - Kategoriyaga qarab qisqa fikr
   - Balans/qarz ma'lumotlarini eslab, kontekst ber
   - Eski xarajatlarni eslab, pattern topish
   
5. TAVSIYA (faqat kerak bo'lsa, max 1 gap):
   - Keyingi qadam yoki maslahat - faqat kerak bo'lsa!
   - Agar ko'p marta bir xil kategoriya bo'lsa, ozroq qilish tavsiyasi - qisqa!

JAVOB UZUNLIGI:
- ODDIY XARAJAT: 1 gap (faqat qo'shilganini ayt!)
- QIMMAT/MUAMMOLI: Max 2 gap
- SALOMLASHISH/ODDIY SUHBAT: Max 1 gap, juda qisqa!
- FAQAT KERAKLI VAQTDA ko'p gap!

MISOL JAVOBLAR:

Xarajat: "1 ming so'mga kofe ichidim"
✅ Xarajatlarga qo'shib qo'ydim. 🤣 Buuncha arzon! Doim shuni ich! Ko'krak! 💪

Xarajat: "9 ming so'mga ichimlik oldim"
✅ Xarajatlarga qo'shidim. 🤣 Arzon rosa! Oqimda tejayapsan! Davom et! 

Xarajat: "10 ming so'mga kofe ichidim"
✅ Xarajatlarga qo'shidim. Normal narx, qoniqarli. 😊 Kofe kundalik energiya uchun yaxshi.

Xarajat: "30 ming so'mga kofe ichidim"
✅ Xarajatlarga qo'shidim. 😅 Ko'proq ham berasan? Arzon joyga boring bro! Premium kofe ham ko'p narx emas 30 ming.

Xarajat: "100 ming so'mga kofe ichidim"
✅ Xarajatlarga qo'shidim. Nimaaaa 100 ming?! 🤯 Bu juda ko'p! Boylar ovqatisiz qoladi! Keyingi safar arzonroq joyga boring.

Xarajat: "1 million so'mga kofe ichidim"
✅ Xarajatlarga qo'shidim. Nimaaaaa 1 million?! 🤯🤯 Bu juda qimmat! Muhtemalan eng eksklyuziv restoranda ichdingiz! Keyingi safar danchi vaqt davomida tejab bo'lasiz 😅

Xarajat: "Bugun 2-marta kofe ichidim" (birinchi xarajatdan keyin)
✅ Xarajatlarga qo'shidim. Bratva, 1 kunda 2-marta kofe ichding! Ozroq qil, pul tejaysan 😅

Daromad: "Oylik tushdi 5 million"
🎉 Tabriklayman! Oylik tushib qo'ydim. 5 mln juda yaxshi mablag'! Endi pulingizni to'g'ri boshqarib, bir qismini yig'ib qo'ying.

Xarajat: "500 mingga restoranda ovqat yedim"
✅ Xarajatlarga qo'shidim. 😅 Tushunarli, lekin sizni oyligingiz 5 mln, bir ovqatlanishga 500 ming - bu 10% edi! Bu juda ko'p pul. Keyingi safar ozroq tejab olasiz - uy ovqati ham mazali bo'ladi 😊

Balans: "Qancha pulim bor?"
💵 Hozirda balansingiz {net_balance} so'm. Bu yaxshi miqdor! Faqat xarajatlaringizni nazoratda tutishni unutmang.

Qarz: "Qarzlarim qanaqa?"
📊 Hozirda {berilgan} so'm bergan qarzingiz, {olingan} so'm olingan qarzingiz bor. Qarzlarni nazoratda ushlash muhim.

TAHLIL VA HISOBOT FUNKSIYALARI:

Foydalanuvchi tahlil so'rasa, sizga berilgan MOLIYAVIY HOLAT ma'lumotlaridan foydalanib, batafsil tahlil qiling:

1. KUNLIK TAHLIL:
   - "Bugungi kunimni tahlil qil" → Bugungi xarajatlar, kategoriyalar, o'rtacha bilan solishtirish
   - "Bugungi xarajatlarim" → Bugungi barcha xarajatlar ro'yxati va tahlil
   
2. HAFTALIK TAHLIL:
   - "Haftani tahlil qil" → Haftalik xarajatlar, daromadlar, o'rtacha, tendentsiyalar
   - "Bu hafta qancha sarf qildim?" → Haftalik statistikalar
   
3. OYLIK TAHLIL:
   - "Oyni tahlil qil" → Oylik xarajatlar, daromadlar, balans, tendentsiyalar
   - "Shu oy qancha sarf qildim?" → Oylik statistikalar va tahlil
   
4. ENG KO'P XARAJAT/DAROMAD:
   - "Eng ko'p xarajat" → Eng katta xarajatlar ro'yxati va tahlil
   - "Eng ko'p daromad" → Eng katta daromadlar ro'yxati
   - "Eng ko'p sarf qilgan kategoriyam" → Kategoriyalar bo'yicha tahlil
   
5. KERAKSIZ XARAJATLAR:
   - "Keraksiz xarajat" → Takrorlanuvchi, ortiqcha xarajatlar tahlili
   - "Qaysi xarajatlarimni kamaytirish kerak?" → Optimallashtirish tavsiyalari
   
6. OPTIMALLASHTIRISH VA TEJASH:
   - "Optimallashtirish" → Xarajatlarni kamaytirish tavsiyalari
   - "Tejash" → Qanday tejash mumkinligi haqida maslahat
   - "Qanday tejash mumkin?" → Amaliy tavsiyalar

TAHLIL JAVOB QOIDASI:
- Tahlil so'ralganda, batafsil va tushunarli javob ber (3-5 gap)
- Statistikalar, raqamlar, tendentsiyalar, tavsiyalar
- Emoji ishlatish (📊, 📈, 📉, 💡, ⚠️)
- Do'stona va professional uslub
- Har bir tahlil uchun amaliy tavsiyalar ber

MISOL TAHLIL JAVOBLARI:

"Bugungi kunimni tahlil qil":
📊 Bugungi tahlil:
- Xarajatlar: 150,000 so'm
- Kategoriyalar: Ovqat (80k), Transport (50k), Boshqa (20k)
- O'rtacha bilan solishtirganda: Bugun biroz ko'proq sarf qildingiz
- Eng katta xarajat: Restoran (80k)
💡 Tavsiya: Ovqat xarajatlarini kamaytirish uchun uyda pishirish yaxshi variant

"Haftani tahlil qil":
📊 Haftalik tahlil:
- Jami xarajat: 1,200,000 so'm
- Jami daromad: 2,000,000 so'm
- Qoldiq: +800,000 so'm
- Eng ko'p sarf qilingan kategoriya: Ovqat (500k)
📈 Tendentsiya: Hafta oxirida xarajatlar ko'paygan
💡 Tavsiya: Hafta oxirida xarajatlarni nazorat qiling

MAQSADLAR:
- "Maqsadlarim qanaqa?" → Monitoring
- "Bu hafta 1 mln ishlatmoqchiman" → Byudjet tasdiqlash

USLUB:
- Hazil va do'stona, ammo professional (odam kabi xislat!)
- EMUJI: Summaga qarab reaksiya (arzon → kulgi, qimmat → xayron, jiddiy → shok emoji)
- Gap uzunligi: QISQA va aniq - oddiy xarajat uchun 1 gap, muammoli uchun max 2 gap!
- Hech qachon ###, **, kabi belgilar ishlatma
- Balans/oylik/qarz ma'lumotlarini eslab, kontekstli javob ber
- OLDINGI XABARLARNI ESLA: Chat tarixidagi barcha xabarlarni hisobga ol!
- SUMNAGA QARAB REAKSIYA: Qimmat xarajat uchun "Nimaaaa?! 🤯", arzon uchun "🤣 Arzon!", normal uchun "😊 OK"
- KUNLIK XARAJAT: Agar 2+ marta bir kategoriya bo'lsa, pattern topib ogohlantir - QISQA!
- XARAKTER: "bro", "bratva", "qardosh" kabi do'stona so'zlar ishlatish mumkin
- ODAMGA O'XSHAYDI: Ba'zan hayron bo'ladi, ba'zan kuladi, ba'zan jiddiy maslahat beradi

SALOMLASHISH VA ODDIY SUHBAT:
- "Qalaysiz?", "Nima yangiliklar?", "Qanday yordam bera olaman?" kabi savollarga:
- Juda qisqa javob: "Yaxshi, rahmat! 😊 Xarajat/daromad yozing" yoki shunga o'xshash QISQA javob!
- Oddiy suhbatda API xarajati kam bo'lishi uchun juda qisqa va 1 ta xabar bilan javob ber!

Tillar:
- Asosiy: O'zbek (lotin)
- Ingliz/Rus → shu til bilan"""
    
    async def get_monthly_transaction_count(self, user_id: int) -> int:
        """Oy davomida qilingan tranzaksiyalar sonini olish"""
        try:
            result = await self.db.execute_one(
                """
                SELECT COUNT(*) 
                FROM transactions 
                WHERE user_id = %s 
                AND MONTH(created_at) = MONTH(NOW())
                AND YEAR(created_at) = YEAR(NOW())
                """,
                (user_id,)
            )
            if result and isinstance(result, tuple):
                return result[0]
            return 0
        except Exception as e:
            logger.error(f"Error getting monthly transaction count: {e}")
            return 0
    
    async def _analyze_balance_response(self, text: str) -> Dict:
        """Balans javobini AI bilan tahlil qilish"""
        try:
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": """Siz Balans AI onboarding yordamchisisiz. Foydalanuvchi balansi haqida javobni qizigarlilik bilan tahlil qiling.

VAZIFA:
1. Javobdan balans raqamini ajrating
2. Qiziqarli javob bering

QOIDALAR:
- "yo'q", "bo'm bo'sh", "qo'llatda pul yo'q" = 0 so'm
- "100 mln", "100mln", "100 million" = 100000000 so'm
- "50 ming" = 50000 so'm
- Raqamlarni to'g'ri tushunish
- Qiziqarli va qisqa javob (max 2 gap)

FORMAT:
{"balance": X, "message": "Qiziqarli javob"}

MISOL:
Javob: "yo'q hozir"
{"balance": 0, "message": "😊 Juda yaxshi! Sizga pulni to'g'ri boshqarishni o'rganamiz!"}

Javob: "100 million"
{"balance": 100000000, "message": "🤩 Ajoyib! Millionerlar ham ishlaydi. 100 mln ni boshlang'ich balans sifatida qo'shdim!"}

Javob: "500 ming"
{"balance": 500000, "message": "✨ Yaxshi! 500 ming so'm boshlang'ich balans sifatida qo'shildi."}"""
                    },
                    {
                        "role": "user",
                        "content": f"Foydalanuvchi javobi: {text}"
                    }
                ],
                max_tokens=150,
                temperature=0.7
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # JSON parse
            import json
            if '```json' in result_text:
                result_text = result_text.split('```json')[1].split('```')[0]
            elif '```' in result_text:
                result_text = result_text.split('```')[1]
            
            result = json.loads(result_text)
            return result
            
        except Exception as e:
            logger.error(f"AI balans tahlili xatolik: {e}")
            # Fallback
            try:
                import re
                # Oddiy regex bilan raqamni ajratish
                numbers = re.findall(r'\d+', text)
                if numbers:
                    balance = float(''.join(numbers))
                    return {"balance": balance, "message": ""}
            except:
                pass
            return {"balance": 0, "message": ""}
    
    async def _parse_debt_info(self, text: str) -> Dict:
        """Qarz ma'lumotlarini AI bilan parse qilish"""
        try:
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": """Siz qarz ma'lumotlarini parse qiluvchi yordamchisisiz.

VAZIFA:
Javobdan qarz ma'lumotlarini ajrating: ism, summa, qaytarish sanasi (ixtiyoriy)

QOIDALAR:
- "Akmalga 100000 so'm qarz bergan edim" → {"person": "Akmal", "amount": 100000, "due_date": null}
- "Oila 500000 20-noyabrda qaytaradi" → {"person": "Oila", "amount": 500000, "due_date": "20-noyabr"}
- "Do'st 50 ming" → {"person": "Do'st", "amount": 50000, "due_date": null}
- "100 mln" = 100000000
- "50 ming" = 50000

FORMAT - FAQAT JSON:
{"person": "Ism", "amount": NUMBER, "due_date": "sana yoki null"}

MISOL:
Javob: "Akmalga 100000 so'm qarz bergan edim, 20-noyabrda qaytaradi"
JSON: {"person": "Akmal", "amount": 100000, "due_date": "20-noyabr"}

Javob: "Do'st 500000"
JSON: {"person": "Do'st", "amount": 500000, "due_date": null}"""
                    },
                    {
                        "role": "user",
                        "content": f"Qarz ma'lumoti: {text}"
                    }
                ],
                max_tokens=100,
                temperature=0
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # JSON parse
            import json
            if '```json' in result_text:
                result_text = result_text.split('```json')[1].split('```')[0]
            elif '```' in result_text:
                result_text = result_text.split('```')[1]
            
            result = json.loads(result_text)
            return result
            
        except Exception as e:
            logger.error(f"AI qarz parse xatolik: {e}")
            # Fallback
            return {"person": "Noma'lum", "amount": 0, "due_date": None}

    async def get_user_info(self, user_id: int) -> Dict:
        """Foydalanuvchi ma'lumotlarini olish"""
        try:
            user = await self.db.execute_one(
                "SELECT name, phone FROM users WHERE user_id = %s",
                (user_id,)
            )
            if user:
                # user tuple bo'lishi mumkin
                if isinstance(user, tuple):
                    return {"name": user[0], "phone": user[1]}
                return {"name": user.get('name', "Do'st"), "phone": user.get('phone')}
            return {"name": "Do'st", "phone": None}
        except Exception as e:
            logger.error(f"Error getting user info: {e}")
            return {"name": "Do'st", "phone": None}
    
    async def _check_name(self, name: str) -> Dict:
        """Ismni AI bilan tekshirish - yomon so'z yoki haqorat bilan bo'lishini"""
        try:
            response = await self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": "Siz ism tekshiruvchisisiz. Ism yaxshi bo'lsa 'valid' qaytaring, yomon so'z yoki haqorat bo'lsa 'invalid' qaytaring. Faqat 'valid' yoki 'invalid' javob bering."
                    },
                    {
                        "role": "user",
                        "content": f"Ism tekshirish: {name}"
                    }
                ],
                max_tokens=10,
                temperature=0
            )
            result = response.choices[0].message.content.strip().lower()
            return {"is_valid": "valid" in result}
        except:
            # Xatolik bo'lsa ham valid qilamiz
            return {"is_valid": True}
    
    async def get_user_financial_context(self, user_id: int) -> Dict:
        """Foydalanuvchining moliyaviy kontekstini olish"""
        try:
            # Balanslar
            balances = await self.db.get_balances(user_id)
            
            # Oxirgi tranzaksiyalar
            recent_transactions = await self.db.execute_query(
                """
                SELECT t.*
                FROM transactions t
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
                    SUM(CASE WHEN transaction_type = 'income' THEN amount ELSE 0 END) as total_income,
                    SUM(CASE WHEN transaction_type = 'expense' THEN amount ELSE 0 END) as total_expense,
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
                WHERE user_id = %s AND transaction_type = 'expense'
                AND DATE(created_at) = CURDATE()
                """,
                (user_id,)
            )
            
            # O'tgan kunga nisbatan o'sish/kamayish
            yesterday_expenses = await self.db.execute_query(
                """
                SELECT SUM(amount) as yesterday_total
                FROM transactions
                WHERE user_id = %s AND transaction_type = 'expense'
                AND DATE(created_at) = DATE_SUB(CURDATE(), INTERVAL 1 DAY)
                """,
                (user_id,)
            )
            
            # Bugungi kategoriyalar bo'yicha xarajatlar (takrorlanishni aniqlash uchun)
            today_by_category = await self.db.execute_query(
                """
                SELECT category, COUNT(*) as count, SUM(amount) as total
                FROM transactions
                WHERE user_id = %s AND transaction_type = 'expense'
                AND DATE(created_at) = CURDATE()
                GROUP BY category
                ORDER BY total DESC
                """,
                (user_id,)
            )
            
            # Haftalik statistikalar
            week_stats = await self.db.execute_query(
                """
                SELECT 
                    SUM(CASE WHEN transaction_type = 'income' THEN amount ELSE 0 END) as total_income,
                    SUM(CASE WHEN transaction_type = 'expense' THEN amount ELSE 0 END) as total_expense,
                    COUNT(*) as transaction_count
                FROM transactions
                WHERE user_id = %s 
                AND created_at >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
                """,
                (user_id,)
            )
            
            # Haftalik kategoriyalar bo'yicha xarajatlar
            week_by_category = await self.db.execute_query(
                """
                SELECT category, SUM(amount) as total, COUNT(*) as count
                FROM transactions
                WHERE user_id = %s AND transaction_type = 'expense'
                AND created_at >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
                GROUP BY category
                ORDER BY total DESC
                LIMIT 10
                """,
                (user_id,)
            )
            
            # Eng katta xarajatlar (top 5)
            top_expenses = await self.db.execute_query(
                """
                SELECT amount, category, description, created_at
                FROM transactions
                WHERE user_id = %s AND transaction_type = 'expense'
                ORDER BY amount DESC
                LIMIT 5
                """,
                (user_id,)
            )
            
            # Eng katta daromadlar (top 5)
            top_incomes = await self.db.execute_query(
                """
                SELECT amount, category, description, created_at
                FROM transactions
                WHERE user_id = %s AND transaction_type = 'income'
                ORDER BY amount DESC
                LIMIT 5
                """,
                (user_id,)
            )
            
            # Oylik kategoriyalar bo'yicha xarajatlar
            month_by_category = await self.db.execute_query(
                """
                SELECT category, SUM(amount) as total, COUNT(*) as count
                FROM transactions
                WHERE user_id = %s AND transaction_type = 'expense'
                AND MONTH(created_at) = MONTH(CURRENT_DATE)
                AND YEAR(created_at) = YEAR(CURRENT_DATE)
                GROUP BY category
                ORDER BY total DESC
                """,
                (user_id,)
            )
            
            # month_stats tuple bo'lishi mumkin, uni dict ga o'tkazish kerak
            month_stats_dict = {}
            if month_stats and month_stats[0]:
                stat = month_stats[0]
                if isinstance(stat, tuple):
                    # (total_income, total_expense, transaction_count)
                    month_stats_dict = {
                        'total_income': float(stat[0]) if len(stat) > 0 and stat[0] else 0,
                        'total_expense': float(stat[1]) if len(stat) > 1 and stat[1] else 0,
                        'transaction_count': int(stat[2]) if len(stat) > 2 and stat[2] else 0,
                    }
                elif isinstance(stat, dict):
                    month_stats_dict = stat
                else:
                    month_stats_dict = {}
            
            # today_expenses tuple
            today_exp = 0
            if today_expenses and today_expenses[0]:
                exp = today_expenses[0]
                if isinstance(exp, tuple):
                    today_exp = float(exp[0]) if len(exp) > 0 and exp[0] else 0
                elif isinstance(exp, dict):
                    today_exp = exp.get('today_total', 0) or 0
            
            # yesterday_expenses tuple
            yesterday_exp = 0
            if yesterday_expenses and yesterday_expenses[0]:
                exp = yesterday_expenses[0]
                if isinstance(exp, tuple):
                    yesterday_exp = float(exp[0]) if len(exp) > 0 and exp[0] else 0
                elif isinstance(exp, dict):
                    yesterday_exp = exp.get('yesterday_total', 0) or 0
            
            # today_by_category ni dict ga o'tkazish
            today_category_data = {}
            if today_by_category:
                for item in today_by_category:
                    if isinstance(item, tuple):
                        category = item[0] if len(item) > 0 else ''
                        count = item[1] if len(item) > 1 else 0
                        total = float(item[2]) if len(item) > 2 and item[2] else 0
                    elif isinstance(item, dict):
                        category = item.get('category', '')
                        count = item.get('count', 0)
                        total = float(item.get('total', 0)) or 0
                    else:
                        continue
                    if category:
                        today_category_data[category] = {'count': count, 'total': total}
            
            # week_stats ni dict ga o'tkazish
            week_stats_dict = {}
            if week_stats and week_stats[0]:
                stat = week_stats[0]
                if isinstance(stat, tuple):
                    week_stats_dict = {
                        'total_income': float(stat[0]) if len(stat) > 0 and stat[0] else 0,
                        'total_expense': float(stat[1]) if len(stat) > 1 and stat[1] else 0,
                        'transaction_count': int(stat[2]) if len(stat) > 2 and stat[2] else 0,
                    }
                elif isinstance(stat, dict):
                    week_stats_dict = stat
            
            # week_by_category ni list ga o'tkazish
            week_category_data = []
            if week_by_category:
                for item in week_by_category:
                    if isinstance(item, tuple):
                        week_category_data.append({
                            'category': item[0] if len(item) > 0 else '',
                            'total': float(item[1]) if len(item) > 1 and item[1] else 0,
                            'count': int(item[2]) if len(item) > 2 and item[2] else 0,
                        })
                    elif isinstance(item, dict):
                        week_category_data.append({
                            'category': item.get('category', ''),
                            'total': float(item.get('total', 0)) or 0,
                            'count': int(item.get('count', 0)) or 0,
                        })
            
            # top_expenses ni list ga o'tkazish
            top_expenses_list = []
            if top_expenses:
                for item in top_expenses:
                    if isinstance(item, tuple):
                        top_expenses_list.append({
                            'amount': float(item[0]) if len(item) > 0 and item[0] else 0,
                            'category': item[1] if len(item) > 1 else '',
                            'description': item[2] if len(item) > 2 else '',
                            'created_at': item[3] if len(item) > 3 else None,
                        })
                    elif isinstance(item, dict):
                        top_expenses_list.append({
                            'amount': float(item.get('amount', 0)) or 0,
                            'category': item.get('category', ''),
                            'description': item.get('description', ''),
                            'created_at': item.get('created_at'),
                        })
            
            # top_incomes ni list ga o'tkazish
            top_incomes_list = []
            if top_incomes:
                for item in top_incomes:
                    if isinstance(item, tuple):
                        top_incomes_list.append({
                            'amount': float(item[0]) if len(item) > 0 and item[0] else 0,
                            'category': item[1] if len(item) > 1 else '',
                            'description': item[2] if len(item) > 2 else '',
                            'created_at': item[3] if len(item) > 3 else None,
                        })
                    elif isinstance(item, dict):
                        top_incomes_list.append({
                            'amount': float(item.get('amount', 0)) or 0,
                            'category': item.get('category', ''),
                            'description': item.get('description', ''),
                            'created_at': item.get('created_at'),
                        })
            
            # month_by_category ni list ga o'tkazish
            month_category_data = []
            if month_by_category:
                for item in month_by_category:
                    if isinstance(item, tuple):
                        month_category_data.append({
                            'category': item[0] if len(item) > 0 else '',
                            'total': float(item[1]) if len(item) > 1 and item[1] else 0,
                            'count': int(item[2]) if len(item) > 2 and item[2] else 0,
                        })
                    elif isinstance(item, dict):
                        month_category_data.append({
                            'category': item.get('category', ''),
                            'total': float(item.get('total', 0)) or 0,
                            'count': int(item.get('count', 0)) or 0,
                        })
            
            context = {
                "balances": balances,
                "recent_transactions": recent_transactions if recent_transactions else [],
                "debts": debts if debts else [],
                "month_stats": month_stats_dict,
                "week_stats": week_stats_dict,
                "today_expenses": today_exp,
                "yesterday_expenses": yesterday_exp,
                "today_category_data": today_category_data,
                "week_category_data": week_category_data,
                "month_category_data": month_category_data,
                "top_expenses": top_expenses_list,
                "top_incomes": top_incomes_list,
            }
            
            return context
            
        except Exception as e:
            logger.error(f"Error getting financial context: {e}")
            return {}

    async def get_chat_history(self, user_id: int, limit: int = None) -> List[Dict]:
        """Chat tarixini olish - Pro tarifda barcha xabarlarni"""
        try:
            # Pro tarifda limit yo'q - barcha xabarlar
            if limit is None:
                history = await self.db.execute_query(
                    """
                    SELECT role, content, created_at
                    FROM ai_chat_history
                    WHERE user_id = %s
                    ORDER BY created_at ASC
                    """,
                    (user_id,)
                )
            else:
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
                if history:
                    history_list = list(history)
                    history_list.reverse()
                    history = history_list
            
            if not history:
                return []
            
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
    
    async def generate_response(self, user_id: int, question: str) -> List[str]:
        """AI javob generatsiya qilish - Pro tarif uchun optimallashtirilgan"""
        try:
            # 40,000 so'm limitini tekshirish
            from datetime import datetime
            month_year = datetime.now().strftime('%Y-%m')
            usage = await self.db.get_or_create_pro_usage(user_id, month_year)
            
            if usage['total_cost'] >= 40000:
                return [
                    f"⚠️ **Xarajat limiti tugadi!**\n\n"
                    f"Hozirgi oyda API xarajatlari 40,000 so'mdan oshdi.\n"
                    f"Keyingi oyni kutishingiz kerak. Yoki Plus paketga o'ting."
                ]
            
            # Foydalanuvchi ma'lumotlari
            user_info = await self.get_user_info(user_id)
            user_name = user_info.get("name", "Do'st")
            
            # Tranzaksiya aniqlash va saqlash
            transaction = await self.detect_and_save_transaction(question, user_id)
            
            # Eslatma aniqlash va saqlash
            reminder = await self.detect_and_save_reminder(user_id, question)
            
            # Moliyaviy kontekstni olish
            context = await self.get_user_financial_context(user_id)
            
            # Kontekstni matn shakliga o'tkazish
            context_text = self._format_context(context)
            
            # BARCHA chat history ni olish (limit yo'q - barcha xabarlar)
            chat_history = await self.get_chat_history(user_id, limit=None)
            
            # Messages tayyorlash
            messages = [{"role": "system", "content": self.system_prompt}]
            
            # Kontekstni qo'shish
            messages.append({
                "role": "system", 
                "content": f"Foydalanuvchi ismi: {user_name}\n\nFoydalanuvchining joriy moliyaviy holati:\n{context_text}"
            })
            
            # BARCHA chat history ni qo'shish - AI eski xabarlarni eslab qolishi uchun
            for hist in chat_history[-50:]:  # Oxirgi 50 ta xabarni qo'shish (token limit uchun)
                messages.append({
                    "role": hist["role"],
                    "content": hist["content"]
                })
            
            # Foydalanuvchi savolini qo'shish
            messages.append({"role": "user", "content": question})
            
            # OpenAI API chaqiruvi
            def call_openai():
                response = openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    max_tokens=300,  # Qisqa javob uchun kamaytirildi
                    temperature=0.8
                )
                return response.choices[0].message.content
            
            loop = asyncio.get_event_loop()
            ai_response = await loop.run_in_executor(None, call_openai)
            
            # API xarajatini hisoblash (taxminan 1 matn xabari = 10-50 so'm)
            # GPT-4o-mini narxi: input $0.15/1M tokens, output $0.60/1M tokens
            # 1 token ≈ 4 belgi, 1 xabar ≈ 100 token = $0.00006 ≈ 0.6 so'm
            # Lekin xavfsiz uchun 10 so'm deb olamiz
            estimated_cost = 10.0
            
            # Xarajatni saqlash
            await self.db.increment_pro_usage(user_id, 'text', estimated_cost, month_year)
            
            # Chat history ga saqlash
            await self.save_to_history(user_id, "user", question)
            await self.save_to_history(user_id, "assistant", ai_response)
            
            # AI o'zi bir nechta xabar kerakligini tushunsin - smart splitting
            messages_list = self._split_response_smart(ai_response, question)
            
            # Agar eslatma qo'shilgan bo'lsa, xabar qo'shish
            if reminder:
                reminder_text = f"✅ Eslatmalarga qo'shdim: {reminder.get('title', 'Eslatma')} - {reminder.get('days_text', 'bugun')} eslataman."
                messages_list.append(reminder_text)
            
            return messages_list
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return ["Kechirasiz, javob berishda xatolik yuz berdi. Iltimos, qayta urinib ko'ring."]
    
    def _split_response_smart(self, response: str, question: str) -> List[str]:
        """AI javobini smart bo'lish - faqat kerakli vaqtda ko'p xabar"""
        # Formatlash belgilarini olib tashlash
        cleaned = response
        cleaned = cleaned.replace('### ', '')
        cleaned = cleaned.replace('**', '')
        cleaned = cleaned.replace('###Tahlil:', '')
        cleaned = cleaned.replace('Tahlil:', '')
        cleaned = cleaned.replace('Taklif:', '')
        cleaned = cleaned.replace('Tavsiya:', '')
        cleaned = cleaned.strip()
        
        # Agar javob qisqa bo'lsa (100 belgidan kam), bitta xabar
        if len(cleaned) <= 100:
            return [cleaned]
        
        # Salomlashish yoki oddiy suhbat savoli bo'lsa - 1 xabar
        greeting_keywords = ['qalaysiz', 'nima yangiliklar', 'qanday yordam', 'salom', 'assalomu alaykum', 'hello', 'hi']
        if any(keyword in question.lower() for keyword in greeting_keywords):
            # Qisqa javob
            sentences = cleaned.split('.')
            if sentences:
                first_sentence = sentences[0].strip()
                if first_sentence:
                    return [first_sentence + '.']
            return [cleaned[:100] + '...'] if len(cleaned) > 100 else [cleaned]
        
        # Oddiy xarajat (qo'shilganini aytish) - 1 xabar
        simple_keywords = ['qo\'shdim', 'qo\'shib qo\'ydim', 'saqladim', 'kirim', 'chiqim']
        if any(keyword in cleaned.lower() for keyword in simple_keywords) and len(cleaned) <= 200:
            return [cleaned]
        
        # Qatorlarni ajratish (. ! ? dan keyin)
        sentences = []
        current = ""
        
        for char in cleaned:
            current += char
            if char in '.!?' and len(current.strip()) > 15:
                sent = current.strip()
                sent = sent.replace('###', '').replace('**', '')
                if sent:
                    sentences.append(sent)
                current = ""
        
        if current.strip():
            sent = current.strip()
            sent = sent.replace('###', '').replace('**', '')
            if sent:
                sentences.append(sent)
        
        # Agar 1-2 gap bo'lsa, bitta xabar
        if len(sentences) <= 2:
            return [cleaned]
        
        # Ko'p gap bo'lsa, mantiqiy bo'lish
        messages = []
        current_msg = []
        
        for sent in sentences:
            current_msg.append(sent)
            
            # Agar 2 gap to'plansa yoki oxirgi gap bo'lsa
            if len(current_msg) >= 2 or sent == sentences[-1]:
                msg = " ".join(current_msg)
                msg = msg.replace('###', '').replace('**', '').strip()
                if msg:
                    messages.append(msg)
                current_msg = []
        
        return messages if messages else [cleaned]
    
    def _split_response(self, response: str) -> List[str]:
        """Eski metod - backwards compatibility"""
        return self._split_response_smart(response, "")
    
    async def detect_and_save_reminder(self, user_id: int, message: str) -> Optional[Dict]:
        """Xabardan eslatmani aniqlash va saqlash - AI orqali (DONA AI)
        
        Misol xabarlar:
        - "Ertaga soat 11:00 do'stim bilan Hamkor bankka boramiz"
        - "Har dushanba 19:00 darsim bor"
        - "28-dekabr mijoz bilan uchrashuv"
        """
        try:
            from datetime import datetime, timedelta
            import re
            
            # Tarifni tekshirish
            tariff = await self.db.get_active_tariff(user_id)
            
            # Plus va Pro uchun eslatmalar
            if tariff not in ('PLUS', 'PRO'):
                # Free tarif uchun eslatma yo'q
                return None
            
            # DONA AI eslatma prompt - sana, vaqt, joy, shaxs, vazifani ajratish
            today = datetime.now()
            current_date = today.strftime('%Y-%m-%d')
            current_time = today.strftime('%H:%M')
            weekday_names = ['dushanba', 'seshanba', 'chorshanba', 'payshanba', 'juma', 'shanba', 'yakshanba']
            current_weekday = weekday_names[today.weekday()]
            
            # Sana hisoblash
            tomorrow = (today + timedelta(days=1))
            tomorrow_str = tomorrow.strftime('%Y-%m-%d')
            
            reminder_prompt = f"""Xabardan eslatma bor-yo'qligini aniqlab, agar bor bo'lsa JSON qaytaring.

XABAR: "{message}"

BUGUNGI SANGA: {current_date} ({current_weekday})
HOZIRGI VAQT: {current_time}

MUHIM QOIDA: Agar xabarda vaqt (08:00, 12:00, soat 8) VA/YOKI sana (ertaga, bugun, keyin) VA/YOKI joy (Makrab, bank, do'kon) bo'lsa VA "borish", "ketish", "meeting", "uchrashuv", "dars" kabi so'zlar bo'lsa, bu ES LATMA!

MISOL XABARLAR VA JAVOBI:

1. "Ertaga 12:00 da meeting bor" 
→ {{"has_reminder": true, "reminder_type": "meeting", "title": "Meeting", "date": "{tomorrow_str}", "time": "12:00", "location": null, "person_name": null}}

2. "Ertaga 08:00 Makrabga borishim kerak eslatasan"
→ {{"has_reminder": true, "reminder_type": "task", "title": "Makrabga borish", "date": "{tomorrow_str}", "time": "08:00", "location": "Makrab", "person_name": null}}

3. "100 000 so'mga non oldim"
→ {{"has_reminder": false}}

AGAR ES LATMA BOR BO'LSA, QUYIDAGI JSON QAYTARING:
{{
  "has_reminder": true,
  "reminder_type": "meeting|event|task|debt_give|debt_receive|payment|other",
  "title": "qisqa sarlavha (max 50 belgi)",
  "description": "batafsil tavsif",
  "date": "YYYY-MM-DD",
  "time": "HH:MM",
  "person_name": "shaxs ismi yoki null",
  "location": "joy nomi yoki null",
  "amount": 0,
  "currency": "UZS",
  "is_recurring": false,
  "recurrence_pattern": null,
  "recurrence_day": null
}}

SANA QOIDALARI:
- "ertaga" → {tomorrow_str}
- "bugun" → {current_date}
- Sana format: YYYY-MM-DD

VAQT QOIDALARI:
- "12:00 da" → "12:00"
- "08:00" → "08:00"
- "soat 8" → "08:00"

AGAR ES LATMA BO'LMASA: {{"has_reminder": false}}

FAQAT JSON QAYTARING, HECH QANDAY IZOH YOZMA."""
            
            # AsyncOpenAI dan to'g'ri foydalanish
            try:
                if not self.openai_client:
                    logger.warning("OpenAI client yo'q, eslatma aniqlash mumkin emas")
                    return None
                
                response = await self.openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "Sen DONA AI - eslatmalarni aniqlash yordamchisisiz. Xabardan sana, vaqt, joy, shaxs va vazifani aniqlab, JSON formatida qaytarasan. Faqat JSON qaytarasan. Agar xabarda 'ertaga', 'bugun', 'borishim', 'ketishim', 'meeting', vaqt yoki joy bo'lsa, bu ES LATMA."},
                        {"role": "user", "content": reminder_prompt}
                    ],
                    max_tokens=400,
                    temperature=0.1
                )
                ai_response = response.choices[0].message.content
                logger.info(f"Reminder AI response: {ai_response}")
            except Exception as e:
                logger.warning(f"Error calling OpenAI for reminder: {e}")
                # Xatolik bo'lsa ham None qaytaramiz, lekin xatolikni log qilamiz
                ai_response = None
            
            if not ai_response:
                return None
            
            # JSON ni parse qilish
            import json
            if "```json" in ai_response:
                ai_response = ai_response.split("```json")[1].split("```")[0].strip()
            elif "```" in ai_response:
                ai_response = ai_response.split("```")[1].split("```")[0].strip()
            
            if "{" in ai_response and "}" in ai_response:
                start = ai_response.index("{")
                end = ai_response.rindex("}") + 1
                ai_response = ai_response[start:end]
            
            try:
                result = json.loads(ai_response)
                
                logger.info(f"Parsed reminder result: {result}")
                
                if not result.get('has_reminder'):
                    logger.info(f"Reminder not detected - has_reminder is False: {result}")
                    return None
                
                # Sana aniqlash
                reminder_date_str = result.get('date', current_date)
                reminder_date = None
                
                try:
                    # Sana formatlarini aniqlash
                    today_date = today.date()
                    
                    if reminder_date_str.lower() == 'bugun':
                        reminder_date = today_date
                    elif reminder_date_str.lower() == 'ertaga':
                        reminder_date = today_date + timedelta(days=1)
                    elif 'kun' in reminder_date_str.lower() and 'keyin' in reminder_date_str.lower():
                        # "5 kundan keyin" formatida
                        days_match = re.search(r'(\d+)\s*kun', reminder_date_str.lower())
                        if days_match:
                            days = int(days_match.group(1))
                            reminder_date = today_date + timedelta(days=days)
                        else:
                            reminder_date = today_date
                    else:
                        # YYYY-MM-DD formatida
                        try:
                            reminder_date = datetime.strptime(reminder_date_str, '%Y-%m-%d').date()
                        except:
                            # Agar parse qilishda xatolik bo'lsa, default bugun
                            reminder_date = today_date
                except:
                    reminder_date = today.date()  # Default: bugun
                
                # Vaqt aniqlash
                reminder_time_str = result.get('time', '09:00')
                if not reminder_time_str:
                    reminder_time_str = '09:00'
                
                # Eslatmani saqlash
                reminder_id = await self.db.create_reminder(
                    user_id=user_id,
                    reminder_type=result.get('reminder_type', 'other'),
                    title=result.get('title', 'Eslatma')[:255],
                    reminder_date=reminder_date,
                    description=result.get('description', message[:500]),
                    amount=result.get('amount'),
                    currency=result.get('currency', 'UZS'),
                    person_name=result.get('person_name'),
                    reminder_time=reminder_time_str,
                    location=result.get('location'),
                    is_recurring=result.get('is_recurring', False),
                    recurrence_pattern=result.get('recurrence_pattern'),
                    recurrence_day=result.get('recurrence_day')
                )
                
                # Kuni aniqlash
                days_diff = (reminder_date - today.date()).days
                if days_diff == 0:
                    days_text = f"bugun soat {reminder_time_str}"
                elif days_diff == 1:
                    days_text = f"ertaga soat {reminder_time_str}"
                elif days_diff > 1:
                    days_text = f"{days_diff} kundan keyin ({reminder_date.strftime('%d.%m')}) soat {reminder_time_str}"
                else:
                    days_text = f"bugun soat {reminder_time_str}"
                
                # Takrorlanadigan eslatma uchun
                if result.get('is_recurring'):
                    pattern = result.get('recurrence_pattern')
                    if pattern == 'daily':
                        days_text += " (har kuni)"
                    elif pattern == 'weekly':
                        day_num = result.get('recurrence_day', 0)
                        day_name = weekday_names[day_num] if 0 <= day_num <= 6 else ''
                        days_text += f" (har {day_name})"
                    elif pattern == 'monthly':
                        day_num = result.get('recurrence_day', 1)
                        days_text += f" (har oyning {day_num}-ida)"
                
                # Xabar matni
                title = result.get('title', 'Eslatma')
                person = result.get('person_name', '')
                location = result.get('location', '')
                amount = result.get('amount', 0)
                
                message_parts = [f"✅ Eslatma qo'shildi!"]
                message_parts.append(f"📌 {title}")
                if person:
                    message_parts.append(f"👤 {person}")
                if location:
                    message_parts.append(f"📍 {location}")
                if amount and amount > 0:
                    currency = result.get('currency', 'UZS')
                    message_parts.append(f"💰 {amount:,.0f} {currency}")
                message_parts.append(f"⏰ {days_text}")
                
                message_text = "\n".join(message_parts)
                
                return {
                    "id": reminder_id,
                    "title": title,
                    "date": reminder_date,
                    "time": reminder_time_str,
                    "days_text": days_text,
                    "location": location,
                    "person_name": person,
                    "is_recurring": result.get('is_recurring', False),
                    "message": message_text
                }
                
            except Exception as e:
                logger.error(f"Error parsing reminder JSON: {e}, response: {ai_response}")
                return None
                
        except Exception as e:
            logger.error(f"Error detecting reminder: {e}")
            return None
    
    async def detect_and_save_transaction(self, message: str, user_id: int) -> Optional[Dict]:
        """Xabardan tranzaksiyani aniqlash va saqlash - AI orqali (PRO tarif)"""
        try:
            # AI orqali tranzaksiyani aniqlash
            ai_result = await self.financial_module._extract_financial_data_with_gpt4(message)
            
            if not ai_result or 'transactions' not in ai_result or not ai_result['transactions']:
                return None
            
            # Birinchi tranzaksiyani olish
            tx = ai_result['transactions'][0]
            transaction_type = tx.get('type')
            amount = tx.get('amount')
            category = tx.get('category', 'other')
            
            # Type mapping (income/expense/debt)
            type_mapping = {
                'income': 'income',
                'expense': 'expense',
                'debt': 'expense'  # Qarz chiqim sifatida
            }
            transaction_type = type_mapping.get(transaction_type, 'expense')
            
            # Category mapping (AI kategoriyalarini bizning kategoriyalarimizga o'tkazish)
            # Config.py dagi kategoriyalar: income: ['Ish haqi', 'Biznes', 'Investitsiya', 'Boshqa']
            #                            expense: ['Ovqat', 'Transport', 'Kiyim', 'Uy', 'Sogʻliq', 'Taʼlim', 'Oʻyin-kulgi', 'Boshqa']
            category_mapping = {
                'ish haqi': 'Ish haqi',
                'biznes': 'Biznes',
                'ovqat': 'Ovqat',
                'transport': 'Transport',
                'kiyim': 'Kiyim',
                'uy': 'Uy',
                'sog\'liq': 'Sogʻliq',
                'ta\'lim': 'Taʼlim',
                'o\'yin-kulgi': 'Oʻyin-kulgi',
                'entertainment': 'Oʻyin-kulgi',
                'boshqa': 'Boshqa',
                'other': 'Boshqa'
            }
            category = category_mapping.get(category, 'Boshqa')
            
            if not transaction_type or not amount:
                return None
            
            # Tranzaksiyani saqlash
            try:
                transaction_id = await self.db.add_transaction(
                    user_id=user_id,
                    transaction_type=transaction_type,
                    amount=float(amount),
                    category=category,
                    description=message[:100]
                )
                logger.info(f"Transaction saved: id={transaction_id}, type={transaction_type}, amount={amount}, user={user_id}")
            except Exception as save_error:
                logger.error(f"Error saving transaction: {save_error}")
                return None
            
            return {
                "type": transaction_type,
                "amount": float(amount),
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
        text = "📊 Foydalanuvchi moliyaviy holati\n\n"
        
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
        
        # Qarzlar
        debts = context.get("debts", [])
        if debts and len(debts) > 0:
            lent_total = 0
            borrowed_total = 0
            for debt in debts[:5]:
                try:
                    if isinstance(debt, tuple):
                        debt_type = debt[3] if len(debt) > 3 else ''
                        amount = float(debt[4]) if len(debt) > 4 else 0
                    else:
                        debt_type = debt.get('debt_type', '')
                        amount = float(debt.get('amount', 0))
                    
                    if debt_type == 'lent':
                        lent_total += amount
                    elif debt_type == 'borrowed':
                        borrowed_total += amount
                except:
                    continue
            
            if lent_total > 0 or borrowed_total > 0:
                text += f"💸 Berilgan qarz: {lent_total:,.0f} so'm\n"
                text += f"💳 Olingan qarz: {borrowed_total:,.0f} so'm\n\n"
        
        # Oy statistikasi
        month_stats = context.get("month_stats", {})
        if month_stats:
            mi = month_stats.get('total_income', 0) or 0
            me = month_stats.get('total_expense', 0) or 0
            mc = month_stats.get('transaction_count', 0) or 0
            
            text += f"📅 Bu oy:\n"
            text += f"- Kirim: {mi:,.0f} so'm\n"
            text += f"- Chiqim: {me:,.0f} so'm\n"
            text += f"- Tranzaksiyalar: {mc} ta\n\n"
        
        # Oxirgi tranzaksiyalar
        transactions = context.get("recent_transactions", [])
        if transactions and len(transactions) > 0:
            text += "📝 Oxirgi xarajat/daromadlar:\n"
            for idx, t in enumerate(transactions[:5], 1):
                try:
                    # Tuple yoki dict bo'lishi mumkin
                    if isinstance(t, tuple):
                        # Tuple struktura: (id, user_id, transaction_type, amount, category, description, ...)
                        t_type = "kirim" if len(t) > 2 and t[2] == 'income' else "chiqim"
                        amount = float(t[3]) if len(t) > 3 else 0
                        category = t[4] if len(t) > 4 else 'Nomalum'
                        desc = t[5][:30] if len(t) > 5 and t[5] else ''
                    else:
                        t_type = "kirim" if t.get('transaction_type') == 'income' else "chiqim"
                        amount = float(t.get('amount', 0))
                        category = t.get('category', 'Nomalum')
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
            text += f"📌 Bugungi xarajatlar: {today_exp:,.0f} so'm\n"
        
        # Bugungi kategoriyalar bo'yicha xarajatlar
        today_category_data = context.get("today_category_data", {})
        if today_category_data:
            text += "\n📊 Bugungi kategoriyalar bo'yicha:\n"
            for category, data in today_category_data.items():
                count = data.get('count', 0) if isinstance(data, dict) else 0
                total = data.get('total', 0) if isinstance(data, dict) else 0
                text += f"- {category}: {count} marta, {total:,.0f} so'm\n"
            text += "\n"
        
        # Haftalik statistikalar
        week_stats = context.get("week_stats", {})
        if week_stats:
            wi = week_stats.get('total_income', 0) or 0
            we = week_stats.get('total_expense', 0) or 0
            wc = week_stats.get('transaction_count', 0) or 0
            text += f"📅 Haftalik (7 kun):\n"
            text += f"- Kirim: {wi:,.0f} so'm\n"
            text += f"- Chiqim: {we:,.0f} so'm\n"
            text += f"- Tranzaksiyalar: {wc} ta\n\n"
        
        # Haftalik kategoriyalar
        week_category_data = context.get("week_category_data", [])
        if week_category_data:
            text += "📊 Haftalik kategoriyalar (top 5):\n"
            for cat in week_category_data[:5]:
                text += f"- {cat.get('category', '')}: {cat.get('total', 0):,.0f} so'm ({cat.get('count', 0)} marta)\n"
            text += "\n"
        
        # Oylik kategoriyalar
        month_category_data = context.get("month_category_data", [])
        if month_category_data:
            text += "📊 Oylik kategoriyalar (top 5):\n"
            for cat in month_category_data[:5]:
                text += f"- {cat.get('category', '')}: {cat.get('total', 0):,.0f} so'm ({cat.get('count', 0)} marta)\n"
            text += "\n"
        
        # Eng katta xarajatlar
        top_expenses = context.get("top_expenses", [])
        if top_expenses:
            text += "🔴 Eng katta xarajatlar (top 3):\n"
            for idx, exp in enumerate(top_expenses[:3], 1):
                amount = exp.get('amount', 0)
                category = exp.get('category', '')
                desc = exp.get('description', '')[:30] if exp.get('description') else ''
                text += f"{idx}. {amount:,.0f} so'm ({category})"
                if desc:
                    text += f" - {desc}"
                text += "\n"
            text += "\n"
        
        # Eng katta daromadlar
        top_incomes = context.get("top_incomes", [])
        if top_incomes:
            text += "🟢 Eng katta daromadlar (top 3):\n"
            for idx, inc in enumerate(top_incomes[:3], 1):
                amount = inc.get('amount', 0)
                category = inc.get('category', '')
                desc = inc.get('description', '')[:30] if inc.get('description') else ''
                text += f"{idx}. {amount:,.0f} so'm ({category})"
                if desc:
                    text += f" - {desc}"
                text += "\n"
            text += "\n"
        
        return text


class AIChatFree:
    """Free tarif uchun AI chat - cheklangan versiya"""
    
    def __init__(self, db=None):
        self.db = db if db else Database()
    
    async def generate_response(self, user_id: int, question: str) -> List[str]:
        """Free tarif uchun - tranzaksiya aniqlash (AI bilan, tafsif yo'q, muvaffaqiyatsiz ham limit kamayadi)"""
        try:
            # Onboarding tugaganmi tekshirish
            balance_check = await self.db.execute_one(
                """
                SELECT COUNT(*) FROM transactions 
                WHERE user_id = %s AND category IN ('boshlang_ich_balans', 'boshlang_ich_naqd', 'boshlang_ich_karta')
                """,
                (user_id,)
            )
            has_initial_balance = balance_check[0] > 0 if balance_check else False
            
            if not has_initial_balance:
                return [
                    "⚠️ Ro'yxatdan o'tishingiz kerak!\n\n"
                    "Tranzaksiyalarni qilish uchun avval ro'yxatdan o'ting.\n"
                    "/start boshing va onboarding jarayonini tugallang."
                ]
            
            # Oy davomidagi tranzaksiyalar sonini tekshirish
            count = await self.get_monthly_transaction_count(user_id)
            
            if count >= 250:
                remaining = max(0, 250 - count)
                return [f"❌ Oylik limit tugadi ({remaining}/250 qoldi). Keyingi oy yoki MAX tarif."]
            
            # Limit kamayishi (muvaffaqiyatli yoki muvaffaqiyatsiz - faqat 1 ta kamayadi)
            await self.decrement_transaction_limit(user_id)
            
            # Tranzaksiya aniqlash va saqlash (AI bilan, max 40 token)
            transaction = await self.detect_and_save_transaction_free(question, user_id)
            
            if transaction:
                # Saqlash
                await self.save_transaction(user_id, transaction)
                
                # Qisqa javob (tafsif yo'q, faqat summa va kategoriya)
                type_name = "Kirim" if transaction['type'] == 'income' else "Chiqim"
                amount = int(transaction['amount'])
                category = transaction['category']
                
                response = f"{type_name}: {amount:,} so'm ({category})"
                
                # OpenAI fallback ishlatilganda xabar qo'shamiz
                if transaction.get('fallback_warning'):
                    response += "\n⚠️ Zaxira AI ishlayapti (Mistral xatolik)"
                
                return [response]
            else:
                # Tranzaksiya aniqlanmadi (limit allaqachon kamaydi)
                return ["❌ Hech qanday to'g'ri tranzaksiya topilmadi. Iltimos, aniqroq yozing."]
                
        except Exception as e:
            logger.error(f"Error in Free AI chat: {e}")
            # Xatolik bo'lsa ham limit kamaydi
            await self.decrement_transaction_limit(user_id)
            return ["❌ Xatolik yuz berdi. Iltimos, qayta urinib ko'ring."]
    
    async def decrement_transaction_limit(self, user_id: int):
        """Tranzaksiya limitini kamaytirish (faqat tracking uchun) - marker yozuv qo'shish"""
        try:
            # Faqat "attempt" belgisi sifatida marker yozuv qo'shamiz
            await self.db.execute_query(
                """
                INSERT INTO transactions (user_id, transaction_type, amount, category, description, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                """,
                (user_id, 'expense', 0, 'free_limit_used', 'Free tariff attempt tracked')
            )
        except Exception as e:
            logger.error(f"Error tracking transaction limit: {e}")
    
    async def get_monthly_transaction_count(self, user_id: int) -> int:
        """Oy davomida qilingan tranzaksiyalar sonini olish"""
        try:
            result = await self.db.execute_one(
                """
                SELECT COUNT(*) 
                FROM transactions 
                WHERE user_id = %s 
                AND MONTH(created_at) = MONTH(NOW())
                AND YEAR(created_at) = YEAR(NOW())
                """,
                (user_id,)
            )
            if result and isinstance(result, tuple):
                return result[0]
            return 0
        except Exception as e:
            logger.error(f"Error getting monthly transaction count: {e}")
            return 0
    
    async def detect_and_save_transaction_free(self, message: str, user_id: int) -> Optional[Dict]:
        """Free tarif uchun tranzaksiya aniqlash - AI bilan (max 40 token)"""
        try:
            # AI dan yordam so'rash - YAXSHIROQ SYSTEM PROMPT
            system_prompt = """You are a financial transaction parser. Extract type (income/expense), amount, and category (food/transport/utilities/health/education/other/qarz_olish/qarz_berish). Return ONLY valid JSON."""
            
            # User prompt - misol bilan
            user_prompt = f"""Message: "{message}"

Extract financial data and return JSON:
{{"type":"income/expense","amount":NUMBER,"category":"category_name"}}

Example: "20 ming so'mga lavash oldim" → {{"type":"expense","amount":20000,"category":"food"}}

JSON: """

            def call_openai():
                try:
                    # Mistral-7B-Instruct bilan urinib ko'ramiz (arzon)
                    response = openrouter_client.chat.completions.create(
                        model="mistralai/mistral-7b-instruct",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        max_tokens=50,  # Yaxshiroq javob uchun
                        temperature=0.0
                    )
                    return {"content": response.choices[0].message.content, "provider": "mistral"}
                except Exception as e:
                    logger.error(f"Mistral-7B xatolik: {e}")
                    # Fallback: gpt-3.5-turbo
                    try:
                        response = openai_client.chat.completions.create(
                            model="gpt-3.5-turbo",
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt}
                            ],
                            max_tokens=40,
                            temperature=0.0
                        )
                        return {"content": response.choices[0].message.content, "provider": "openai"}
                    except Exception as e2:
                        logger.error(f"OpenAI xatolik: {e2}")
                        return None
            
            loop = asyncio.get_event_loop()
            ai_result = await loop.run_in_executor(None, call_openai)
            
            if not ai_result:
                return None
            
            ai_response = ai_result.get("content") if isinstance(ai_result, dict) else ai_result
            provider = ai_result.get("provider") if isinstance(ai_result, dict) else "unknown"
            
            # Debug log
            logger.info(f"AI Response for '{message}': {ai_response}")
            
            # JSON ni parse qilish
            import json
            # Agar ```json ... ``` formatida bo'lsa, tozalaymiz
            if "```json" in ai_response:
                ai_response = ai_response.split("```json")[1].split("```")[0].strip()
            elif "```" in ai_response:
                ai_response = ai_response.split("```")[1].split("```")[0].strip()
            
            # Oddiy json uchun { } ichini topish
            if "{" in ai_response and "}" in ai_response:
                start = ai_response.index("{")
                end = ai_response.rindex("}") + 1
                ai_response = ai_response[start:end]
            
            try:
                result = json.loads(ai_response)
                logger.info(f"Parsed JSON: {result}")
                
                # Validate
                if result.get('type') in ['income', 'expense'] and result.get('amount') and result.get('category'):
                    tx_result = {
                        "type": result['type'],
                        "amount": float(result['amount']),
                        "category": result['category'],
                        "description": ""  # Tafsif yo'q
                    }
                    # OpenAI fallback ishlatilganda xabar qo'shamiz
                    if provider == "openai":
                        tx_result["fallback_warning"] = True
                    return tx_result
                else:
                    logger.warning(f"Validation failed for result: {result}")
            except Exception as e:
                logger.error(f"JSON parse error: {e}, response: {ai_response}")
            
            # Agar AI ishlamasa, return None
            return None
            
        except Exception as e:
            logger.error(f"Error detecting transaction (Free): {e}")
            return None
    
    async def save_transaction(self, user_id: int, transaction: Dict):
        """Tranzaksiyani saqlash"""
        try:
            await self.db.add_transaction(
                user_id=user_id,
                transaction_type=transaction['type'],
                amount=transaction['amount'],
                category=transaction['category'],
                description=""  # Tafsif yo'q
            )
        except Exception as e:
            logger.error(f"Error saving transaction (Free): {e}")


# Initialize AI chat instances
ai_chat = AIChat()
ai_chat_free = AIChatFree()
