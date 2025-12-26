import re
import logging
import json
import aiofiles
import requests
from typing import Optional, Dict, Any, List
from datetime import datetime

from openai import OpenAI, AsyncOpenAI
from google.cloud import speech_v1p1beta1 as speech
import asyncio

from config import (
    OPENAI_API_KEY,
    OPENROUTER_API_KEY,
    ELEVENLABS_API_KEY,
    GOOGLE_CLOUD_PROJECT,
    GOOGLE_APPLICATION_CREDENTIALS,
    CATEGORIES,
    ACTIVE_SPEECH_MODELS,
)
from database import db
from models import Transaction, TransactionType

class FinancialModule:
    def __init__(self):
        self.openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        # OpenRouter uchun sync client (Bepul tarifda ishlaganidek)
        self.openrouter_client = OpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1"
        ) if OPENROUTER_API_KEY else None
        self.speech_client = None

    def _format_amount_with_sign(self, amount: float, trans_type: str, currency: str = 'UZS') -> str:
        """Tranzaksiya summasini foydalanuvchiga qulay ko'rinishda formatlash (valyuta bilan)"""
        amount_value = float(amount or 0)
        sign_map = {
            "income": "+",
            "expense": "-",
            "debt": ""
        }
        sign = sign_map.get(trans_type, "")
        
        currency_names = {'UZS': "so'm", 'USD': "dollar", 'EUR': "evro", 'RUB': "rubl", 'TRY': "lira"}
        currency_symbols = {'UZS': "", 'USD': "🇺🇸", 'EUR': "🇪🇺", 'RUB': "🇷🇺", 'TRY': "🇹🇷"}
        currency_name = currency_names.get(currency, currency)
        currency_symbol = currency_symbols.get(currency, "💰")
        
        if currency != 'UZS':
            formatted = f"{currency_symbol} {amount_value:,.2f} {currency_name}"
        else:
            formatted = f"{amount_value:,.0f} so'm"
        
        return f"{sign} {formatted}".strip()

    def _format_human_date(self, iso_timestamp: Optional[str]) -> str:
        """Sana va vaqtni foydalanuvchi uchun qulay ko'rinishda chiqarish"""
        uz_months = {
            1: "Yanvar",
            2: "Fevral",
            3: "Mart",
            4: "Aprel",
            5: "May",
            6: "Iyun",
            7: "Iyul",
            8: "Avgust",
            9: "Sentabr",
            10: "Oktabr",
            11: "Noyabr",
            12: "Dekabr",
        }

        if not iso_timestamp:
            dt = datetime.now()
        else:
            cleaned = iso_timestamp.replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(cleaned)
            except ValueError:
                dt = datetime.now()

        month_name = uz_months.get(dt.month, "")
        return f"{dt.day:02d}-{month_name}, {dt.year}".strip().replace("- ,", "-")

    def _ensure_speech_client(self) -> speech.SpeechClient:
        if self.speech_client is None:
            if not GOOGLE_APPLICATION_CREDENTIALS:
                raise RuntimeError(
                    "Google Cloud Speech kredensial yo'q. Iltimos, GOOGLE_APPLICATION_CREDENTIALS ni .env faylda ko'rsating."
                )
            
            # Serverda kredensial faylini tekshirish
            import os
            if not os.path.exists(GOOGLE_APPLICATION_CREDENTIALS):
                raise RuntimeError(
                    f"Google Cloud kredensial fayli topilmadi: {GOOGLE_APPLICATION_CREDENTIALS}"
                )
            
            # Environment variable o'rnatish
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = GOOGLE_APPLICATION_CREDENTIALS
            
            self.speech_client = speech.SpeechClient()
        return self.speech_client
    
    async def process_audio_input(self, audio_file_path: str, user_id: int) -> Dict[str, Any]:
        """Audio faylni qayta ishlash - Google Cloud Speech-to-Text"""
        try:
            print(f"DEBUG: Processing audio file: {audio_file_path}")
            
            # Google Cloud Speech-to-Text (asosiy)
            google_enabled = ACTIVE_SPEECH_MODELS.get('GOOGLE', True)
            print(f"DEBUG: Google Speech enabled: {google_enabled}")
            print(f"DEBUG: GOOGLE_APPLICATION_CREDENTIALS: {GOOGLE_APPLICATION_CREDENTIALS}")
            
            if google_enabled:
                google_result = None
                try:
                    print("DEBUG: Trying to create Google Speech client...")
                    client = self._ensure_speech_client()
                    print(f"DEBUG: Google Speech client created: {client is not None}")
                    
                    if client:
                        with open(audio_file_path, "rb") as audio_file:
                            audio_content = audio_file.read()
                        print(f"DEBUG: Audio file read, size: {len(audio_content)} bytes")
                        
                        google_text = await self._transcribe_with_google(client, audio_content)
                        print(f"DEBUG: Google Speech transcription: {google_text}")
                        
                        if google_text and google_text.strip():
                            # Google natijasini darhol qayta ishlaymiz
                            google_result = await self.process_ai_input_advanced(google_text, user_id)
                            if google_result['success']:
                                google_result['message'] += f"\n\n🔊 **Texnologiya:** Google Cloud Speech-to-Text"
                                return google_result
                    else:
                        print("DEBUG: Google Speech client olinmadi - kredensiallar yo'q")
                except RuntimeError as google_error:
                    # RuntimeError - kredensiallar yo'q, bu normal
                    logging.warning(f"Google Speech credentials yo'q: {google_error}")
                    print(f"DEBUG: Google Speech credentials yo'q: {google_error}")
                except Exception as google_error:
                    logging.warning(f"Google Speech failed: {google_error}")
                    print(f"DEBUG: Google Speech failed: {google_error}")
            
            # Whisper API - asosiy va eng ishonchli
            whisper_text = None
            try:
                whisper_text = await self._transcribe_with_whisper(audio_file_path)
                print(f"DEBUG: Whisper transcription: {whisper_text}")
                
                if whisper_text and whisper_text.strip():
                    whisper_result = await self.process_ai_input_advanced(whisper_text, user_id)
                    
                    # Agar tranzaksiya topilgan bo'lsa
                    if whisper_result.get('success'):
                        return whisper_result
                    
                    # Tranzaksiya topilmadi, lekin matn aniqlandi - bu xato emas
                    # Foydalanuvchiga eshitilgan matnni ko'rsatamiz
                    return {
                        "success": False,
                        "message": f"🎤 **Eshitildi:** \"{whisper_text}\"\n\n❌ Moliyaviy tranzaksiya topilmadi.\n\nMasalan: \"100 ming ga ovqat oldim\" yoki \"500 000 qarz berdim\""
                    }
            except Exception as whisper_error:
                logging.warning(f"Whisper transcription failed: {whisper_error}")
                print(f"DEBUG: Whisper failed: {whisper_error}")
            
            # Agar Whisper ham ishlamasa
            return {
                "success": False,
                "message": "❌ Ovozli xabarni qayta ishlashda xatolik. Iltimos, qaytadan urinib ko'ring."
            }

        except Exception as e:
            logging.error(f"Audio qayta ishlashda xatolik: {e}")
            return {
                "success": False,
                "message": "❌ Audio faylni qayta ishlashda xatolik yuz berdi."
            }

    async def _transcribe_with_google(self, client: speech.SpeechClient, audio_content: bytes) -> Optional[str]:
        """Google Cloud Speech orqali transkripti olish"""
        audio = speech.RecognitionAudio(content=audio_content)

        speech_context = speech.SpeechContext(
            phrases=[
                "so'm",
                "ming",
                "million",
                "daromad",
                "xarajat",
                "qarz",
                "ishlab topdim",
                "sarfladim",
                "pul tushdi",
                "investitsiya",
                "marketing",
                "transport",
                "bepul",
                "premium",
            ],
            boost=15.0,
        )

        configs = [
            {
                "language_code": "uz-UZ",
                "alternative_language_codes": ["ru-RU", "kk-KZ", "en-US"],
            },
            {
                "language_code": "ru-RU",
                "alternative_language_codes": ["uz-UZ", "kk-KZ", "en-US"],
            },
            {
                "language_code": "en-US",
                "alternative_language_codes": ["ru-RU", "uz-UZ"],
            },
        ]

        for cfg in configs:
            try:
                recognition_config = speech.RecognitionConfig(
                    encoding=speech.RecognitionConfig.AudioEncoding.OGG_OPUS,
                    sample_rate_hertz=48000,
                    language_code=cfg["language_code"],
                    alternative_language_codes=cfg.get("alternative_language_codes", []),
                    enable_automatic_punctuation=True,
                    enable_word_time_offsets=False,
                    speech_contexts=[speech_context],
                )

                response = client.recognize(config=recognition_config, audio=audio)
                if response.results:
                    best_alternative = response.results[0].alternatives[0]
                    transcript = best_alternative.transcript.strip()
                    if transcript:
                        logging.info(
                            f"Google Speech muvaffaqiyatli (lang={cfg['language_code']}): {transcript}"
                        )
                        return transcript

            except Exception as e:
                logging.warning(
                    f"Google Speech konfiguratsiya sinovi muvaffaqiyatsiz (lang={cfg['language_code']}): {e}"
                )

        return None
    
    async def _transcribe_with_whisper(self, audio_file_path: str) -> Optional[str]:
        """OpenAI Whisper API orqali transkripti olish"""
        try:
            if not OPENAI_API_KEY:
                logging.warning("OpenAI API key yo'q, Whisper ishlatib bo'lmaydi")
                return None
            
            # OpenAI Whisper API uchun faylni ochish
            from openai import OpenAI
            openai_client = OpenAI(api_key=OPENAI_API_KEY)
            
            def call_whisper():
                with open(audio_file_path, "rb") as audio_file:
                    response = openai_client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file
                        # language parametrini olib tashladik - Whisper avtomatik aniqlaydi
                    )
                    return response.text
            
            loop = asyncio.get_event_loop()
            transcript = await loop.run_in_executor(None, call_whisper)
            
            if transcript and transcript.strip():
                logging.info(f"Whisper transcription muvaffaqiyatli: {transcript}")
                return transcript.strip()
                    
            return None
        except Exception as e:
            logging.error(f"Whisper transcription xatolik: {e}")
            return None
    
    async def _transcribe_with_elevenlabs(self, audio_content: bytes) -> Optional[str]:
        """ElevenLabs Speech-to-Text orqali transkripti olish"""
        try:
            
            # ElevenLabs Speech-to-Text API endpoint
            url = "https://api.elevenlabs.io/v1/speech-to-text"
            
            headers = {
                "xi-api-key": ELEVENLABS_API_KEY
            }
            
            # OGG formatni ElevenLabs qo'llab-quvvatlasa, shu formatni yuboramiz
            # ElevenLabs API `file` parametrini kutadi, `audio` emas
            files = {
                "file": ("audio.ogg", audio_content, "audio/ogg")
            }
            
            # Model - ElevenLabs Scribe v1 (Speech-to-Text model)
            data = {
                "model_id": "scribe_v1"
            }
            
            def call_api():
                response = requests.post(url, headers=headers, files=files, data=data, timeout=30)
                return response
            
            loop = asyncio.get_event_loop()
            http_response = await loop.run_in_executor(None, call_api)
            
            if http_response.status_code == 200:
                result = http_response.json()
                transcript = result.get('text', '').strip()
                if transcript:
                    logging.info(f"ElevenLabs Speech muvaffaqiyatli: {transcript}")
                    return transcript
            else:
                logging.warning(f"ElevenLabs API xatolik: {http_response.status_code} - {http_response.text}")
                return None
                
        except Exception as e:
            logging.error(f"ElevenLabs Speech xatolik: {e}")
            return None

    async def process_ai_input_advanced(self, text: str, user_id: int) -> Dict[str, Any]:
        """AI orqali matnni to'liq tahlil qilish va moliyaviy ma'lumotlarni ajratish"""
        try:
            # 1-bosqich: Moliyaviy ma'lumotlarni ajratish - to'g'ridan-to'g'ri
            financial_data = await self._extract_financial_data_with_gpt4(text)
            print(f"DEBUG AI financial_data: {financial_data}")
            # Taxminiy (approximate) bosqich o'chirildi: foydalanuvchi talabiga ko'ra taxmin qilinmasin
            # financial_data = await self._ensure_ai_guess(financial_data, extract_base)
            # print(f"DEBUG AI after ensure_guess: {financial_data}")
            
            # 3-bosqich: Ma'lumotlarni validatsiya qilish
            validation_result = await self._validate_extracted_data(financial_data, text)
            
            if not validation_result['is_valid']:
                return {
                    "success": False,
                    "message": validation_result['message']
                }
            
            # 4-bosqich: Tranzaksiyalarni tahlil qilish va ko'rsatish
            return await self._analyze_and_show_transactions(validation_result['data'], user_id, text)
            
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
        """Mistral bilan moliyaviy ma'lumotlarni ajratish - tez va arzon (PLUS tarif)"""
        try:
            # Bugungi sana va vaqt ma'lumotlari
            from datetime import datetime
            today = datetime.now()
            current_date = today.strftime('%Y-%m-%d')
            current_year = today.year
            current_month = today.month
            current_day = today.day
            
            # System prompt - soddalashtirilgan va optimallashtirilgan
            system_prompt = f"""Sen tranzaksiya aniqlovchisan. JSON formatda javob ber.

BUGUNGI SANGA: {current_date} ({current_year}-yil, {current_month}-oy, {current_day}-sana)

MUHIM: Agar xabarda ANIQ SUMMA bo'lmasa yoki oddiy so'z bo'lsa (ok, ha, yo'q, salom, rahmat, yaxshi), tranzaksiya TOPILMADI deb javob ber:
{{"transactions":[],"total_confidence":0}}

QOIDALAR:
1. TYPE:
   - "income" = daromad, oylik, ish haqi, maosh, tushdi, keldi
   - "expense" = xarajat, sotib oldim, ketdi, sarfladim, to'ladim
   - "debt_lent" = qarz berdim, qarz berish (men berdim)
   - "debt_borrowed" = qarz oldim, qarz olish (men oldim)

2. VALYUTA: UZS (default), USD, EUR, RUB, TRY

3. KATEGORIYALAR:
   - "ish haqi" = oylik, maosh
   - "biznes" = savdo, do'kon
   - "ovqat" = somsa, lavash, restoran, kafe
   - "transport" = taksi, benzin
   - "uy" = kvartira, kommunal
   - "qarz" = qarz berish/olish
   - "boshqa" = qolganlar

4. QARZ uchun qo'shimcha:
   - "person_name" = kimga/kimdan (MAJBURIY qarz uchun!)
   - "due_date" = qaytarish sanasi (YYYY-MM-DD formatida, MUHIM - sana tushunish qoidalari quyida)

SANA TUSHUNISH QOIDALARI (MUHIM!):
- "keyingi yil 31-dekabr" → {current_year + 1}-12-31
- "keyingi yil" → {current_year + 1}-12-31 (yil oxiri)
- "2 haftadan keyin" → bugundan 14 kun keyin (YYYY-MM-DD)
- "keyingi oy oxrida" → keyingi oyning oxirgi kuni (YYYY-MM-DD)
- "keyingi oy 15-sana" → keyingi oyning 15-sanasi (YYYY-MM-DD)
- "3 oydan keyin" → 3 oy keyin (YYYY-MM-DD)
- "31-dekabr" → agar hozir {current_month}-oy bo'lsa va 31-dekabr o'tgan bo'lsa, {current_year + 1}-12-31, aks holda {current_year}-12-31
- "2026-yil 31-dekabr" → 2026-12-31
- "2025-yil 31-dekabr" → 2025-12-31
- Sana kiritilmagan bo'lsa → due_date bo'sh qoldiriladi

MISOLLAR:
"ok" → {{"transactions":[],"total_confidence":0}}
"salom" → {{"transactions":[],"total_confidence":0}}
"80k somsa" → {{"transactions":[{{"amount":80000,"type":"expense","category":"ovqat","currency":"UZS"}}]}}
"oylik 3mln" → {{"transactions":[{{"amount":3000000,"type":"income","category":"ish haqi","currency":"UZS"}}]}}
"Hasanga 500k qarz berdim" → {{"transactions":[{{"amount":500000,"type":"debt_lent","category":"qarz","currency":"UZS","person_name":"Hasan"}}]}}
"Komildan 200k qarz oldim" → {{"transactions":[{{"amount":200000,"type":"debt_borrowed","category":"qarz","currency":"UZS","person_name":"Komil"}}]}}
"Ali dan 100 000 sum qarz oldim keyingi yil 31-dekabrga qayttarishim kerak" → {{"transactions":[{{"amount":100000,"type":"debt_borrowed","category":"qarz","currency":"UZS","person_name":"Ali","due_date":"{current_year + 1}-12-31"}}]}}

FORMAT: {{"transactions":[{{...}}],"total_confidence":0.9}}"""

            user_prompt = f'Message: "{text}"\n\nJSON:'

            # Mistral-7B-Instruct orqali (OpenRouter) - sync client bilan
            def call_ai():
                try:
                    if self.openrouter_client:
                        response = self.openrouter_client.chat.completions.create(
                            model="mistralai/mistral-7b-instruct",
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt}
                            ],
                            max_tokens=150,
                            temperature=0.0
                        )
                        return response.choices[0].message.content
                    else:
                        raise Exception("OpenRouter client not available")
                except Exception as e:
                    logging.warning(f"Mistral xatolik, GPT-3.5 ga o'tilmoqda: {e}")
                    # Fallback: GPT-3.5-turbo (sync)
                    from openai import OpenAI
                    openai_sync = OpenAI(api_key=OPENAI_API_KEY)
                    response = openai_sync.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        max_tokens=150,
                        temperature=0.0
                    )
                    return response.choices[0].message.content
            
            loop = asyncio.get_event_loop()
            ai_response = await loop.run_in_executor(None, call_ai)
            
            logging.info(f"AI moliyaviy javob: {ai_response}")
            print(f"DEBUG AI raw response: {ai_response}")
            
            # JSON parse qilish
            try:
                # JSON ni tozalash
                ai_response = ai_response.strip()
                if '```json' in ai_response:
                    ai_response = ai_response.split('```json')[1].split('```')[0]
                elif '```' in ai_response:
                    ai_response = ai_response.split('```')[1]
                
                # Agar bir nechta JSON obyekti bo'lsa, faqat birinchisini olish
                # {"transactions":...} pattern ni topish
                if ai_response.count('{"transactions"') > 1:
                    # Faqat birinchi JSON obyektini olish
                    first_json_end = ai_response.find('}', ai_response.find(']')) + 1
                    if first_json_end > 0:
                        ai_response = ai_response[:first_json_end]
                
                # Yangi qatorlardan keyin kelgan ortiqcha ma'lumotlarni olib tashlash
                if '\n\n' in ai_response:
                    ai_response = ai_response.split('\n\n')[0]
                
                # Agar AI "tushunmasligini" yozgan bo'lsa
                if not ai_response or 'tushunish_e_madi' in ai_response.lower():
                    logging.info("AI tushunmadi")
                    return {"transactions": [], "total_confidence": 0, "error": "tushunish_e_madi"}
                
                # Faqat JSON qismini olish - { dan } gacha
                json_start = ai_response.find('{')
                json_end = ai_response.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    ai_response = ai_response[json_start:json_end]
                
                data = json.loads(ai_response)
                
                # Agar transactions bo'sh bo'lsa
                if not data.get('transactions'):
                    return {"transactions": [], "total_confidence": 0, "error": "tushunish_e_madi"}
                
                return data
                
            except json.JSONDecodeError as e:
                logging.error(f"JSON parse xatolik: {e}")
                logging.error(f"AI javobi: {ai_response}")
                
                # Fallback - regex bilan birinchi JSON ni olishga harakat
                try:
                    import re
                    json_pattern = r'\{"transactions":\s*\[.*?\]\s*(?:,\s*"total_confidence":\s*[\d.]+)?\}'
                    match = re.search(json_pattern, ai_response, re.DOTALL)
                    if match:
                        data = json.loads(match.group())
                        return data
                except:
                    pass
                
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
                # Agar tranzaksiya yo'q bo'lsa, xato qaytaramiz
                return {
                    'is_valid': False,
                    'message': "❌ Hech qanday to'g'ri tranzaksiya topilmadi. Iltimos, aniqroq yozing."
                }
            
            # Har bir tranzaksiyani validatsiya qilish
            validated_transactions = []
            
            for trans in transactions:
                # Amount validatsiya
                amount = trans.get('amount', 0)
                if not isinstance(amount, (int, float)):
                    amount = 0
                
                # 0 yoki juda katta summalarni skip qilamiz
                if amount == 0 or amount > 10000000000:  # 10 milliard dan ko'p
                    continue
                    
                # Type validatsiya
                trans_type = trans.get('type', '')
                if trans_type not in ['income', 'expense', 'debt', 'debt_lent', 'debt_borrowed']:
                    continue
                
                # person_name va due_date olish (qarzlar uchun)
                person_name = trans.get('person_name', '')
                due_date = trans.get('due_date', '')
                
                # Category validatsiya va to'g'rilash
                category = trans.get('category', 'boshqa').lower().strip()
                valid_categories = [
                    'ovqat', 'transport', 'ish haqi', 'maosh', 'biznes', 'investitsiya',
                    'kiyim', 'uy', 'sog\'liq', 'ta\'lim', 'o\'yin-kulgi', 'boshqa'
                ]
                
                # Kategoriya mapping - noto'g'ri kategoriyalarni to'g'rilash
                category_mapping = {
                    'ish haqi': 'ish haqi',
                    'maosh': 'ish haqi',
                    'oylik': 'ish haqi',
                    'daromad': 'ish haqi' if trans_type == 'income' else 'boshqa',
                    'ovqat': 'ovqat',
                    'oziq': 'ovqat',
                    'oziq-ovqat': 'ovqat',
                    'taom': 'ovqat',
                    'yegimlik': 'ovqat',
                    'ichimlik': 'ovqat',
                    'somsa': 'ovqat',
                    'non': 'ovqat',
                    'lavash': 'ovqat',
                    'shashlik': 'ovqat',
                    'kebab': 'ovqat',
                    'pizza': 'ovqat',
                    'burger': 'ovqat',
                    'restoran': 'ovqat',
                    'kafe': 'ovqat',
                    'kofe': 'ovqat',
                    'choy': 'ovqat',
                    'gazak': 'ovqat',
                    'transport': 'transport',
                    'taksi': 'transport',
                    'avtobus': 'transport',
                    'metro': 'transport',
                    'mashina': 'transport',
                    'benzin': 'transport',
                    'yoqilg\'i': 'transport',
                    'kiyim': 'kiyim',
                    'uy': 'uy',
                    'kvartira': 'uy',
                    'kommunal': 'uy',
                    'elektr': 'uy',
                    'gaz': 'uy',
                    'suv': 'uy',
                    'internet': 'uy',
                    'telefon': 'uy',
                    'sog\'liq': 'sog\'liq',
                    'shifokor': 'sog\'liq',
                    'dori': 'sog\'liq',
                    'davolanish': 'sog\'liq',
                    'ta\'lim': 'ta\'lim',
                    'maktab': 'ta\'lim',
                    'universitet': 'ta\'lim',
                    'kurs': 'ta\'lim',
                    'kitob': 'ta\'lim',
                    'o\'yin-kulgi': 'o\'yin-kulgi',
                    'kino': 'o\'yin-kulgi',
                    'teatr': 'o\'yin-kulgi',
                    'konsert': 'o\'yin-kulgi',
                    'o\'yin': 'o\'yin-kulgi',
                    'sayr': 'o\'yin-kulgi',
                    'biznes': 'biznes',
                    'savdo': 'biznes',
                    'investitsiya': 'investitsiya',
                    'boshqa': 'boshqa'
                }
                
                # Kategoriyani to'g'rilash
                if category in category_mapping:
                    category = category_mapping[category]
                elif category not in valid_categories:
                    # Agar kategoriya noto'g'ri bo'lsa, original_text dan kategoriyani aniqlashga harakat qilamiz
                    original_text_lower = original_text.lower()
                    if any(word in original_text_lower for word in ['somsa', 'non', 'lavash', 'shashlik', 'kebab', 'pizza', 'burger', 'restoran', 'kafe', 'kofe', 'choy', 'gazak', 'oziq', 'taom', 'yegimlik', 'ichimlik']):
                        category = 'ovqat'
                    elif any(word in original_text_lower for word in ['taksi', 'avtobus', 'metro', 'mashina', 'benzin', 'yoqilg\'i']):
                        category = 'transport'
                    elif any(word in original_text_lower for word in ['oylik', 'maosh', 'ish haqi']) and trans_type == 'income':
                        category = 'ish haqi'
                    else:
                        category = 'boshqa'
                
                # "maosh" ni "ish haqi" ga aylantirish
                if category == 'maosh':
                    category = 'ish haqi'
                
                # Type va category mosligini tekshirish va to'g'rilash
                original_text_lower = original_text.lower()
                
                # Agar income bo'lsa va kategoriya ovqat bo'lsa, bu noto'g'ri - expense bo'lishi kerak
                if trans_type == 'income' and category == 'ovqat':
                    # Original text dan qarab, agar ovqat so'zi bor bo'lsa, expense bo'lishi kerak
                    if any(word in original_text_lower for word in ['somsa', 'non', 'lavash', 'shashlik', 'kebab', 'pizza', 'burger', 'restoran', 'kafe', 'kofe', 'choy', 'gazak', 'oziq', 'taom', 'yegimlik', 'ichimlik']):
                        trans_type = 'expense'
                        category = 'ovqat'
                
                # Agar "oldim" so'zi bor va ovqat so'zi bor bo'lsa, expense bo'lishi kerak
                if trans_type == 'income' and 'oldim' in original_text_lower:
                    if any(word in original_text_lower for word in ['somsa', 'non', 'lavash', 'shashlik', 'kebab', 'pizza', 'burger', 'restoran', 'kafe', 'kofe', 'choy', 'gazak', 'oziq', 'taom', 'yegimlik', 'ichimlik']):
                        trans_type = 'expense'
                        category = 'ovqat'
                
                # Agar "ish haqi" kategoriyasi bo'lsa va type expense bo'lsa, bu noto'g'ri - income bo'lishi kerak
                if trans_type == 'expense' and category == 'ish haqi':
                    # Original text dan qarab, agar "oylik", "maosh", "ish haqi" so'zlari bor bo'lsa, income bo'lishi kerak
                    if any(word in original_text_lower for word in ['oylik', 'maosh', 'ish haqi', 'tushdi', 'oldim']):
                        trans_type = 'income'
                        category = 'ish haqi'
                
                # Valyuta validatsiya
                currency = trans.get('currency', 'UZS')
                currency = currency.upper() if currency else 'UZS'
                if currency not in ['UZS', 'USD', 'EUR', 'RUB', 'TRY']:
                    currency = 'UZS'
                
                # Description validatsiya - AI description kiritmaydi, shuning uchun avtomatik qo'shamiz
                description = trans.get('description', '').strip()
                if not description:
                    currency_names = {'UZS': "so'm", 'USD': "dollar", 'EUR': "evro", 'RUB': "rubl", 'TRY': "lira"}
                    currency_name = currency_names.get(currency, currency)
                    if currency != 'UZS':
                        description = f"{trans_type}: {amount:,.2f} {currency_name} ({category})"
                    else:
                        description = f"{trans_type}: {amount:,.0f} so'm ({category})"
                elif len(description) > 100:
                    description = description[:100]
                
                # Confidence validatsiya - total_confidence dan foydalanamiz
                trans_confidence = trans.get('confidence', total_confidence)
                # Agar tranzaksiyada confidence bo'lmasa, total_confidence ishlatamiz
                
                validated_transactions.append({
                    'amount': float(amount),
                    'type': trans_type,
                    'category': category,
                    'currency': currency,
                    'description': description,
                    'confidence': trans_confidence,
                    'person_name': person_name,  # Qarz uchun
                    'due_date': due_date  # Qarz qaytarish sanasi
                })
            
            if not validated_transactions or data.get('error') == 'tushunish_e_madi':
                return {
                    'is_valid': False,
                    'message': "❌ Hech qanday to'g'ri tranzaksiya topilmadi. Iltimos, aniqroq yozing."
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
                transaction_data['original_text'] = original_text
                
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
                    return await self._show_single_transaction_confirmation(confirmed_transactions[0], user_id, original_text)
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
                currency = trans.get('currency', 'UZS')
                
                type_emoji = {
                    "income": "📈",
                    "expense": "📉",
                    "debt": "💳"
                }.get(trans['type'], "❓")
                
                # Valyutani formatlash
                currency_names = {'UZS': "so'm", 'USD': "dollar", 'EUR': "evro", 'RUB': "rubl", 'TRY': "lira"}
                currency_symbols = {'UZS': "", 'USD': "🇺🇸", 'EUR': "🇪🇺", 'RUB': "🇷🇺", 'TRY': "🇹🇷"}
                currency_name = currency_names.get(currency, currency)
                currency_symbol = currency_symbols.get(currency, "💰")
                
                if currency != 'UZS':
                    amount_text = f"{currency_symbol} {trans['amount']:,.2f} {currency_name}"
                else:
                    amount_text = f"{trans['amount']:,.0f} so'm"
                
                message += f"{item['index']}. {type_emoji} **{amount_text}**\n"
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

    async def _show_single_transaction_confirmation(self, transaction_item: Dict[str, Any], user_id: int, original_text: str = "") -> Dict[str, Any]:
        """Bitta aniq tranzaksiya uchun tasdiqlash - YANGI FORMAT"""
        try:
            trans = transaction_item['data']
            trans_type = trans.get('type', 'expense')
            currency = trans.get('currency', 'UZS')
            amount = trans.get('amount', 0)
            category = trans.get('category', 'boshqa')
            person_name = trans.get('person_name', '')
            due_date = trans.get('due_date', '')
            
            formatted_date = self._format_human_date(trans.get('transaction_time'))
            
            # Valyuta formatlash
            currency_names = {'UZS': 'UZS', 'USD': 'USD', 'EUR': 'EUR', 'RUB': 'RUB', 'TRY': 'TRY'}
            currency_display = currency_names.get(currency, 'UZS')
            amount_formatted = f"{currency_display} {amount:,.0f}"
            
            original_text_clean = (original_text or "").strip()
            if not original_text_clean:
                original_text_clean = trans.get('original_text', '').strip()
            
            # Yangi format bo'yicha xabar
            if trans_type == 'income':
                message = f"💰 **Kirim:**\n"
                message += f"Sana: {formatted_date}\n\n"
                message += f"Summa: {amount_formatted}\n"
                message += f"Kategoriya: {category}\n"
                if original_text_clean:
                    message += f"Izoh: {original_text_clean}\n"
                    
            elif trans_type == 'expense':
                message = f"💸 **Chiqim:**\n"
                message += f"Sana: {formatted_date}\n\n"
                message += f"Summa: {amount_formatted}\n"
                message += f"Kategoriya: {category}\n"
                if original_text_clean:
                    message += f"Izoh: {original_text_clean}\n"
                    
            elif trans_type == 'debt_borrowed':
                message = f"💳 **Qarz olish:**\n"
                message += f"Olingan vaqt: {formatted_date}\n\n"
                
                # Kontakt ma'lumotlarini tekshirish va ko'rsatish
                contact_info_text = ""
                if person_name:
                    contact = await db.get_or_create_contact(user_id, person_name)
                    if contact and not contact.get('is_new'):
                        # Mavjud kontakt
                        contact_info_text = f"👤 **{person_name}** (Kontaktdagi shaxs)\n"
                    else:
                        # Yangi kontakt qo'shildi
                        contact_info_text = f"👤 **{person_name}** (Yangi kontakt qo'shildi)\n"
                    message += contact_info_text
                
                message += f"Summasi: {amount_formatted}\n"
                if due_date:
                    message += f"Qaytarish vaqti: {self._format_human_date(due_date)}\n"
                if original_text_clean:
                    message += f"Izoh: {original_text_clean}\n"
                
                # Ogohlantirishlar
                warnings = []
                if not person_name:
                    warnings.append("⚠️ Ism kiritilmagan (keyinchalik tahrirlash mumkin)")
                if not due_date:
                    warnings.append("⚠️ Qaytarish sanasi ko'rsatilmagan (keyinchalik tahrirlash mumkin)")
                
                if warnings:
                    message += f"\n{' | '.join(warnings)}\n"
                    
            elif trans_type == 'debt_lent':
                message = f"💳 **Qarz berish:**\n"
                message += f"Berilgan vaqt: {formatted_date}\n\n"
                
                # Kontakt ma'lumotlarini tekshirish va ko'rsatish
                contact_info_text = ""
                if person_name:
                    contact = await db.get_or_create_contact(user_id, person_name)
                    if contact and not contact.get('is_new'):
                        # Mavjud kontakt
                        contact_info_text = f"👤 **{person_name}** (Kontaktdagi shaxs)\n"
                    else:
                        # Yangi kontakt qo'shildi
                        contact_info_text = f"👤 **{person_name}** (Yangi kontakt qo'shildi)\n"
                    message += contact_info_text
                
                message += f"Summasi: {amount_formatted}\n"
                if due_date:
                    message += f"Qaytarish vaqti: {self._format_human_date(due_date)}\n"
                if original_text_clean:
                    message += f"Izoh: {original_text_clean}\n"
                
                # Ogohlantirishlar
                warnings = []
                if not person_name:
                    warnings.append("⚠️ Ism kiritilmagan (keyinchalik tahrirlash mumkin)")
                if not due_date:
                    warnings.append("⚠️ Qaytarish sanasi ko'rsatilmagan (keyinchalik tahrirlash mumkin)")
                
                if warnings:
                    message += f"\n{' | '.join(warnings)}\n"
                    
            else:  # Eski format uchun fallback (debt)
                type_emoji = {"income": "💰", "expense": "💸", "debt": "💳"}.get(trans_type, "❓")
                message = f"{type_emoji} **Tranzaksiya:**\n"
                message += f"Sana: {formatted_date}\n\n"
                message += f"Summa: {amount_formatted}\n"
                message += f"Kategoriya: {category}\n"
                if original_text_clean:
                    message += f"Izoh: {original_text_clean}\n"
            
            # Qarz uchun qo'shimcha ma'lumotlar (tugmalar uchun)
            extra_data = {}
            if trans_type in ('debt_borrowed', 'debt_lent'):
                missing_fields = []
                if not person_name:
                    missing_fields.append('person_name')
                if not due_date:
                    missing_fields.append('due_date')
                extra_data['missing_fields'] = missing_fields
                extra_data['has_person_name'] = bool(person_name)
                extra_data['has_due_date'] = bool(due_date)
            
            return {
                "success": True,
                "type": "single_confirmation",
                "message": message,
                "transaction_data": {
                    'transactions': [transaction_item],
                    'user_id': user_id
                },
                "auto_save": True,  # Avtomatik saqlash
                **extra_data
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
                
                # Status izoh - taxminiy ma'lumotlarni olib tashladik
                
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
                    currency = trans.get('currency', 'UZS')
                    person_name = trans.get('person_name', '')
                    due_date = trans.get('due_date', '')
                    trans_type = trans['type']
                    
                    # To'g'ridan-to'g'ri db.add_transaction ni chaqirish
                    # Bu debt_lent/debt_borrowed ni to'g'ri qayta ishlaydi
                    transaction_id = await db.add_transaction(
                        user_id=user_id,
                        transaction_type=trans_type,  # Original type (debt_lent, debt_borrowed, income, expense)
                        amount=trans['amount'],
                        category=trans['category'],
                        description=trans.get('description', ''),
                        currency=currency,
                        person_name=person_name,
                        due_date=due_date
                    )
                    
                    reminder_created = False
                    reminder_date_str = None
                    if transaction_id:
                        # Qarz uchun eslatma yaratish - faqat qaytarish sanasi bo'lsa
                        if trans_type in ('debt_lent', 'debt_borrowed') and due_date:
                            try:
                                await db.execute_insert(
                                    "INSERT INTO debt_reminders (user_id, transaction_id, reminder_date) VALUES (%s, %s, %s)",
                                    (user_id, transaction_id, due_date)
                                )
                                reminder_created = True
                                reminder_date_str = due_date
                            except Exception as e:
                                logging.error(f"Qarz eslatmasi yaratishda xatolik: {e}")
                        
                        saved_transactions.append({
                            'id': transaction_id,
                            'index': item.get('index', 1),
                            'amount': trans['amount'],
                            'type': trans_type,
                            'category': trans['category'],
                            'currency': currency,
                            'description': trans.get('description', ''),
                            'person_name': person_name,
                            'due_date': due_date,
                            'confidence': trans.get('confidence', 0),
                            'reminder_created': reminder_created,
                            'reminder_date': reminder_date_str
                        })
                    else:
                        failed_transactions.append(item.get('index', 1))
                        
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
                
                # Valyutani formatlash
                currency = trans.get('currency', 'UZS')
                currency_names = {'UZS': "so'm", 'USD': "dollar", 'EUR': "evro", 'RUB': "rubl", 'TRY': "lira"}
                currency_symbols = {'UZS': "", 'USD': "🇺🇸", 'EUR': "🇪🇺", 'RUB': "🇷🇺", 'TRY': "🇹🇷"}
                currency_name = currency_names.get(currency, currency)
                currency_symbol = currency_symbols.get(currency, "💰")
                
                if currency != 'UZS':
                    amount_text = f"{currency_symbol} {trans['amount']:,.2f} {currency_name}"
                else:
                    amount_text = f"{trans['amount']:,.0f} so'm"
                
                message += f"#{trans['index']} {type_emoji} {amount_text} - {trans['category']}\n"
                
                # Jami hisobga qo'shish (valyutani so'mga o'girib)
                # db allaqachon fayl boshida import qilingan
                try:
                    rates = await db.get_currency_rates()
                    rate = rates.get(currency, 1.0)
                except:
                    rate = 1.0
                amount_uzs = trans['amount'] * rate
                
                if trans['type'] == 'income':
                    total_income += amount_uzs
                elif trans['type'] == 'expense':
                    total_expense += amount_uzs
                elif trans['type'] == 'debt':
                    total_debt += amount_uzs
            
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
                "type": "completed",  # Type qo'shish
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
                             description: str, transaction_type: TransactionType, 
                             currency: str = 'UZS', person_name: str = None, 
                             due_date: str = None) -> int:
        """Tranzaksiyani ma'lumotlar bazasiga saqlash (valyuta va qarz ma'lumotlari bilan)"""
        try:
            # Valyutani to'g'ri formatda saqlash
            currency = currency.upper() if currency else 'UZS'
            if currency not in ['UZS', 'USD', 'EUR', 'RUB', 'TRY']:
                currency = 'UZS'
            
            # db.add_transaction orqali saqlash - bu qarzlarni ham to'g'ri qayta ishlaydi
            transaction_id = await db.add_transaction(
                user_id=user_id,
                transaction_type=transaction_type.value,
                amount=amount,
                category=category,
                description=description,
                currency=currency,
                person_name=person_name,
                due_date=due_date
            )
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

    def generate_transaction_buttons(self, transactions_data: Dict[str, Any], auto_saved: bool = True) -> list:
        """Tranzaksiyalar uchun tugmalarni yaratish - YANGI FORMAT
        
        Args:
            transactions_data: Tranzaksiya ma'lumotlari
            auto_saved: Avtomatik saqlangan bo'lsa True (faqat O'chirish/Tahrirlash ko'rsatiladi)
        """
        try:
            transactions = transactions_data.get('transactions', [])
            transaction_type = transactions_data.get('type', 'multiple_preview')
            
            if auto_saved:
                # Avtomatik saqlangan - faqat O'chirish va Tahrirlash
                if transaction_type == 'single_confirmation' or len(transactions) == 1:
                    return [
                        [
                            {"text": "✏️ Tahrirlash", "callback_data": "trans_edit_1"},
                            {"text": "🗑️ O'chirish", "callback_data": "trans_delete_1"}
                        ]
                    ]
                else:
                    # Ko'p tranzaksiya uchun
                    buttons = []
                    for item in transactions:
                        index = item.get('index', 1)
                        buttons.append([
                            {"text": f"✏️ #{index}", "callback_data": f"trans_edit_{index}"},
                            {"text": f"🗑️ #{index}", "callback_data": f"trans_delete_{index}"}
                        ])
                    return buttons
            else:
                # Eski format - saqlash tugmalari bilan
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
                    for item in transactions:
                        index = item['index']
                        buttons.append([
                            {"text": f"💾 #{index}", "callback_data": f"trans_save_{index}"},
                            {"text": f"🗑️ #{index}", "callback_data": f"trans_delete_{index}"}
                        ])
                    buttons.append([
                        {"text": "✅ Hammasini saqlash", "callback_data": "trans_all"},
                        {"text": "❌ Bekor qilish", "callback_data": "trans_cancel"}
                    ])
                    return buttons
            
        except Exception as e:
            logging.error(f"Tugmalar yaratishda xatolik: {e}")
            return []

    async def _ensure_ai_guess(self, data: Dict[str, Any], text: str) -> Dict[str, Any]:
        """AI natijasini tekshirib, zarur bo'lsa qo'shimcha taxmin qilish"""
        transactions = data.get('transactions', [])
        has_positive_amount = any(
            isinstance(t.get('amount'), (int, float)) and t.get('amount', 0) > 0
            for t in transactions
        )

        if transactions and has_positive_amount:
            return data

        try:
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": """Siz moliyaviy tahlilchi AI siz. Oldingi natijada summalar topilmadi yoki 0 bo'ldi. Endi aynan shu matndan real summalarni toping yoki eng mantiqli taxminni yozing.

QOIDALAR:
- Hech qachon "tushunmadim" demang, har doim aniq taxmin qiling
- "10 ming" = 10000, "25k" = 25000, "50 mingga" = 50000
- Gap oxiri tushib qolsa ham ma'nosini to'ldiring
- Har bir tranzaksiya uchun type, category, amount, description, confidence maydonlarini qaytaring
- JSON formatida javob bering"""
                    },
                    {
                        "role": "user",
                        "content": f"Matn: {text}\n\nIltimos, summani aniqlab yoki taxmin qilib JSON shaklida qaytaring."
                    }
                ],
                temperature=0.2,
                max_tokens=1000,
            )

            ai_response = response.choices[0].message.content.strip()
            if "```json" in ai_response:
                ai_response = ai_response.split("```json")[1].split("```")[0]
            elif "```" in ai_response:
                ai_response = ai_response.split("```")[1]

            try:
                guessed_data = json.loads(ai_response)
            except json.JSONDecodeError:
                logging.warning("AI taxminiy javob JSON emas, fallback qo'llanadi")
                guessed_data = {}

            guessed_transactions = guessed_data.get('transactions', [])

            if guessed_transactions:
                return guessed_data

        except Exception as e:
            logging.warning(f"AI taxminiy yordamda xatolik: {e}")

        return data