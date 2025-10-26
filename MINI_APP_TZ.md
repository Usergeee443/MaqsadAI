# Mini ilova - To'lov moduli (TZ)

## 1. Umumiy ma'lumot

**Loyiha:** Balans AI Bot - Mini ilova to'lov moduli  
**Maqsad:** Foydalanuvchilar uchun qulay mini ilova orqali tarif sotib olish  
**Texnologiyalar:** React, TypeScript, Telegram WebApp API  
**URL:** `https://pulbot-mini-app.onrender.com/payment`

## 2. Funksionallik

### 2.1. Asosiy funksiyalar

- ✅ Tarifni tanlash (FREE, PLUS, MAX, BUSINESS va boshqalar)
- ✅ Muddatni tanlash (1, 3, 6, 12 oy)
- ✅ Narxni hisoblash (chegirmalar bilan)
- ✅ To'lov usulini tanlash
- ✅ Test rejimida to'lov qilish
- ✅ To'lov natijasini botga yuborish

### 2.2. UX oqimi

```
1. Mini ilova ochiladi (tarif tanlash)
2. Foydalanuvchi tarifni tanlaydi
3. Muddatni tanlaydi (1/3/6/12 oy)
4. Narx ko'rsatiladi (chegirma bilan)
5. To'lov usulini tanlaydi
6. Test rejimida to'lov qiladi
7. Muvaffaqiyatli xabar ko'rsatiladi
8. Botga xabar yuboriladi
```

## 3. UI dizayn

### 3.1. Sidebar (Yon panel)

```tsx
interface SidebarProps {
  steps: string[];
  currentStep: number;
}
```

**Bosqichlar:**
1. Tarif tanlash
2. Muddat tanlash
3. To'lov

### 3.2. Asosiy ekranlar

#### 3.2.1. Tarif tanlash ekrani

- **Tarif kartalari:** Har bir tarif uchun alohida karta
- **Imkoniyatlar ro'yxati:** Har bir tarif uchun amallar
- **Narx ko'rsatish:** Oylik/yillik narx

#### 3.2.2. Muddat tanlash ekrani

- **Muddat variantlari:** 1, 3, 6, 12 oy
- **Chegirma ko'rsatish:** Uzoq muddatli obunada
- **Jami summa:** To'liq summani ko'rsatish

#### 3.2.3. To'lov ekrani

- **To'lov usullari:** Test rejimida to'lov
- **Ma'lumotlar kiritish:** Test kartasi ma'lumotlari
- **Tekshiruv:** Ma'lumotlar to'g'riligini tekshirish

### 3.3. Responsive dizayn

- Mobile-first yondashuv
- Telegram UI dizayn prinsiplariga mosligi
- Dark/Light mode (Telegram parametrlariga mos)

## 4. Backend integratsiya

### 4.1. Bot API endpointlar (Asosiy server)

Mini ilova shu endpointlardan foydalanadi:

```typescript
// 1. Tariflar ro'yxatini olish
GET https://your-bot-server.com/api/tariffs
Response: {
  tariffs: [
    { code: 'PLUS', name: 'Plus', monthly_price: 99900 },
    { code: 'MAX', name: 'Max', monthly_price: 199900 }
  ],
  discount_rates: {
    1: 0,   // 1 oy: chegirma yo'q
    3: 5,   // 3 oy: 5% chegirma
    6: 10,  // 6 oy: 10% chegirma
    12: 20  // 12 oy: 20% chegirma
  }
}

// 2. Foydalanuvchi ma'lumotlarini olish
GET https://your-bot-server.com/api/user/{user_id}
Headers: { Authorization: 'Bearer {token}' }
Response: {
  user_id: number;
  current_tariff: string;
  tariff_expires_at: string | null;
}

// 3. To'lovni amalga oshirish (Mini ilova serveridan POST so'rov)
POST https://your-bot-server.com/api/payment/webhook
Body: {
  user_id: number;
  tariff: string;
  months: number;
  amount: number;
  payment_method: 'test' | 'click' | 'payme';
}
Response: {
  success: boolean;
  message: string;
  new_tariff: string;
  expires_at: string;
}
```

### 4.2. Mini ilova server endpointlar

Mini ilova o'z serverida shu endpointlarni taqdim etadi:

```typescript
// 1. Mini ilova sahifasi
GET https://pulbot-mini-app.onrender.com/payment
// Bu sahifa React komponentlardan tashkil topadi

// 2. Telegram WebApp initData ni validate qilish
POST /api/auth
Body: { init_data: string }
Response: {
  user_id: number;
  user_info: object;
}

// 3. Tariflarni olish (Bot serverdan proxy qiladi)
GET /api/tariffs
Response: { /* Bot server response */ }

// 4. To'lov webhook (Bot serverga yuboradi)
POST /api/process-payment
Body: {
  user_id: number;
  tariff: string;
  months: number;
  payment_method: string;
}
Response: {
  success: boolean;
  message: string;
}
```

### 4.2. Authentication

```typescript
// Telegram WebApp initData dan foydalanib authentication
const initData = window.Telegram.WebApp.initData;
const response = await fetch(`/api/auth?init_data=${initData}`);
const { user_id } = await response.json();
```

