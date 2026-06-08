import sqlite3
import os
from difflib import SequenceMatcher

DB_PATH = os.path.join(os.path.dirname(__file__), "app.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                is_admin INTEGER NOT NULL DEFAULT 0,
                expires_at TEXT,
                device_token TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
            CREATE TABLE IF NOT EXISTS analysis_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                client_name TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL,
                product_name TEXT NOT NULL,
                insurance_type TEXT NOT NULL,
                premium_type TEXT NOT NULL,
                coverage_end_age INTEGER NOT NULL DEFAULT 75,
                added_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                UNIQUE(company, product_name)
            );
            CREATE TABLE IF NOT EXISTS api_cost_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT 'claude-sonnet-4-6',
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                user_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
            CREATE TABLE IF NOT EXISTS product_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL,
                product_name TEXT NOT NULL,
                reported_by TEXT NOT NULL DEFAULT '',
                note TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
        """)
        # 舊版升級：補欄位
        for col, definition in [("expires_at", "TEXT"), ("device_token", "TEXT")]:
            try:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
                conn.commit()
            except Exception:
                pass

        row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
        if row[0] == 0:
            from auth import hash_password
            conn.execute(
                "INSERT INTO users (username, password_hash, display_name, is_admin) VALUES (?,?,?,1)",
                ("admin", hash_password("admin123"), "系統管理員")
            )
            conn.commit()


MODEL_PRICING = {
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},   # USD per MTok
    "claude-opus-4-8":   {"input": 15.0, "output": 75.0},
    "claude-haiku-4-5":  {"input": 0.8,  "output": 4.0},
}

def log_api_usage(endpoint: str, model: str, input_tokens: int, output_tokens: int, user_id=None):
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO api_cost_logs (endpoint, model, input_tokens, output_tokens, user_id) VALUES (?,?,?,?,?)",
                (endpoint, model, input_tokens, output_tokens, user_id)
            )
            conn.commit()
    except Exception:
        pass


def get_cost_summary():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, endpoint, model, input_tokens, output_tokens, created_at FROM api_cost_logs ORDER BY created_at DESC"
        ).fetchall()
    result = []
    total_usd = 0.0
    for r in rows:
        pricing = MODEL_PRICING.get(r["model"], {"input": 3.0, "output": 15.0})
        cost = (r["input_tokens"] * pricing["input"] + r["output_tokens"] * pricing["output"]) / 1_000_000
        total_usd += cost
        result.append({
            "id": r["id"],
            "endpoint": r["endpoint"],
            "model": r["model"],
            "input_tokens": r["input_tokens"],
            "output_tokens": r["output_tokens"],
            "cost_usd": round(cost, 6),
            "created_at": r["created_at"],
        })
    return {"total_usd": round(total_usd, 4), "logs": result}


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a.strip(), b.strip()).ratio()


def lookup_product(company: str, product_name: str) -> dict | None:
    # 先查手動維護的 app.db
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM products").fetchall()

    if rows:
        company_matches = [
            r for r in rows
            if company in r["company"] or r["company"] in company
            or _sim(company, r["company"]) >= 0.7
        ]
        pool = company_matches if company_matches else list(rows)
        best = max(pool, key=lambda r: _sim(r["product_name"], product_name))
        score = _sim(best["product_name"], product_name)
        name_substr = (
            len(product_name) >= 4 and (
                product_name in best["product_name"] or best["product_name"] in product_name
            )
        )
        if score >= 0.75 or name_substr:
            return {"product": dict(best), "score": round(score, 2), "source": "manual"}

    # 若 app.db 查無結果，改查 tii_scraper.db
    try:
        from tii_lookup import tii_lookup
        match = tii_lookup(company, product_name)
        if match:
            p = match["product"]
            return {
                "product": {
                    "company":          p["company_name"],
                    "product_name":     p["product_name"],
                    "insurance_type":   p["category"],
                    "premium_type":     "自然保費" if p["category"] in ("健康保險", "傷害保險") else "平準保費",
                    "coverage_end_age": 75,
                },
                "score":  match["score"],
                "source": "tii",
                "clause_r2_key": match.get("clause_r2_key"),
            }
    except Exception:
        pass

    return None


def insert_report(company: str, product_name: str, reported_by: str, note: str = '') -> bool:
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO product_reports (company, product_name, reported_by, note) VALUES (?,?,?,?)",
                (company, product_name, reported_by, note)
            )
            conn.commit()
        return True
    except Exception:
        return False


def insert_product(company: str, product_name: str, insurance_type: str,
                   premium_type: str, coverage_end_age: int, added_by: str) -> bool:
    try:
        with get_db() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO products
                   (company, product_name, insurance_type, premium_type, coverage_end_age, added_by)
                   VALUES (?,?,?,?,?,?)""",
                (company, product_name, insurance_type, premium_type, coverage_end_age, added_by)
            )
            conn.commit()
        return True
    except Exception:
        return False
