# BALANS AI — BIZNES TARIFI MINI ILOVA TEXNIK TOPSHIRIQ (TZ)

## 1. UMUMIY MA'LUMOT

### 1.1. Maqsad
Biznes tarifi foydalanuvchilari uchun Telegram Mini App orqali biznesni boshqarish: ombor, hisobotlar, xodimlar va AI chat.

### 1.2. Texnologiyalar
- **Backend**: Python Flask (to'g'ridan-to'g'ri MySQL bilan ishlaydi)
- **Frontend**: HTML + Tailwind CSS + JavaScript
- **Ma'lumotlar bazasi**: MySQL (bot bilan bir xil database)
- **Integratsiya**: Telegram Mini App API

**MUHIM**: Flask server to'g'ridan-to'g'ri MySQL ga ulanadi. Bot `main.py` bilan bir xil database bilan ishlaydi.

---

## 2. DATABASE STRUKTURA (BIZNES TARIFI UCHUN)

### 2.1. Transactions jadvali (biznes uchun ham)
```sql
transactions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT,
    transaction_type ENUM('income', 'expense', 'debt') NOT NULL,
    amount DECIMAL(15,2) NOT NULL,
    currency VARCHAR(10) DEFAULT 'UZS',
    category VARCHAR(100),
    description TEXT,
    created_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
)
```

### 2.2. Warehouse_products jadvali (OMBOR)
```sql
warehouse_products (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(100),
    barcode VARCHAR(100),
    price DECIMAL(15,2) DEFAULT 0,
    quantity INT DEFAULT 0,
    min_quantity INT DEFAULT 0,
    unit VARCHAR(50) DEFAULT 'dona',  -- dona, kg, litr, qop, va h.k.
    image_url VARCHAR(500),
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
)
```

### 2.3. Warehouse_movements jadvali (OMBOR HARAKATLARI)
```sql
warehouse_movements (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    product_id INT NOT NULL,
    movement_type ENUM('in', 'out') NOT NULL,
    quantity INT NOT NULL,
    price DECIMAL(15,2) DEFAULT 0,
    reason VARCHAR(100) DEFAULT 'other',  -- purchase, sale, loss, defect, other
    created_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (product_id) REFERENCES warehouse_products(id)
)
```

### 2.4. Business_employees jadvali (XODIMLAR)
```sql
business_employees (
    id INT PRIMARY KEY AUTO_INCREMENT,
    owner_id BIGINT NOT NULL,
    telegram_id BIGINT NOT NULL,
    name VARCHAR(255) NOT NULL,
    role ENUM('employee', 'manager') DEFAULT 'employee',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    FOREIGN KEY (owner_id) REFERENCES users(user_id)
)
```

### 2.5. Business_tasks jadvali (VAZIFALAR)
```sql
business_tasks (
    id INT PRIMARY KEY AUTO_INCREMENT,
    owner_id BIGINT NOT NULL,
    employee_id INT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    due_date DATETIME,
    status ENUM('pending', 'in_progress', 'completed', 'cancelled') DEFAULT 'pending',
    created_at TIMESTAMP,
    completed_at TIMESTAMP NULL,
    FOREIGN KEY (owner_id) REFERENCES users(user_id),
    FOREIGN KEY (employee_id) REFERENCES business_employees(id)
)
```

### 2.6. Debts jadvali (BIZNES QARZLARI)
```sql
debts (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    debt_type ENUM('lent', 'borrowed') NOT NULL,
    amount DECIMAL(15,2) NOT NULL,
    paid_amount DECIMAL(15,2) DEFAULT 0,
    person_name VARCHAR(255),
    due_date DATE NULL,
    status ENUM('active', 'paid') DEFAULT 'active',
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
)
```

---

## 3. FLASK SERVER (BACKEND)

### 3.1. Paketlar

```bash
pip install flask flask-cors pymysql python-dotenv
```

### 3.2. Flask App Struktura

