# Kategoriya va Kontakt Integratsiyasi

## Qisqa qo'llanma

Kategoriyalar endi kontaktlar bilan integratsiya qilingan. Chiqim/kirim kategoriyalari (masalan "Korzinka", "Ali") kontakt sifatida yaratilishi va barcha tranzaksiyalarni ko'rish mumkin.

## Database

**`transactions` jadvali:**
- `category_contact_id INT NULL` - kategoriya bilan bog'langan kontakt ID

**`contacts` jadvali:**
- `contact_type ENUM('person', 'category')` - kontakt turi
- `category_name VARCHAR(100)` - kategoriya nomi
- `transaction_type ENUM('income', 'expense', 'both')` - tranzaksiya turi

## API Endpoint'lar

**1. Kategoriya tranzaksiyalarini olish:**
```
GET /api/category/{category_name}/transactions?user_id={user_id}
```

**2. Kategoriya kontakt yaratish:**
```
POST /api/contacts
{
  "user_id": 123,
  "name": "Korzinka",
  "contact_type": "category",
  "category_name": "Korzinka",
  "transaction_type": "expense"
}
```

**3. Kategoriya bo'limi:**
```
GET /api/category/{category_name}/details?user_id={user_id}
```

## Mini App

Kategoriya bo'limida:
- Barcha tranzaksiyalar ro'yxati
- Jami summa va statistika
- Filtrlar (sana, summa)

**Misol:**
```jsx
// Kategoriya tranzaksiyalarini yuklash
const response = await fetch(
  `/api/category/${categoryName}/transactions?user_id=${userId}`
);
const { transactions, total_amount } = await response.json();
```

## Muhim

- Kategoriya kontakt sifatida yaratilishi mumkin
- Tranzaksiya saqlashda `category_contact_id` yuborish kerak
- Kategoriya bo'limi mini app da ko'rsatiladi

