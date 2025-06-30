import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

# Получаем параметры подключения к PostgreSQL
DATABASE_URL = os.getenv('DATABASE_URL')

def get_connection():
    """Создает подключение к PostgreSQL"""
    if DATABASE_URL:
        # Для Render и других облачных платформ
        return psycopg2.connect(DATABASE_URL)
    else:
        # Для локальной разработки
        return psycopg2.connect(
            host=os.getenv('DB_HOST', 'localhost'),
            database=os.getenv('DB_NAME', 'crypto_bot'),
            user=os.getenv('DB_USER', 'postgres'),
            password=os.getenv('DB_PASSWORD', ''),
            port=os.getenv('DB_PORT', '5432')
        )

def init_db():
    """Инициализирует базу данных PostgreSQL"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Создаем таблицу пользователей
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id     BIGINT PRIMARY KEY,
                    tz          VARCHAR(50) DEFAULT 'UTC',
                    summary_at  VARCHAR(5) DEFAULT '09:00',
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Создаем таблицу уведомлений
            cur.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id          SERIAL PRIMARY KEY,
                    user_id     BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    coin        VARCHAR(20) NOT NULL,
                    target      DECIMAL(20, 8) NOT NULL,
                    above       BOOLEAN DEFAULT TRUE,
                    active      BOOLEAN DEFAULT TRUE,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Создаем таблицу портфолио
            cur.execute("""
                CREATE TABLE IF NOT EXISTS portfolio (
                    id          SERIAL PRIMARY KEY,
                    user_id     BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    coin        VARCHAR(20) NOT NULL,
                    amount      DECIMAL(20, 8) NOT NULL,
                    avg_price   DECIMAL(20, 8) NOT NULL,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, coin)
                )
            """)
            
            # Создаем таблицу транзакций
            cur.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id          SERIAL PRIMARY KEY,
                    user_id     BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    coin        VARCHAR(20) NOT NULL,
                    type        VARCHAR(10) NOT NULL CHECK (type IN ('buy', 'sell')),
                    amount      DECIMAL(20, 8) NOT NULL,
                    price       DECIMAL(20, 8) NOT NULL,
                    total       DECIMAL(20, 8) NOT NULL,
                    date        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Создаем индексы для оптимизации
            cur.execute("CREATE INDEX IF NOT EXISTS idx_alerts_user_id ON alerts(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_alerts_active ON alerts(active)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_portfolio_user_id ON portfolio(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date)")
            
            conn.commit()

def upsert_user(user_id: int, tz: str = None, summary_at: str = None):
    """Добавляет или обновляет пользователя"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Сначала пытаемся вставить нового пользователя
            cur.execute("""
                INSERT INTO users (user_id) 
                VALUES (%s) 
                ON CONFLICT (user_id) DO NOTHING
            """, (user_id,))
            
            # Если нужно обновить поля
            if tz or summary_at:
                update_parts = []
                params = []
                
                if tz:
                    update_parts.append("tz = %s")
                    params.append(tz)
                if summary_at:
                    update_parts.append("summary_at = %s")
                    params.append(summary_at)
                
                if update_parts:
                    params.append(user_id)
                    cur.execute(f"""
                        UPDATE users 
                        SET {', '.join(update_parts)}
                        WHERE user_id = %s
                    """, params)
            
            conn.commit()

def get_user(user_id: int):
    """Получает пользователя по ID"""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            return cur.fetchone()

def all_users():
    """Получает всех пользователей"""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users")
            return cur.fetchall()

# ──────────────── alerts functions ─────────────
def add_alert(user_id: int, coin: str, target: float, above: bool = True) -> int:
    """Добавляет новое уведомление о цене"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO alerts (user_id, coin, target, above) 
                VALUES (%s, %s, %s, %s) 
                RETURNING id
            """, (user_id, coin.lower(), target, above))
            alert_id = cur.fetchone()[0]
            conn.commit()
            return alert_id

def get_user_alerts(user_id: int):
    """Получает все активные уведомления пользователя"""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM alerts 
                WHERE user_id = %s AND active = TRUE 
                ORDER BY created_at DESC
            """, (user_id,))
            return cur.fetchall()

def delete_alert(alert_id: int, user_id: int) -> bool:
    """Удаляет уведомление пользователя"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM alerts 
                WHERE id = %s AND user_id = %s
            """, (alert_id, user_id))
            deleted = cur.rowcount > 0
            conn.commit()
            return deleted

def get_all_active_alerts():
    """Получает все активные уведомления для проверки"""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM alerts WHERE active = TRUE")
            return cur.fetchall()

def deactivate_alert(alert_id: int):
    """Деактивирует уведомление"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE alerts SET active = FALSE WHERE id = %s", (alert_id,))
            conn.commit()