```
business_mini_app/
├── app.py              # Flask server
├── database.py         # Database connection (bot bilan bir xil config)
├── telegram_auth.py    # Telegram initData validatsiya
├── templates/          # HTML shablonlar
│   ├── index.html      # Asosiy sahifa
│   ├── warehouse.html  # Ombor sahifasi
│   ├── reports.html    # Hisobotlar sahifasi
│   ├── employees.html  # Xodimlar sahifasi
│   └── ai_chat.html    # AI Chat sahifasi
├── static/
│   ├── css/
│   └── js/
│       ├── app.js      # Asosiy JavaScript
│       ├── warehouse.js
│       ├── reports.js
│       └── employees.js
└── requirements.txt
```

### 3.3. Database Connection

```python
# database.py
import pymysql
from config import MYSQL_CONFIG
import logging

class FlaskDatabase:
    def __init__(self):
        self.connection = None
    
    def get_connection(self):
        """Database connection olish"""
        if not self.connection or not self.connection.open:
            try:
                self.connection = pymysql.connect(
                    host=MYSQL_CONFIG['host'],
                    port=MYSQL_CONFIG.get('port', 3306),
                    user=MYSQL_CONFIG['user'],
                    password=MYSQL_CONFIG['password'],
                    database=MYSQL_CONFIG['database'],
                    cursorclass=pymysql.cursors.DictCursor,
                    autocommit=True
                )
            except Exception as e:
                logging.error(f"Database connection error: {e}")
                raise
        return self.connection
    
    def execute_query(self, query, params=None):
        """SQL so'rovni bajarish - dict qaytaradi"""
        conn = self.get_connection()
        with conn.cursor() as cursor:
            cursor.execute(query, params or ())
            return cursor.fetchall()
    
    def execute_one(self, query, params=None):
        """Bitta natija qaytaruvchi SQL so'rov"""
        conn = self.get_connection()
        with conn.cursor() as cursor:
            cursor.execute(query, params or ())
            return cursor.fetchone()
    
    def execute_insert(self, query, params=None):
        """Ma'lumot kiritish"""
        conn = self.get_connection()
        with conn.cursor() as cursor:
            cursor.execute(query, params or ())
            conn.commit()
            return cursor.lastrowid

db = FlaskDatabase()
```

### 3.4. Flask Routes (app.py)

