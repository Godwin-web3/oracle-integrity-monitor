"""
SQLite database layer for the multi-chain oracle dashboard.
Stores price history from all 5 sources, disagreement events, depeg events, subscribers.
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "oracle_dashboard.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    # Price snapshots — one row per source per symbol per check
    c.execute("""
        CREATE TABLE IF NOT EXISTS price_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            source TEXT NOT NULL,
            chain TEXT,
            price REAL NOT NULL,
            checked_at TEXT NOT NULL
        )
    """)

    # Oracle disagreements
    c.execute("""
        CREATE TABLE IF NOT EXISTS disagreements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            median_price REAL NOT NULL,
            max_deviation_pct REAL NOT NULL,
            severity INTEGER NOT NULL,
            leading_source TEXT,
            lagging_source TEXT,
            sources_json TEXT,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1
        )
    """)

    # Depeg events
    c.execute("""
        CREATE TABLE IF NOT EXISTS depeg_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            price REAL NOT NULL,
            peg REAL NOT NULL DEFAULT 1.0,
            deviation_pct REAL NOT NULL,
            severity INTEGER NOT NULL,
            direction TEXT NOT NULL,
            source TEXT,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1
        )
    """)

    # Subscribers
    c.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            chat_id INTEGER PRIMARY KEY,
            username TEXT,
            subscribed_at TEXT NOT NULL,
            disagreement_threshold REAL NOT NULL DEFAULT 0.005,
            depeg_threshold REAL NOT NULL DEFAULT 0.01
        )
    """)

    # Indexes
    c.execute("CREATE INDEX IF NOT EXISTS idx_snap_symbol ON price_snapshots(symbol)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_snap_source ON price_snapshots(source)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_snap_time ON price_snapshots(checked_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_disagree_sym ON disagreements(symbol)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_depeg_sym ON depeg_events(symbol)")

    conn.commit()
    conn.close()


# ── Price Snapshots ──────────────────────────────────────────────────────────

def save_price_snapshot(symbol: str, source: str, price: float, chain: str | None = None):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO price_snapshots (symbol, source, chain, price, checked_at)
        VALUES (?, ?, ?, ?, ?)
    """, (symbol, source, chain, price, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def save_price_snapshots_bulk(rows: list[tuple]):
    """rows = [(symbol, source, chain, price), ...]"""
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    c = conn.cursor()
    c.executemany(
        "INSERT INTO price_snapshots (symbol, source, chain, price, checked_at) VALUES (?,?,?,?,?)",
        [(r[0], r[1], r[2], r[3], now) for r in rows],
    )
    conn.commit()
    conn.close()


def get_latest_prices_by_source(limit_per_symbol: int = 1) -> list[dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT ps.symbol, ps.source, ps.chain, ps.price, ps.checked_at
        FROM price_snapshots ps
        INNER JOIN (
            SELECT symbol, source, MAX(checked_at) AS max_time
            FROM price_snapshots
            GROUP BY symbol, source
        ) latest ON ps.symbol = latest.symbol AND ps.source = latest.source
                 AND ps.checked_at = latest.max_time
    """)
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_price_history(symbol: str, source: str | None = None, limit: int = 200) -> list[dict]:
    conn = get_conn()
    c = conn.cursor()
    if source:
        c.execute("""
            SELECT symbol, source, price, checked_at
            FROM price_snapshots WHERE symbol=? AND source=?
            ORDER BY checked_at DESC LIMIT ?
        """, (symbol, source, limit))
    else:
        c.execute("""
            SELECT symbol, source, price, checked_at
            FROM price_snapshots WHERE symbol=?
            ORDER BY checked_at DESC LIMIT ?
        """, (symbol, limit))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


# ── Disagreements ────────────────────────────────────────────────────────────

_active_disagreements: dict[str, int] = {}  # symbol → row id


def record_disagreement(symbol: str, median: float, max_dev_pct: float,
                         severity: int, leading: str, lagging: str, sources_json: str) -> bool:
    """Record or update a disagreement. Returns True if it's a new event."""
    import json
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    c = conn.cursor()

    if symbol in _active_disagreements:
        row_id = _active_disagreements[symbol]
        c.execute("""
            UPDATE disagreements
            SET last_seen=?, max_deviation_pct=?, severity=?, median_price=?,
                leading_source=?, lagging_source=?, sources_json=?
            WHERE id=?
        """, (now, max_dev_pct, severity, median, leading, lagging, sources_json, row_id))
        conn.commit()
        conn.close()
        return False

    c.execute("""
        INSERT INTO disagreements
            (symbol, median_price, max_deviation_pct, severity, leading_source,
             lagging_source, sources_json, first_seen, last_seen, is_active)
        VALUES (?,?,?,?,?,?,?,?,?,1)
    """, (symbol, median, max_dev_pct, severity, leading, lagging, sources_json, now, now))
    row_id = c.lastrowid
    _active_disagreements[symbol] = row_id
    conn.commit()
    conn.close()
    return True


