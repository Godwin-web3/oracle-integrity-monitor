import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "depeg_monitor.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            chat_id INTEGER PRIMARY KEY,
            username TEXT,
            subscribed_at TEXT,
            alert_threshold REAL DEFAULT 0.01
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coin_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            price REAL NOT NULL,
            peg REAL NOT NULL,
            deviation REAL NOT NULL,
            is_depegged INTEGER NOT NULL DEFAULT 0,
            checked_at TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS depeg_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coin_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            price REAL NOT NULL,
            peg REAL NOT NULL,
            deviation REAL NOT NULL,
            direction TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            resolved_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def add_subscriber(chat_id, username, threshold=0.01):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT OR IGNORE INTO subscribers (chat_id, username, subscribed_at, alert_threshold)
        VALUES (?, ?, ?, ?)
    """, (chat_id, username, datetime.utcnow().isoformat(), threshold))
    conn.commit()
    conn.close()


def remove_subscriber(chat_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM subscribers WHERE chat_id = ?", (chat_id,))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def get_all_subscribers():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM subscribers")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def is_subscriber(chat_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT 1 FROM subscribers WHERE chat_id = ?", (chat_id,))
    result = c.fetchone()
    conn.close()
    return result is not None


def update_alert_threshold(chat_id, threshold):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE subscribers SET alert_threshold = ? WHERE chat_id = ?", (threshold, chat_id))
    conn.commit()
    conn.close()


def get_subscriber_threshold(chat_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT alert_threshold FROM subscribers WHERE chat_id = ?", (chat_id,))
    row = c.fetchone()
    conn.close()
    return row["alert_threshold"] if row else 0.01


def save_price(coin_id, symbol, price, peg, deviation, is_depegged):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO price_history (coin_id, symbol, price, peg, deviation, is_depegged, checked_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (coin_id, symbol, price, peg, deviation, int(is_depegged), datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def record_depeg_event(coin_id, symbol, price, peg, deviation, direction):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO depeg_events (coin_id, symbol, price, peg, deviation, direction, detected_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (coin_id, symbol, price, peg, deviation, direction, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def get_recent_prices(limit=100):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM price_history
        ORDER BY checked_at DESC
        LIMIT ?
    """, (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_prices():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT ph.*
        FROM price_history ph
        INNER JOIN (
            SELECT coin_id, MAX(checked_at) as max_time
            FROM price_history
            GROUP BY coin_id
        ) latest ON ph.coin_id = latest.coin_id AND ph.checked_at = latest.max_time
    """)
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_depeg_history(limit=50):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM depeg_events
        ORDER BY detected_at DESC
        LIMIT ?
    """, (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_price_chart_data(coin_id, limit=288):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT price, deviation, is_depegged, checked_at
        FROM price_history
        WHERE coin_id = ?
        ORDER BY checked_at DESC
        LIMIT ?
    """, (coin_id, limit))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]
