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
        """)
        row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
        if row[0] == 0:
            from auth import hash_password
            conn.execute(
                "INSERT INTO users (username, password_hash, display_name, is_admin) VALUES (?,?,?,1)",
                ("admin", hash_password("admin123"), "系統管理員")
            )
            conn.commit()


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a.strip(), b.strip()).ratio()


def lookup_product(company: str, product_name: str) -> dict | None:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM products").fetchall()

    if not rows:
        return None

    # Filter by company: one name contains the other, or similarity >= 0.7
    company_matches = [
        r for r in rows
        if company in r["company"] or r["company"] in company
        or _sim(company, r["company"]) >= 0.7
    ]
    pool = company_matches if company_matches else list(rows)

    # Find best product name match
    best = max(pool, key=lambda r: _sim(r["product_name"], product_name))
    score = _sim(best["product_name"], product_name)

    # Accept if high similarity OR one name is substring of the other (≥4 chars)
    name_substr = (
        len(product_name) >= 4 and (
            product_name in best["product_name"] or best["product_name"] in product_name
        )
    )
    if score >= 0.75 or name_substr:
        return {"product": dict(best), "score": round(score, 2)}

    return None


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