def resolve_disagreement(symbol: str):
    if symbol not in _active_disagreements:
        return
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        UPDATE disagreements SET is_active=0, last_seen=? WHERE id=?
    """, (now, _active_disagreements.pop(symbol)))
    conn.commit()
    conn.close()


def get_recent_disagreements(limit: int = 50) -> list[dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM disagreements ORDER BY last_seen DESC LIMIT ?
    """, (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_active_disagreements() -> list[dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM disagreements WHERE is_active=1 ORDER BY severity DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Depeg Events ─────────────────────────────────────────────────────────────

_active_depegs: dict[str, int] = {}  # symbol → row id


def record_depeg(symbol: str, price: float, peg: float, deviation_pct: float,
                 severity: int, direction: str, source: str | None = None) -> bool:
    """Record or update a depeg event. Returns True if it's new."""
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    c = conn.cursor()

    if symbol in _active_depegs:
        row_id = _active_depegs[symbol]
        c.execute("""
            UPDATE depeg_events
            SET last_seen=?, price=?, deviation_pct=?, severity=?
            WHERE id=?
        """, (now, price, deviation_pct, severity, row_id))
        conn.commit()
        conn.close()
        return False

    c.execute("""
        INSERT INTO depeg_events
            (symbol, price, peg, deviation_pct, severity, direction, source,
             first_seen, last_seen, is_active)
        VALUES (?,?,?,?,?,?,?,?,?,1)
    """, (symbol, price, peg, deviation_pct, severity, direction, source, now, now))
    _active_depegs[symbol] = c.lastrowid
    conn.commit()
    conn.close()
    return True


def resolve_depeg(symbol: str):
    if symbol not in _active_depegs:
        return
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        UPDATE depeg_events SET is_active=0, last_seen=? WHERE id=?
    """, (now, _active_depegs.pop(symbol)))
    conn.commit()
    conn.close()


def get_depeg_history(limit: int = 50) -> list[dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM depeg_events ORDER BY last_seen DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_active_depegs() -> list[dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM depeg_events WHERE is_active=1")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Subscribers ───────────────────────────────────────────────────────────────

def add_subscriber(chat_id: int, username: str, dis_thresh: float = 0.005,
                   dep_thresh: float = 0.01):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT OR IGNORE INTO subscribers
            (chat_id, username, subscribed_at, disagreement_threshold, depeg_threshold)
        VALUES (?,?,?,?,?)
    """, (chat_id, username, datetime.utcnow().isoformat(), dis_thresh, dep_thresh))
    conn.commit()
    conn.close()


def remove_subscriber(chat_id: int) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM subscribers WHERE chat_id=?", (chat_id,))
    n = c.rowcount
    conn.commit()
    conn.close()
    return n > 0


def is_subscriber(chat_id: int) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT 1 FROM subscribers WHERE chat_id=?", (chat_id,))
    r = c.fetchone()
    conn.close()
    return r is not None


def get_all_subscribers() -> list[dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM subscribers")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_subscriber(chat_id: int) -> dict | None:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM subscribers WHERE chat_id=?", (chat_id,))
    r = c.fetchone()
    conn.close()
    return dict(r) if r else None


def update_subscriber_thresholds(chat_id: int, dis_thresh: float | None = None,
                                  dep_thresh: float | None = None):
    conn = get_conn()
    c = conn.cursor()
    if dis_thresh is not None:
        c.execute("UPDATE subscribers SET disagreement_threshold=? WHERE chat_id=?",
                  (dis_thresh, chat_id))
    if dep_thresh is not None:
        c.execute("UPDATE subscribers SET depeg_threshold=? WHERE chat_id=?",
                  (dep_thresh, chat_id))
    conn.commit()
    conn.close()


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats() -> dict:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM subscribers")
    subs = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM disagreements WHERE is_active=1")
    active_dis = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM depeg_events WHERE is_active=1")
    active_dep = c.fetchone()[0]
    c.execute("SELECT COUNT(DISTINCT symbol) FROM price_snapshots")
    total_coins = c.fetchone()[0]
    c.execute("SELECT COUNT(DISTINCT source) FROM price_snapshots")
    active_sources = c.fetchone()[0]
    conn.close()
    return {
        "subscribers": subs,
        "active_disagreements": active_dis,
        "active_depegs": active_dep,
        "total_coins_tracked": total_coins,
        "active_sources": active_sources,
    }