```python
# app.py
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from database import db
from telegram_auth import verify_telegram_webapp_data
import logging

app = Flask(__name__)
CORS(app)

def get_user_id_from_request():
    """Request dan user_id ni olish"""
    init_data = request.headers.get('X-Telegram-Init-Data')
    if not init_data:
        return None
    
    user_data = verify_telegram_webapp_data(init_data)
    if not user_data:
        return None
    
    return user_data.get('id')


@app.route('/')
def index():
    """Asosiy sahifa - biznes menyu"""
    return render_template('index.html')


# ============ HISOBOTLAR ============

@app.route('/api/reports/daily', methods=['GET'])
def get_daily_report():
    """Kunlik hisobot"""
    try:
        user_id = get_user_id_from_request()
        if not user_id:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        
        date = request.args.get('date')  # YYYY-MM-DD
        
        # Tranzaksiyalar
        transactions = db.execute_query(
            """
            SELECT transaction_type, SUM(amount) as total, COUNT(*) as count
            FROM transactions
            WHERE user_id = %s AND DATE(created_at) = %s
            GROUP BY transaction_type
            """,
            (user_id, date)
        )
        
        # Qarzlar
        debts = db.execute_query(
            """
            SELECT debt_type, SUM(amount - paid_amount) as remaining
            FROM debts
            WHERE user_id = %s AND status = 'active'
            GROUP BY debt_type
            """,
            (user_id,)
        )
        
        # Ombor qiymati
        warehouse_value = db.execute_one(
            """
            SELECT COALESCE(SUM(price * quantity), 0) as total_value
            FROM warehouse_products
            WHERE user_id = %s
            """,
            (user_id,)
        )
        
        result = {
            "date": date,
            "income": 0.0,
            "expense": 0.0,
            "debt_lent": 0.0,
            "debt_borrowed": 0.0,
            "warehouse_value": float(warehouse_value['total_value']) if warehouse_value else 0.0,
            "transactions_count": 0
        }
        
        for tx in transactions:
            if tx['transaction_type'] == 'income':
                result['income'] = float(tx['total'])
            elif tx['transaction_type'] == 'expense':
                result['expense'] = float(tx['total'])
            result['transactions_count'] += tx['count']
        
        for debt in debts:
            if debt['debt_type'] == 'lent':
                result['debt_lent'] = float(debt['remaining'])
            elif debt['debt_type'] == 'borrowed':
                result['debt_borrowed'] = float(debt['remaining'])
        
        result['net_profit'] = result['income'] - result['expense']
        
        return jsonify({"success": True, "data": result})
        
    except Exception as e:
        logging.error(f"Error getting daily report: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/reports/monthly', methods=['GET'])
def get_monthly_report():
    """Oylik hisobot"""
    try:
        user_id = get_user_id_from_request()
        if not user_id:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        
        year = int(request.args.get('year', datetime.now().year))
        month = int(request.args.get('month', datetime.now().month))
        
        # Tranzaksiyalar
        transactions = db.execute_query(
            """
            SELECT transaction_type, SUM(amount) as total
            FROM transactions
            WHERE user_id = %s AND YEAR(created_at) = %s AND MONTH(created_at) = %s
            GROUP BY transaction_type
            """,
            (user_id, year, month)
        )
        
        # Kategoriyalar bo'yicha
        categories = db.execute_query(
            """
            SELECT category, transaction_type, SUM(amount) as total
            FROM transactions
            WHERE user_id = %s AND YEAR(created_at) = %s AND MONTH(created_at) = %s
            GROUP BY category, transaction_type
            """,
            (user_id, year, month)
        )
        
        result = {
            "year": year,
            "month": month,
            "income": 0.0,
            "expense": 0.0,
            "categories": {}
        }
        
        for tx in transactions:
            if tx['transaction_type'] == 'income':
                result['income'] = float(tx['total'])
            elif tx['transaction_type'] == 'expense':
                result['expense'] = float(tx['total'])
        
        for cat in categories:
            cat_name = cat['category']
            if cat_name not in result['categories']:
                result['categories'][cat_name] = {'income': 0.0, 'expense': 0.0}
            
            if cat['transaction_type'] == 'income':
                result['categories'][cat_name]['income'] = float(cat['total'])
            else:
                result['categories'][cat_name]['expense'] = float(cat['total'])
        
        result['net_profit'] = result['income'] - result['expense']
        
        return jsonify({"success": True, "data": result})
        
    except Exception as e:
        logging.error(f"Error getting monthly report: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============ OMBOR ============

@app.route('/api/warehouse/products', methods=['GET'])
def get_warehouse_products():
    """Ombor tovarlarini olish"""
    try:
        user_id = get_user_id_from_request()
        if not user_id:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        
        category = request.args.get('category')  # optional filter
        
        if category:
            products = db.execute_query(
                """
                SELECT id, name, category, price, quantity, min_quantity, unit, image_url, created_at
                FROM warehouse_products
                WHERE user_id = %s AND category = %s
                ORDER BY name
                """,
                (user_id, category)
            )
        else:
            products = db.execute_query(
                """
                SELECT id, name, category, price, quantity, min_quantity, unit, image_url, created_at
                FROM warehouse_products
                WHERE user_id = %s
                ORDER BY name
                """,
                (user_id,)
            )
        
        formatted_products = []
        for p in products:
            formatted_products.append({
                "id": p['id'],
                "name": p['name'],
                "category": p.get('category'),
                "price": float(p['price'] or 0),
                "quantity": p['quantity'] or 0,
                "min_quantity": p.get('min_quantity') or 0,
                "unit": p.get('unit', 'dona'),
                "image_url": p.get('image_url'),
                "is_low_stock": (p['quantity'] or 0) < (p.get('min_quantity') or 0),
                "created_at": str(p['created_at']) if p.get('created_at') else None
            })
        
        return jsonify({"success": True, "data": formatted_products})
        
    except Exception as e:
        logging.error(f"Error getting warehouse products: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/warehouse/products', methods=['POST'])
def add_warehouse_product():
    """Yangi tovar qo'shish"""
    try:
        user_id = get_user_id_from_request()
        if not user_id:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        
        data = request.json
        name = data.get('name')
        category = data.get('category')
        price = float(data.get('price', 0))
        quantity = int(data.get('quantity', 0))
        min_quantity = int(data.get('min_quantity', 0))
        unit = data.get('unit', 'dona')
        
        product_id = db.execute_insert(
            """
            INSERT INTO warehouse_products 
            (user_id, name, category, price, quantity, min_quantity, unit)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (user_id, name, category, price, quantity, min_quantity, unit)
        )
        
        return jsonify({
            "success": True,
            "id": product_id,
            "message": "Tovar qo'shildi"
        })
        
    except Exception as e:
        logging.error(f"Error adding warehouse product: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/warehouse/movements', methods=['POST'])
def add_warehouse_movement():
    """Ombor harakati qo'shish (kirim/chiqim)"""
    try:
        user_id = get_user_id_from_request()
        if not user_id:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        
        data = request.json
        product_id = int(data.get('product_id'))
        movement_type = data.get('type')  # 'in' yoki 'out'
        quantity = int(data.get('quantity', 0))
        price = float(data.get('price', 0))
        reason = data.get('reason', 'other')
        
        # Harakatni saqlash
        movement_id = db.execute_insert(
            """
            INSERT INTO warehouse_movements 
            (user_id, product_id, movement_type, quantity, price, reason)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (user_id, product_id, movement_type, quantity, price, reason)
        )
        
        # Tovar miqdorini yangilash
        if movement_type == 'in':
            db.execute_query(
                "UPDATE warehouse_products SET quantity = quantity + %s WHERE id = %s AND user_id = %s",
                (quantity, product_id, user_id)
            )
        else:  # out
            db.execute_query(
                "UPDATE warehouse_products SET quantity = quantity - %s WHERE id = %s AND user_id = %s",
                (quantity, product_id, user_id)
            )
        
        return jsonify({
            "success": True,
            "id": movement_id,
            "message": f"{'Kirim' if movement_type == 'in' else 'Chiqim'} qo'shildi"
        })
        
    except Exception as e:
        logging.error(f"Error adding warehouse movement: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/warehouse/low-stock', methods=['GET'])
def get_low_stock_products():
    """Kam qolgan tovarlar"""
    try:
        user_id = get_user_id_from_request()
        if not user_id:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        
        products = db.execute_query(
            """
            SELECT id, name, category, price, quantity, min_quantity, unit
            FROM warehouse_products
            WHERE user_id = %s AND quantity <= min_quantity
            ORDER BY (quantity - min_quantity) ASC
            """,
            (user_id,)
        )
        
        formatted_products = []
        for p in products:
            formatted_products.append({
                "id": p['id'],
                "name": p['name'],
                "category": p.get('category'),
                "quantity": p['quantity'] or 0,
                "min_quantity": p.get('min_quantity') or 0,
                "unit": p.get('unit', 'dona'),
                "deficit": (p.get('min_quantity') or 0) - (p['quantity'] or 0)
            })
        
        return jsonify({"success": True, "data": formatted_products})
        
    except Exception as e:
        logging.error(f"Error getting low stock products: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============ XODIMLAR ============

@app.route('/api/employees', methods=['GET'])
def get_employees():
    """Xodimlar ro'yxatini olish"""
    try:
        user_id = get_user_id_from_request()
        if not user_id:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        
        employees = db.execute_query(
            """
            SELECT id, telegram_id, name, role, is_active, created_at
            FROM business_employees
            WHERE owner_id = %s
            ORDER BY created_at DESC
            """,
            (user_id,)
        )
        
        formatted_employees = []
        for emp in employees:
            formatted_employees.append({
                "id": emp['id'],
                "telegram_id": emp['telegram_id'],
                "name": emp['name'],
                "role": emp['role'],
                "is_active": bool(emp['is_active']),
                "created_at": str(emp['created_at']) if emp.get('created_at') else None
            })
        
        return jsonify({"success": True, "data": formatted_employees})
        
    except Exception as e:
        logging.error(f"Error getting employees: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/employees', methods=['POST'])
def add_employee():
    """Yangi xodim qo'shish"""
    try:
        user_id = get_user_id_from_request()
        if not user_id:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        
        data = request.json
        telegram_id = int(data.get('telegram_id'))
        name = data.get('name')
        role = data.get('role', 'employee')  # 'employee' yoki 'manager'
        
        employee_id = db.execute_insert(
            """
            INSERT INTO business_employees (owner_id, telegram_id, name, role)
            VALUES (%s, %s, %s, %s)
            """,
            (user_id, telegram_id, name, role)
        )
        
        return jsonify({
            "success": True,
            "id": employee_id,
            "message": "Xodim qo'shildi"
        })
        
    except Exception as e:
        logging.error(f"Error adding employee: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============ VAZIFALAR ============

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    """Vazifalar ro'yxatini olish"""
    try:
        user_id = get_user_id_from_request()
        if not user_id:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        
        employee_id = request.args.get('employee_id')  # optional filter
        
        if employee_id:
            tasks = db.execute_query(
                """
                SELECT t.id, t.title, t.description, t.due_date, t.status, 
                       t.created_at, t.completed_at, e.name as employee_name
                FROM business_tasks t
                LEFT JOIN business_employees e ON t.employee_id = e.id
                WHERE t.owner_id = %s AND t.employee_id = %s
                ORDER BY t.created_at DESC
                """,
                (user_id, employee_id)
            )
        else:
            tasks = db.execute_query(
                """
                SELECT t.id, t.title, t.description, t.due_date, t.status, 
                       t.created_at, t.completed_at, e.name as employee_name
                FROM business_tasks t
                LEFT JOIN business_employees e ON t.employee_id = e.id
                WHERE t.owner_id = %s
                ORDER BY t.created_at DESC
                """,
                (user_id,)
            )
        
        formatted_tasks = []
        for task in tasks:
            formatted_tasks.append({
                "id": task['id'],
                "title": task['title'],
                "description": task.get('description'),
                "due_date": str(task['due_date']) if task.get('due_date') else None,
                "status": task['status'],
                "employee_name": task.get('employee_name'),
                "created_at": str(task['created_at']) if task.get('created_at') else None,
                "completed_at": str(task['completed_at']) if task.get('completed_at') else None
            })
        
        return jsonify({"success": True, "data": formatted_tasks})
        
    except Exception as e:
        logging.error(f"Error getting tasks: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/tasks', methods=['POST'])
def add_task():
    """Yangi vazifa qo'shish"""
    try:
        user_id = get_user_id_from_request()
        if not user_id:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        
        data = request.json
        title = data.get('title')
        description = data.get('description')
        employee_id = data.get('employee_id')  # optional
        due_date = data.get('due_date')  # YYYY-MM-DD HH:MM:SS
        
        task_id = db.execute_insert(
            """
            INSERT INTO business_tasks (owner_id, employee_id, title, description, due_date)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, employee_id, title, description, due_date)
        )
        
        return jsonify({
            "success": True,
            "id": task_id,
            "message": "Vazifa qo'shildi"
        })
        
    except Exception as e:
        logging.error(f"Error adding task: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============ TRANZAKSIYALAR ============

@app.route('/api/transactions', methods=['GET'])
def get_transactions():
    """Biznes tranzaksiyalarini olish"""
    try:
        user_id = get_user_id_from_request()
        if not user_id:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 50))
        offset = (page - 1) * limit
        transaction_type = request.args.get('type')  # income, expense, debt
        
        query = """
            SELECT id, transaction_type, amount, currency, category, description, created_at
            FROM transactions
            WHERE user_id = %s
        """
        params = [user_id]
        
        if transaction_type:
            query += " AND transaction_type = %s"
            params.append(transaction_type)
        
        query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        
        transactions = db.execute_query(query, tuple(params))
        
        formatted_transactions = []
        for tx in transactions:
            formatted_transactions.append({
                "id": tx['id'],
                "type": tx['transaction_type'],
                "amount": float(tx['amount']),
                "currency": tx.get('currency', 'UZS'),
                "category": tx.get('category'),
                "description": tx.get('description'),
                "created_at": str(tx['created_at']) if tx.get('created_at') else None
            })
        
        return jsonify({
            "success": True,
            "data": formatted_transactions,
            "page": page,
            "limit": limit
        })
        
    except Exception as e:
        logging.error(f"Error getting transactions: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)  # Port 5001 (5000 dan farq)
```