## 5. Test rejimi

### 5.1. Test kartasi ma'lumotlari

```
Karta raqami: 8600 0000 0000 0000
CVV: 123
Muddati: 12/25
```

### 5.2. Test to'lov jarayoni

1. Foydalanuvchi test kartani to'ldiradi
2. Ma'lumotlar tekshiriladi (frontend validatsiya)
3. Backend ga POST so'rov yuboriladi
4. Backend bazaga yozadi va tarifni aktiv qiladi
5. Muvaffaqiyatli javob qaytariladi
6. Foydalanuvchiga muvaffaqiyatli xabar ko'rsatiladi

## 6. Bot integratsiya (Webhook orqali)

### 6.1. To'lov jarayoni

Mini ilova to'lovni amalga oshirgandan keyin webhook orqali bot serverga ma'lumot yuboradi:

```typescript
// Mini ilova to'lov muvaffaqiyatli bo'lganda
const response = await fetch('https://your-bot-server.com/api/payment/webhook', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    user_id: userId,
    tariff: selectedTariff,
    months: selectedMonths,
    amount: finalPrice,
    payment_method: 'test'
  })
});

const result = await response.json();
// result.success = true bo'lsa, tarif aktivlashgan
```

### 6.2. Bot handler (bot serverda)

Bot server webhook orqali to'lov ma'lumotlarini qabul qiladi va bazaga yozadi:

```python
@app.post("/api/payment/webhook")
async def payment_webhook(data: dict):
    """Mini ilova dan to'lov ma'lumotlarini qabul qilish"""
    user_id = data.get("user_id")
    tariff = data.get("tariff")
    months = data.get("months", 1)
    amount = data.get("amount")
    
    # Tarifni aktiv qilish
    expires_at = datetime.now() + timedelta(days=30 * months)
    await db.add_user_subscription(user_id, tariff, expires_at)
    await db.set_active_tariff(user_id, tariff)
    
    # Foydalanuvchiga xabar yuborish
    await bot.send_message(
        user_id,
        f"✅ To'lov muvaffaqiyatli amalga oshirildi!\n"
        f"📦 Tarif: {tariff}\n"
        f"⏰ Muddati: {expires_at.strftime('%d.%m.%Y')}"
    )
    
    return {"success": True}
```

## 7. Holat boshqaruvi

### 7.1. State management

```typescript
interface PaymentState {
  selectedTariff: string | null;
  selectedMonths: number;
  calculatedPrice: {
    total: number;
    discount: number;
    final: number;
  };
  paymentMethod: string;
  userInfo: {
    id: number;
    currentTariff: string;
  };
}
```

### 7.2. Hook structure

```typescript
const usePaymentFlow = () => {
  const [state, setState] = useState<PaymentState>(initialState);
  
  const selectTariff = (tariff: string) => { /* ... */ };
  const selectMonths = (months: number) => { /* ... */ };
  const calculatePrice = async () => { /* ... */ };
  const processPayment = async () => { /* ... */ };
  
  return { state, selectTariff, selectMonths, calculatePrice, processPayment };
};
```

## 8. Xatoliklarni boshqarish

### 8.1. Frontend xatoliklar

- **Tarif tanlanmagan:** "Iltimos, tarif tanlang"
- **Muddat tanlanmagan:** "Iltimos, muddat tanlang"
- **Narx hisoblash xatoligi:** "Narxni hisoblashda xatolik yuz berdi"
- **To'lov xatoligi:** "To'lovni amalga oshirishda xatolik"

### 8.2. Backend xatoliklar

- **Authentication xatoligi:** 401 Unauthorized
- **Validation xatoligi:** 400 Bad Request
- **Server xatoligi:** 500 Internal Server Error

## 9. Deploy

### 9.1. Build

```bash
npm run build
```

### 9.2. Deploy

```bash
# Render.com ga deploy
render deploy
```

### 9.3. Environment variables

```env
REACT_APP_API_URL=https://your-api-url.com
REACT_APP_WEBHOOK_URL=https://your-webhook-url.com
```

## 10. Test

### 10.1. Unit testlar

- Tarif tanlash funksiyasi
- Narx hisoblash funksiyasi
- To'lov validation

### 10.2. Integration testlar

- API so'rovlari
- Webhook handler
- Bot integratsiya

### 10.3. E2E testlar

- To'liq to'lov jarayoni
- Xatoliklar bilan ishlash

## 11. Xavfsizlik

- ✅ HTTPS ishlatish
- ✅ Input validation
- ✅ XSS himoyasi
- ✅ CSRF protection
- ✅ Rate limiting

## 12. Monitoring va analytics

- To'lovlar statistikasi
- Xatoliklar logi
- Foydalanuvchilar harakatlari
- Performance metrics

## 13. Keyingi bosqichlar

- Real to'lov integratsiyasi (Click, Payme)
- Sertifikat to'lov tizimi
- Chegirma kuponlar
- Referral tizimi

## 14. Contact

Savollar bo'lsa:
- Telegram: @nurmuxammadrayimov
- Email: support@balansai.com
