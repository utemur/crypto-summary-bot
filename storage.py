import sqlite3
from pathlib import Path

DB_PATH = Path("bot.db")


def _conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    with _conn() as cx:
        cx.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                tz          TEXT   DEFAULT 'UTC',
                summary_at  TEXT   DEFAULT '09:00'
            )
            """
        )
        cx.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                coin        TEXT,
                target      REAL,
                above       INTEGER DEFAULT 1,
                active      INTEGER DEFAULT 1,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
            """
        )
        cx.execute(
            """
            CREATE TABLE IF NOT EXISTS portfolio (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                coin        TEXT,
                amount      REAL,
                avg_price   REAL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
            """
        )
        cx.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                coin        TEXT,
                type        TEXT,  -- 'buy' or 'sell'
                amount      REAL,
                price       REAL,
                total       REAL,
                date        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
            """
        )


def upsert_user(user_id: int, tz: str | None = None, summary_at: str | None = None):
    with _conn() as cx:
        cx.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        if tz:
            cx.execute("UPDATE users SET tz=? WHERE user_id=?", (tz, user_id))
        if summary_at:
            cx.execute("UPDATE users SET summary_at=? WHERE user_id=?", (summary_at, user_id))


def get_user(user_id: int) -> dict | None:
    cx = _conn()
    cx.row_factory = sqlite3.Row
    row = cx.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def all_users():
    cx = _conn()
    cx.row_factory = sqlite3.Row
    return [dict(r) for r in cx.execute("SELECT * FROM users")]


# ──────────────── alerts functions ─────────────
def add_alert(user_id: int, coin: str, target: float, above: bool = True) -> int:
    """Добавляет новое уведомление о цене"""
    with _conn() as cx:
        cursor = cx.execute(
            "INSERT INTO alerts (user_id, coin, target, above) VALUES (?, ?, ?, ?)",
            (user_id, coin.lower(), target, 1 if above else 0)
        )
        return cursor.lastrowid


def get_user_alerts(user_id: int) -> list[dict]:
    """Получает все активные уведомления пользователя"""
    cx = _conn()
    cx.row_factory = sqlite3.Row
    return [dict(r) for r in cx.execute(
        "SELECT * FROM alerts WHERE user_id=? AND active=1 ORDER BY created_at DESC",
        (user_id,)
    )]


def delete_alert(alert_id: int, user_id: int) -> bool:
    """Удаляет уведомление пользователя"""
    with _conn() as cx:
        cursor = cx.execute(
            "DELETE FROM alerts WHERE id=? AND user_id=?",
            (alert_id, user_id)
        )
        return cursor.rowcount > 0


def get_all_active_alerts() -> list[dict]:
    """Получает все активные уведомления для проверки"""
    cx = _conn()
    cx.row_factory = sqlite3.Row
    return [dict(r) for r in cx.execute(
        "SELECT * FROM alerts WHERE active=1"
    )]


def deactivate_alert(alert_id: int):
    """Деактивирует уведомление (не удаляет, а помечает как неактивное)"""
    with _conn() as cx:
        cx.execute("UPDATE alerts SET active=0 WHERE id=?", (alert_id,))


# ──────────────── portfolio functions ─────────────
def add_transaction(user_id: int, coin: str, tx_type: str, amount: float, price: float) -> int:
    """Добавляет транзакцию покупки/продажи"""
    total = amount * price
    
    with _conn() as cx:
        # Добавляем транзакцию
        cursor = cx.execute(
            "INSERT INTO transactions (user_id, coin, type, amount, price, total) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, coin.lower(), tx_type, amount, price, total)
        )
        tx_id = cursor.lastrowid
        
        # Обновляем портфолио
        if tx_type == "buy":
            # Проверяем, есть ли уже эта монета в портфолио
            cx.row_factory = sqlite3.Row
            existing = cx.execute(
                "SELECT * FROM portfolio WHERE user_id=? AND coin=?",
                (user_id, coin.lower())
            ).fetchone()
            
            if existing:
                # Обновляем существующую позицию
                new_amount = existing["amount"] + amount
                new_avg_price = ((existing["amount"] * existing["avg_price"]) + total) / new_amount
                cx.execute(
                    "UPDATE portfolio SET amount=?, avg_price=? WHERE user_id=? AND coin=?",
                    (new_amount, new_avg_price, user_id, coin.lower())
                )
            else:
                # Создаем новую позицию
                cx.execute(
                    "INSERT INTO portfolio (user_id, coin, amount, avg_price) VALUES (?, ?, ?, ?)",
                    (user_id, coin.lower(), amount, price)
                )
        elif tx_type == "sell":
            # Уменьшаем позицию в портфолио
            cx.row_factory = sqlite3.Row
            existing = cx.execute(
                "SELECT * FROM portfolio WHERE user_id=? AND coin=?",
                (user_id, coin.lower())
            ).fetchone()
            
            if existing and existing["amount"] >= amount:
                new_amount = existing["amount"] - amount
                if new_amount <= 0:
                    # Удаляем позицию если продали все
                    cx.execute(
                        "DELETE FROM portfolio WHERE user_id=? AND coin=?",
                        (user_id, coin.lower())
                    )
                else:
                    # Обновляем количество (средняя цена остается той же)
                    cx.execute(
                        "UPDATE portfolio SET amount=? WHERE user_id=? AND coin=?",
                        (new_amount, user_id, coin.lower())
                    )
        
        return tx_id


def get_user_portfolio(user_id: int) -> list[dict]:
    """Получает портфолио пользователя"""
    cx = _conn()
    cx.row_factory = sqlite3.Row
    return [dict(r) for r in cx.execute(
        "SELECT * FROM portfolio WHERE user_id=? ORDER BY amount DESC",
        (user_id,)
    )]


def get_user_transactions(user_id: int, limit: int = 10) -> list[dict]:
    """Получает последние транзакции пользователя"""
    cx = _conn()
    cx.row_factory = sqlite3.Row
    return [dict(r) for r in cx.execute(
        "SELECT * FROM transactions WHERE user_id=? ORDER BY date DESC LIMIT ?",
        (user_id, limit)
    )]


def delete_transaction(tx_id: int, user_id: int) -> bool:
    """Удаляет транзакцию (только для отладки)"""
    with _conn() as cx:
        cursor = cx.execute(
            "DELETE FROM transactions WHERE id=? AND user_id=?",
            (tx_id, user_id)
        )
        return cursor.rowcount > 0


def get_portfolio_summary(user_id: int, get_current_price_func=None) -> dict:
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