---

## 4. FRONTEND (HTML + TAILWIND CSS + JAVASCRIPT)

### 4.1. Asosiy Sahifa (templates/index.html)

```html
<!DOCTYPE html>
<html lang="uz">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📊 BALANS AI - Biznes</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-50 min-h-screen">
    <div id="app" class="max-w-md mx-auto bg-white min-h-screen">
        <!-- Header -->
        <header class="bg-gradient-to-r from-blue-600 to-purple-600 text-white p-4 sticky top-0 z-10">
            <h1 class="text-xl font-bold">📊 BALANS AI - Biznes</h1>
        </header>
        
        <!-- Navigation Menu -->
        <nav class="bg-white border-b border-gray-200 p-2">
            <div class="flex space-x-2">
                <button onclick="showReports()" class="flex-1 bg-blue-500 text-white px-4 py-2 rounded-lg font-semibold">
                    📊 Hisobotlar
                </button>
                <button onclick="showWarehouse()" class="flex-1 bg-green-500 text-white px-4 py-2 rounded-lg font-semibold">
                    📦 Ombor
                </button>
                <button onclick="showEmployees()" class="flex-1 bg-purple-500 text-white px-4 py-2 rounded-lg font-semibold">
                    👥 Xodimlar
                </button>
                <button onclick="showAIChat()" class="flex-1 bg-orange-500 text-white px-4 py-2 rounded-lg font-semibold">
                    🤖 AI Chat
                </button>
            </div>
        </nav>
        
        <!-- Content Area -->
        <main class="p-4" id="main-content">
            <!-- Default: Reports view -->
            <div id="reports-view">
                <h2 class="text-2xl font-bold mb-4">📊 Hisobotlar</h2>
                <div id="reports-content"></div>
            </div>
            
            <!-- Warehouse view (hidden by default) -->
            <div id="warehouse-view" class="hidden">
                <h2 class="text-2xl font-bold mb-4">📦 Ombor</h2>
                <div id="warehouse-content"></div>
            </div>
            
            <!-- Employees view (hidden by default) -->
            <div id="employees-view" class="hidden">
                <h2 class="text-2xl font-bold mb-4">👥 Xodimlar</h2>
                <div id="employees-content"></div>
            </div>
            
            <!-- AI Chat view (hidden by default) -->
            <div id="ai-chat-view" class="hidden">
                <h2 class="text-2xl font-bold mb-4">🤖 AI Chat</h2>
                <div id="ai-chat-content"></div>
            </div>
        </main>
    </div>
    
    <script src="{{ url_for('static', filename='js/app.js') }}"></script>
</body>
</html>
```

