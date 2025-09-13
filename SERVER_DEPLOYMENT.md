# Balans AI Bot Serverga Joylash Qo'llanmasi

## 1. Server Sozlamalari

### VPS/Server talablari:
- **OS**: Ubuntu 20.04+ yoki CentOS 8+
- **RAM**: Kamida 2GB
- **CPU**: 2 core
- **Disk**: 20GB+
- **Python**: 3.8+

## 2. Loyihani Yuklash

```bash
# Git orqali yuklash
git clone https://github.com/yourusername/balans-ai-bot.git
cd balans-ai-bot

# Yoki loyihani zip fayl sifatida yuklab, ochish
unzip balans-ai-bot.zip
cd balans-ai-bot
```

## 3. Python Sozlamalari

```bash
# Python 3.8+ o'rnatish (agar yo'q bo'lsa)
sudo apt update
sudo apt install python3 python3-pip python3-venv

# Virtual environment yaratish
python3 -m venv venv
source venv/bin/activate

# Kerakli kutubxonalarni o'rnatish
pip install -r requirements.txt
```

## 4. MySQL Ma'lumotlar Bazasi

```bash
# MySQL o'rnatish
sudo apt install mysql-server

# MySQL xavfsizlik sozlamalari
sudo mysql_secure_installation

# Ma'lumotlar bazasini yaratish
sudo mysql -u root -p
```

MySQL ichida:
```sql
CREATE DATABASE balans_ai;
CREATE USER 'balans_user'@'localhost' IDENTIFIED BY 'your_strong_password';
GRANT ALL PRIVILEGES ON balans_ai.* TO 'balans_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

## 5. Environment Sozlamalari

```bash
# .env faylini yaratish
cp .env.example .env
nano .env
```

`.env` faylini to'ldiring:
```
BOT_TOKEN=your_telegram_bot_token
OPENAI_API_KEY=your_openai_api_key
DB_HOST=localhost
DB_NAME=balans_ai
DB_USER=balans_user
DB_PASSWORD=your_strong_password
DB_PORT=3306
```

## 6. Botni Test Qilish

```bash
# Botni test qilish
python3 run_bot.py
```

Agar hammasi to'g'ri ishlasa, Ctrl+C bilan to'xtating.

## 7. Supervisor Sozlamalari

```bash
# Supervisor o'rnatish
sudo apt install supervisor

# Bot uchun konfiguratsiya fayli yaratish
sudo nano /etc/supervisor/conf.d/balans-ai-bot.conf
```

`balans-ai-bot.conf` faylini to'ldiring:
```ini
[program:balans-ai-bot]
command=/path/to/your/project/venv/bin/python /path/to/your/project/run_bot.py
directory=/path/to/your/project
user=www-data
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/balans-ai-bot.log
environment=PATH="/path/to/your/project/venv/bin"
```

```bash
# Supervisor ni qayta ishga tushirish
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start balans-ai-bot

# Status tekshirish
sudo supervisorctl status balans-ai-bot
```

## 8. Loglarni Ko'rish

```bash
# Bot loglari
sudo tail -f /var/log/balans-ai-bot.log

# Supervisor loglari
sudo tail -f /var/log/supervisor/supervisord.log
```

## 9. Xavfsizlik

```bash
# Firewall sozlamalari
sudo ufw allow 22
sudo ufw allow 80
sudo ufw allow 443
sudo ufw enable

# MySQL xavfsizlik
sudo mysql -u root -p
```

MySQL ichida:
```sql
DELETE FROM mysql.user WHERE User='';
DELETE FROM mysql.user WHERE User='root' AND Host NOT IN ('localhost', '127.0.0.1', '::1');
DROP DATABASE IF EXISTS test;
DELETE FROM mysql.db WHERE Db='test' OR Db='test\\_%';
FLUSH PRIVILEGES;
```

## 10. Monitoring

```bash
# Bot holatini tekshirish
sudo supervisorctl status balans-ai-bot

# Botni qayta ishga tushirish
sudo supervisorctl restart balans-ai-bot

# Botni to'xtatish
sudo supervisorctl stop balans-ai-bot
```

## 11. Yangilanish

```bash
# Yangi kodni yuklash
cd /path/to/your/project
git pull origin main

# Kerakli kutubxonalarni yangilash
source venv/bin/activate
pip install -r requirements.txt

# Botni qayta ishga tushirish
sudo supervisorctl restart balans-ai-bot
```

## 12. Backup

```bash
# Ma'lumotlar bazasini backup qilish
mysqldump -u balans_user -p balans_ai > backup_$(date +%Y%m%d_%H%M%S).sql

# Loyiha fayllarini backup qilish
tar -czf balans-ai-backup_$(date +%Y%m%d_%H%M%S).tar.gz /path/to/your/project
```

## 13. Muammolarni Hal Qilish

### Bot ishlamayapti:
```bash
# Loglarni tekshirish
sudo tail -f /var/log/balans-ai-bot.log

# Supervisor status
sudo supervisorctl status balans-ai-bot

# Botni qayta ishga tushirish
sudo supervisorctl restart balans-ai-bot
```

### Ma'lumotlar bazasi ulanishi:
```bash
# MySQL holatini tekshirish
sudo systemctl status mysql

# MySQL ni qayta ishga tushirish
sudo systemctl restart mysql
```

### Port band:
```bash
# Portlarni tekshirish
sudo netstat -tlnp | grep :3306
sudo netstat -tlnp | grep :8000
```

## 14. Foydalanish

Bot ishga tushgandan so'ng:
1. Telegram'da botni toping
2. `/start` komandasi bilan ishga tushiring
3. Moliyaviy ma'lumotlaringizni kiritishni boshlang

## 15. Qo'shimcha Ma'lumotlar

- **Bot token**: @BotFather dan oling
- **OpenAI API key**: platform.openai.com dan oling
- **MySQL**: Ma'lumotlar bazasi boshqaruvi
- **Supervisor**: Bot jarayonini boshqarish
- **Logs**: Xatoliklarni kuzatish

## 16. Yordam

Agar muammo bo'lsa:
1. Loglarni tekshiring
2. Ma'lumotlar bazasi ulanishini tekshiring
3. Environment o'zgaruvchilarini tekshiring
4. Bot token va API keylarni tekshiring