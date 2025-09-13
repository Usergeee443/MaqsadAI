# Mini App O'rnatish Qo'llanmasi

## 1. Ngrok O'rnatish

### macOS uchun:
```bash
# Homebrew orqali
brew install ngrok

# Yoki to'g'ridan-to'g'ri yuklab olish
# https://ngrok.com/download
```

### Linux uchun:
```bash
# Snap orqali
sudo snap install ngrok

# Yoki to'g'ridan-to'g'ri yuklab olish
wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.zip
unzip ngrok-v3-stable-linux-amd64.zip
sudo mv ngrok /usr/local/bin/
```

### Windows uchun:
1. https://ngrok.com/download dan yuklab oling
2. ZIP faylni oching va `ngrok.exe` ni C:\Windows\System32 ga ko'chiring

## 2. Ngrok Hisob Yaratish

1. https://ngrok.com/ ga kiring
2. Hisob yarating
3. Authtoken oling: https://dashboard.ngrok.com/get-started/your-authtoken

## 3. Ngrok Authtoken Sozlash

```bash
ngrok config add-authtoken YOUR_AUTHTOKEN_HERE
```

## 4. Mini App Ishga Tushirish

### Variant 1: Avtomatik (Tavsiya etiladi)
```bash
python3 start_mini_app.py
```

### Variant 2: Qo'lda
```bash
# 1. Ngrok tunnel ishga tushirish
ngrok http 8000

# 2. Boshqa terminalda Mini App serverini ishga tushirish
python3 mini_app.py

# 3. Ngrok dan HTTPS URLni oling va main.py da yangilang
```

## 5. Botda Web App URL Yangilash

Ngrok dan olgan HTTPS URLni `main.py` faylida yangilang:

```python
web_app=WebAppInfo(url="https://your-actual-ngrok-url.ngrok.io")
```

## 6. Test Qilish

1. Botni ishga tushiring: `python3 run_bot.py`
2. Telegram da botga kiring
3. "📊 Hisobotlar" tugmasini bosing
4. "📊 Kengaytirilgan hisobotlar" tugmasini bosing
5. Mini App ochilishi kerak

## Muammolar va Yechimlar

### "Only HTTPS links are allowed" xatoligi
- Ngrok tunnel ishga tushmagan
- HTTP URL ishlatilgan (HTTPS kerak)

### Mini App ochilmaydi
- Ngrok tunnel ishlamayapti
- URL noto'g'ri
- Bot qayta ishga tushirilmagan

### "Connection refused" xatoligi
- Mini App server ishlamayapti
- Port 8000 band

## Xususiyatlari

- 📊 Interaktiv grafiklar
- 📈 Oylik tendensiya
- 🥧 Kategoriyalar bo'yicha taqsimot
- 📋 So'nggi tranzaksiyalar
- 💰 Balans ma'lumotlari
- 📱 Mobil optimizatsiya
- 🎨 Zamonaviy dizayn