### 4.2. JavaScript (static/js/app.js)

```javascript
// Telegram WebApp
const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

// API Request
async function apiRequest(endpoint, options = {}) {
    const initData = tg.initData;
    
    const response = await fetch(endpoint, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            'X-Telegram-Init-Data': initData,
            ...options.headers
        }
    });
    
    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'API xatolik');
    }
    
    return response.json();
}

// Navigation functions
function showReports() {
    document.getElementById('reports-view').classList.remove('hidden');
    document.getElementById('warehouse-view').classList.add('hidden');
    document.getElementById('employees-view').classList.add('hidden');
    document.getElementById('ai-chat-view').classList.add('hidden');
    loadDailyReport();
}

function showWarehouse() {
    document.getElementById('reports-view').classList.add('hidden');
    document.getElementById('warehouse-view').classList.remove('hidden');
    document.getElementById('employees-view').classList.add('hidden');
    document.getElementById('ai-chat-view').classList.add('hidden');
    loadWarehouseProducts();
}

function showEmployees() {
    document.getElementById('reports-view').classList.add('hidden');
    document.getElementById('warehouse-view').classList.add('hidden');
    document.getElementById('employees-view').classList.remove('hidden');
    document.getElementById('ai-chat-view').classList.add('hidden');
    loadEmployees();
}

function showAIChat() {
    document.getElementById('reports-view').classList.add('hidden');
    document.getElementById('warehouse-view').classList.add('hidden');
    document.getElementById('employees-view').classList.add('hidden');
    document.getElementById('ai-chat-view').classList.remove('hidden');
}

// Reports
async function loadDailyReport() {
    try {
        const today = new Date().toISOString().split('T')[0];
        const result = await apiRequest(`/api/reports/daily?date=${today}`);
        const data = result.data;
        
        const content = document.getElementById('reports-content');
        content.innerHTML = `
            <div class="bg-gradient-to-r from-blue-500 to-blue-600 rounded-lg p-6 text-white mb-4">
                <h3 class="text-lg font-semibold mb-4">Bugun (${today})</h3>
                <div class="space-y-2">
                    <div class="flex justify-between">
                        <span>📈 Kirim:</span>
                        <span class="font-bold">${formatNumber(data.income)} so'm</span>
                    </div>
                    <div class="flex justify-between">
                        <span>📉 Chiqim:</span>
                        <span class="font-bold">${formatNumber(data.expense)} so'm</span>
                    </div>
                    <div class="flex justify-between border-t pt-2">
                        <span>💰 Sof foyda:</span>
                        <span class="font-bold text-xl">${formatNumber(data.net_profit)} so'm</span>
                    </div>
                </div>
            </div>
            
            <div class="bg-white rounded-lg shadow p-4 mb-4">
                <h3 class="font-semibold mb-2">📦 Ombor qiymati</h3>
                <p class="text-2xl font-bold text-green-600">${formatNumber(data.warehouse_value)} so'm</p>
            </div>
            
            <div class="bg-white rounded-lg shadow p-4">
                <h3 class="font-semibold mb-2">💳 Qarzlar</h3>
                <div class="space-y-2">
                    <div class="flex justify-between">
                        <span>Berilgan:</span>
                        <span>${formatNumber(data.debt_lent)} so'm</span>
                    </div>
                    <div class="flex justify-between">
                        <span>Olingan:</span>
                        <span>${formatNumber(data.debt_borrowed)} so'm</span>
                    </div>
                </div>
            </div>
        `;
    } catch (error) {
        console.error('Report yuklashda xatolik:', error);
    }
}

// Warehouse
async function loadWarehouseProducts() {
    try {
        const result = await apiRequest('/api/warehouse/products');
        const products = result.data;
        
        const content = document.getElementById('warehouse-content');
        
        if (products.length === 0) {
            content.innerHTML = '<p class="text-gray-500 text-center py-8">Ombor bo\'sh</p>';
            return;
        }
        
        content.innerHTML = products.map(product => `
            <div class="bg-white rounded-lg shadow p-4 mb-3 border-l-4 ${product.is_low_stock ? 'border-red-500' : 'border-green-500'}">
                <div class="flex justify-between items-start">
                    <div>
                        <h3 class="font-semibold">${product.name}</h3>
                        <p class="text-sm text-gray-600">${product.category || 'Kategoriya yo\'q'}</p>
                        <p class="text-sm text-gray-500 mt-1">
                            Qoldiq: <span class="font-semibold">${product.quantity} ${product.unit}</span>
                            ${product.is_low_stock ? '<span class="text-red-600">⚠️ Kam qoldi!</span>' : ''}
                        </p>
                    </div>
                    <div class="text-right">
                        <p class="font-semibold">${formatNumber(product.price)} so'm</p>
                        <p class="text-sm text-gray-500">${formatNumber(product.price * product.quantity)} so'm (jami)</p>
                    </div>
                </div>
            </div>
        `).join('');
    } catch (error) {
        console.error('Warehouse yuklashda xatolik:', error);
    }
}

// Employees
async function loadEmployees() {
    try {
        const result = await apiRequest('/api/employees');
        const employees = result.data;
        
        const content = document.getElementById('employees-content');
        
        if (employees.length === 0) {
            content.innerHTML = '<p class="text-gray-500 text-center py-8">Xodimlar yo\'q</p>';
            return;
        }
        
        content.innerHTML = employees.map(emp => `
            <div class="bg-white rounded-lg shadow p-4 mb-3">
                <div class="flex justify-between items-center">
                    <div>
                        <h3 class="font-semibold">${emp.name}</h3>
                        <p class="text-sm text-gray-600">${emp.role === 'manager' ? '👔 Menejer' : '👤 Xodim'}</p>
                    </div>
                    <span class="px-3 py-1 rounded-full ${emp.is_active ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'}">
                        ${emp.is_active ? 'Faol' : 'Nofaol'}
                    </span>
                </div>
            </div>
        `).join('');
    } catch (error) {
        console.error('Employees yuklashda xatolik:', error);
    }
}

// Helper function
function formatNumber(num) {
    return new Intl.NumberFormat('uz-UZ').format(Math.round(num));
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    showReports();
});
```