# ──────────────── portfolio functions ─────────────
def add_transaction(user_id: int, coin: str, tx_type: str, amount: float, price: float) -> int:
    """Добавляет транзакцию покупки/продажи"""
    total = amount * price
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Добавляем транзакцию
            cur.execute("""
                INSERT INTO transactions (user_id, coin, type, amount, price, total) 
                VALUES (%s, %s, %s, %s, %s, %s) 
                RETURNING id
            """, (user_id, coin.lower(), tx_type, amount, price, total))
            tx_id = cur.fetchone()[0]
            
            # Обновляем портфолио
            if tx_type == "buy":
                # Проверяем, есть ли уже эта монета в портфолио
                cur.execute("""
                    SELECT * FROM portfolio 
                    WHERE user_id = %s AND coin = %s
                """, (user_id, coin.lower()))
                existing = cur.fetchone()
                
                if existing:
                    # Обновляем существующую позицию
                    new_amount = existing[3] + amount  # existing[3] = amount
                    new_avg_price = ((existing[3] * existing[4]) + total) / new_amount  # existing[4] = avg_price
                    cur.execute("""
                        UPDATE portfolio 
                        SET amount = %s, avg_price = %s 
                        WHERE user_id = %s AND coin = %s
                    """, (new_amount, new_avg_price, user_id, coin.lower()))
                else:
                    # Создаем новую позицию
                    cur.execute("""
                        INSERT INTO portfolio (user_id, coin, amount, avg_price) 
                        VALUES (%s, %s, %s, %s)
                    """, (user_id, coin.lower(), amount, price))
                    
            elif tx_type == "sell":
                # Уменьшаем позицию в портфолио
                cur.execute("""
                    SELECT * FROM portfolio 
                    WHERE user_id = %s AND coin = %s
                """, (user_id, coin.lower()))
                existing = cur.fetchone()
                
                if existing and existing[3] >= amount:  # existing[3] = amount
                    new_amount = existing[3] - amount
                    if new_amount <= 0:
                        # Удаляем позицию если продали все
                        cur.execute("""
                            DELETE FROM portfolio 
                            WHERE user_id = %s AND coin = %s
                        """, (user_id, coin.lower()))
                    else:
                        # Обновляем количество (средняя цена остается той же)
                        cur.execute("""
                            UPDATE portfolio 
                            SET amount = %s 
                            WHERE user_id = %s AND coin = %s
                        """, (new_amount, user_id, coin.lower()))
            
            conn.commit()
            return tx_id

def get_user_portfolio(user_id: int):
    """Получает портфолио пользователя"""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM portfolio 
                WHERE user_id = %s 
                ORDER BY amount DESC
            """, (user_id,))
            return cur.fetchall()

def get_user_transactions(user_id: int, limit: int = 10):
    """Получает последние транзакции пользователя"""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM transactions 
                WHERE user_id = %s 
                ORDER BY date DESC 
                LIMIT %s
            """, (user_id, limit))
            return cur.fetchall()

def get_portfolio_summary(user_id: int, get_current_price_func=None):
    """Получает сводку портфолио с текущими ценами"""
    portfolio = get_user_portfolio(user_id)
    if not portfolio:
        return {
            "total_invested": 0, 
            "total_current": 0, 
            "total_pnl": 0, 
            "total_pnl_percent": 0, 
            "positions": 0,
            "positions_detail": []
        }
    
    total_invested = sum(pos["amount"] * pos["avg_price"] for pos in portfolio)
    total_current = 0
    positions_with_pnl = []
    
    for position in portfolio:
        current_price = position["avg_price"]  # По умолчанию используем среднюю цену
        
        # Если передана функция получения цены, используем её
        if get_current_price_func:
            try:
                current_price = get_current_price_func(position["coin"]) or position["avg_price"]
            except:
                current_price = position["avg_price"]
        
        position_value = position["amount"] * current_price
        position_invested = position["amount"] * position["avg_price"]
        position_pnl = position_value - position_invested
        position_pnl_percent = (position_pnl / position_invested * 100) if position_invested > 0 else 0
        
        total_current += position_value
        
        positions_with_pnl.append({
            **dict(position),
            "current_price": current_price,
            "current_value": position_value,
            "invested_value": position_invested,
            "pnl": position_pnl,
            "pnl_percent": position_pnl_percent
        })
    
    total_pnl = total_current - total_invested
    total_pnl_percent = (total_pnl / total_invested * 100) if total_invested > 0 else 0
    
    return {
        "total_invested": total_invested,
        "total_current": total_current,
        "total_pnl": total_pnl,
        "total_pnl_percent": total_pnl_percent,
        "positions": len(portfolio),
        "positions_detail": positions_with_pnl
    } 