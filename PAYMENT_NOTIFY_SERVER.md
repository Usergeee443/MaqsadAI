# Payment Notify Server

Mini ilova bilan Bot o'rtasida to'lov xabarlarini uzatish uchun Flask server.

## Xususiyatlar

- ✅ POST so'rovlarni qabul qiladi: `/payment-notify`
- ✅ Foydalanuvchiga avtomatik xabar yuboradi
- ✅ JSON formatda ma'lumotlar
- ✅ 5005-portda ishlaydi
- ✅ Health check endpoint: `/health`

## O'rnatish

```bash
pip install -r requirements.txt
```

## Ishga tushirish

### To'g'ridan-to'g'ri

```bash
python3 payment_notify_server.py
```

### Background da

```bash
python3 payment_notify_server.py &
```

## API Endpoints

### POST /payment-notify

Mini ilovadan to'lov ma'lumotlarini qabul qiladi.

**Request Body:**
```json
{
  "user_id": 123456789,
  "amount": 29990,
  "status": "success"
}
```

**Response:**
```json
{
  "ok": true
}
```

**Status Codes:**
- `200`: Muvaffaqiyatli
- `400`: Noto'g'ri ma'lumotlar
- `500`: Server xatoligi

### GET /health

Server holatini tekshirish.

**Response:**
```json
{
  "status": "ok",
  "message": "Payment notify server is running"
}
```

## Xabar Formatlari

### Muvaffaqiyatli to'lov

```
✅ To'lov 29 990 so'm muvaffaqiyatli amalga oshirildi!
```

### Xatolik

```
⚠️ To'lov amalga oshmadi. Status: failed
```

## Test Qilish

### Qisqa test

```bash
python3 test_notify_server.py
```

Bu script:
1. Server holatini tekshiradi
2. Muvaffaqiyatli to'lov simulyatsiya qiladi
3. Xatolik to'lov simulyatsiya qiladi
4. Noto'g'ri so'rov testi
5. Barcha natijalarni ko'rsatadi

### Manual test

```bash
# Health check
curl http://localhost:5005/health

# Payment notify (success)
curl -X POST http://localhost:5005/payment-notify \
  -H "Content-Type: application/json" \
  -d '{"user_id": 123456789, "amount": 29990, "status": "success"}'

# Payment notify (failed)
curl -X POST http://localhost:5005/payment-notify \
  -H "Content-Type: application/json" \
  -d '{"user_id": 123456789, "amount": 29990, "status": "failed"}'
```

## Deployment

### Production

Production uchun WSGI server ishlatish tavsiya etiladi:

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5005 payment_notify_server:app
```

### PM2 bilan

```bash
pm2 start payment_notify_server.py --name payment-notify --interpreter python3
pm2 save
```

## Xatoliklarni Kuzatish

Server loglari stdout ga chiqadi:

```
✅ Xabar yuborildi: user_id=123456789, status=success
❌ Xatolik: ...
```

## Eslatma

- Server background thread da xabar yuboradi
- Bot token `.env` faylidan olinadi
- Server Flask development mode da ishlaydi