---

## 5. DEPLOYMENT

### 5.1. Serverga Joylash

Flask server alohida portda ishlaydi (masalan, 5001 - shaxsiy mini app 5000 da).

```bash
# Flask server
cd /path/to/business_mini_app
source venv/bin/activate
gunicorn app:app --bind 0.0.0.0:5001 --workers 2
```

### 5.2. Telegram Mini App Sozlash

1. Bot Settings → Mini Apps → Add Mini App
2. Domain: `your-domain.com`
3. Mini App URL: `https://your-domain.com:5001/` yoki `https://business.your-domain.com/`

---

## 6. MUHIM ESLATMALAR

### 6.1. Xavfsizlik

1. **Telegram Init Data Validatsiya**: Har bir so'rovda validatsiya qilish
2. **User ID tekshirish**: Foydalanuvchi faqat o'z ma'lumotlariga kirish huquqiga ega
3. **HTTPS**: Production da HTTPS ishlatish (Telegram Mini App talab qiladi)
4. **SQL Injection**: Parametrli so'rovlar ishlatish

### 6.2. Ombor Operatsiyalari

- **Kirim**: `quantity` qo'shiladi
- **Chiqim**: `quantity` kamayadi
- **Kam qoldi**: `quantity <= min_quantity` bo'lganda bildirish

### 6.3. Xodimlar

- **Owner**: Faqat biznes egasi (user_id) xodimlarni qo'sha/olib tashlash mumkin
- **Employee**: Xodimlar faqat o'z vazifalarini ko'rishlari mumkin
- **Manager**: Menejerlar qo'shimcha huquqlarga ega

---

**Tayyor!** Bu TZ orqali biznes tarifi uchun to'liq mini app yaratish mumkin.

