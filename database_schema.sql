-- HamyonAI&MaqsadAI Bot ma'lumotlar bazasi jadvallari

-- Foydalanuvchilar jadvali
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNIQUE NOT NULL,
    username VARCHAR(255),
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    tariff ENUM('FREE', 'PRO', 'MAX') DEFAULT 'FREE',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    INDEX idx_user_id (user_id),
    INDEX idx_tariff (tariff)
);

-- Tranzaksiyalar jadvali
CREATE TABLE IF NOT EXISTS transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    amount DECIMAL(15,2) NOT NULL,
    category VARCHAR(255) NOT NULL,
    description TEXT,
    transaction_type ENUM('income', 'expense', 'debt') NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id),
    INDEX idx_transaction_type (transaction_type),
    INDEX idx_created_at (created_at),
    INDEX idx_category (category)
);

-- To-Do vazifalar jadvali
CREATE TABLE IF NOT EXISTS todos (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    title VARCHAR(500) NOT NULL,
    description TEXT,
    due_date DATE,
    is_completed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id),
    INDEX idx_is_completed (is_completed),
    INDEX idx_due_date (due_date)
);

-- Maqsadlar jadvali
CREATE TABLE IF NOT EXISTS goals (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    title VARCHAR(500) NOT NULL,
    description TEXT NOT NULL,
    target_amount DECIMAL(15,2),
    target_date DATE,
    current_progress DECIMAL(5,2) DEFAULT 0.0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id),
    INDEX idx_is_active (is_active),
    INDEX idx_target_date (target_date)
);

-- Kunlik vazifalar jadvali (Maqsad AI uchun)
CREATE TABLE IF NOT EXISTS daily_tasks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    goal_id INT NOT NULL,
    task VARCHAR(1000) NOT NULL,
    is_completed BOOLEAN DEFAULT FALSE,
    due_date DATE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE CASCADE,
    INDEX idx_goal_id (goal_id),
    INDEX idx_is_completed (is_completed),
    INDEX idx_due_date (due_date)
);

-- Maqsad bosqichlari jadvali
CREATE TABLE IF NOT EXISTS goal_milestones (
    id INT AUTO_INCREMENT PRIMARY KEY,
    goal_id INT NOT NULL,
    title VARCHAR(500) NOT NULL,
    description TEXT,
    deadline DATE,
    is_completed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE CASCADE,
    INDEX idx_goal_id (goal_id),
    INDEX idx_is_completed (is_completed),
    INDEX idx_deadline (deadline)
);

-- Bot sozlamalari jadvali
CREATE TABLE IF NOT EXISTS user_settings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNIQUE NOT NULL,
    language VARCHAR(10) DEFAULT 'uz',
    notifications_enabled BOOLEAN DEFAULT TRUE,
    reminder_time TIME DEFAULT '09:00:00',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id)
);

-- Eslatmalar jadvali
CREATE TABLE IF NOT EXISTS reminders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    reminder_type ENUM('todo', 'goal', 'financial') NOT NULL,
    title VARCHAR(500) NOT NULL,
    message TEXT,
    reminder_time DATETIME NOT NULL,
    is_sent BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id),
    INDEX idx_reminder_time (reminder_time),
    INDEX idx_is_sent (is_sent)
);

-- AI suhbatlar jadvali (Maqsad AI uchun)
CREATE TABLE IF NOT EXISTS ai_conversations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    goal_id INT,
    message_type ENUM('user', 'ai') NOT NULL,
    message TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id),
    INDEX idx_goal_id (goal_id),
    INDEX idx_created_at (created_at)
);

-- Statistika jadvali
CREATE TABLE IF NOT EXISTS user_statistics (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    stat_date DATE NOT NULL,
    total_income DECIMAL(15,2) DEFAULT 0.0,
    total_expense DECIMAL(15,2) DEFAULT 0.0,
    total_debt DECIMAL(15,2) DEFAULT 0.0,
    completed_todos INT DEFAULT 0,
    completed_goals INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE KEY unique_user_date (user_id, stat_date),
    INDEX idx_user_id (user_id),
    INDEX idx_stat_date (stat_date)
);

-- Maqsad yaratish sessiyalari
CREATE TABLE IF NOT EXISTS goal_creation_sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    initial_goal TEXT NOT NULL,
    current_step INT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id),
    INDEX idx_current_step (current_step)
);

-- Maqsad yaratish javoblari
CREATE TABLE IF NOT EXISTS goal_answers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id INT NOT NULL,
    step INT NOT NULL,
    answer TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES goal_creation_sessions(id) ON DELETE CASCADE,
    INDEX idx_session_id (session_id),
    INDEX idx_step (step)
);
