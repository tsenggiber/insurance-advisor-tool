"""
tii_lookup.py
從 tii_scraper.db 查詢保單資料、從 R2 下載 PDF、解析條款文字。
"""

import io
import json
import os
import sqlite3
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import boto3
import pdfplumber
from botocore.config import Config

# ── R2 設定 ───────────────────────────────────────────────────────────────────

R2_ACCOUNT_ID = "56279c540b6e49a298a89749be5f996b"
R2_ACCESS_KEY = "32602fa20182a65f4388be8457df62bc"
R2_SECRET_KEY = "de21f16d0ab5873cc0e77f548cfc06e323a51ecbb5b8d74fa9c879dfe13f83ca"
R2_BUCKET     = "tii-policies"
R2_ENDPOINT   = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

# 預設：repo 根目錄 (backend/../)；Render 上透過 TII_DB_PATH env var 指向 /data/tii_scraper.db
TII_DB_PATH = Path(os.environ.get("TII_DB_PATH", str(Path(__file__).parent.parent / "tii_scraper.db")))

# ── Step 1：查 tii_scraper.db ─────────────────────────────────────────────────

import re as _re

_VERSION_RE      = _re.compile(r'[（(]第(\d+)次[^）)]*[）)]')
_PLAN_VARIANT_RE = _re.compile(r'[（(](?:甲|乙|丙|丁|戊|擇優)[型型]?[^）)]*[）)]')
_PLAN_SUFFIX_RE  = _re.compile(r'\s*[-－]\s*計劃\S*')

def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a.strip(), b.strip()).ratio()


def _strip_version(name: str) -> str:
    return _VERSION_RE.sub('', name).strip()


def _strip_plan_type(name: str) -> str:
    """去掉「(丁型-...)」「(擇優)」「 - 計劃二」等子類型後綴，用於 fallback 比對。"""
    name = _PLAN_SUFFIX_RE.sub('', name)
    name = _PLAN_VARIANT_RE.sub('', name)
    return name.strip()


def tii_lookup(company: str, product_name: str, policy_date: str | None = None) -> dict | None:
    """
    在 tii_scraper.db 找最接近的保單。
    policy_date: 民國格式字串，如 "110/05/01"，用於選正確版本。
    回傳 {"product": {...}, "score": float, "clause_r2_key": str | None}
    """
    if not TII_DB_PATH.exists():
        return None

    query_base    = _strip_version(product_name)
    query_stripped = _strip_plan_type(query_base)  # fallback：去掉計劃型別後綴

    conn = sqlite3.connect(TII_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # SQL 層先篩同公司
        rows = conn.execute(
            """SELECT * FROM tii_products
               WHERE status='done'
               AND (company_name LIKE ? OR ? LIKE '%' || company_name || '%')""",
            (f"%{company}%", company)
        ).fetchall()

        if not rows:
            all_rows = conn.execute(
                "SELECT * FROM tii_products WHERE status='done'"
            ).fetchall()
            rows = [r for r in all_rows if _sim(company, r["company_name"]) >= 0.6] or list(all_rows)
    finally:
        conn.close()

    if not rows:
        return None

    # 用 base_name 比對（去除版次干擾），找最高分的基底名稱群組
    def _best_match(q: str):
        bst = max(rows, key=lambda r: _sim(r["base_name"] or r["product_name"], q))
        sc  = _sim(bst["base_name"] or bst["product_name"], q)
        sub = len(q) >= 4 and (
            q in (bst["base_name"] or "") or
            (bst["base_name"] or "") in q
        )
        return bst, sc, sub

    best_base, base_score, name_substr = _best_match(query_base)

    # Fallback：若原始名稱比對失敗，嘗試去掉計劃型別後綴再比對
    if base_score < 0.65 and not name_substr and query_stripped != query_base:
        best_base2, base_score2, name_substr2 = _best_match(query_stripped)
        if base_score2 >= 0.65 or name_substr2:
            best_base, base_score, name_substr = best_base2, base_score2, name_substr2

    if base_score < 0.65 and not name_substr:
        return None

    # 找同基底名的所有版本
    target_base = best_base["base_name"] or best_base["product_name"]
    same_base = [
        r for r in rows
        if _sim(r["base_name"] or r["product_name"], target_base) >= 0.95
    ]

    # 優先選有 files 的版本（files=[] 的版本沒有可用的 PDF）
    def _has_files(r) -> bool:
        try:
            return len(json.loads(r["files"] or "[]")) > 0
        except Exception:
            return False

    same_base_with_files = [r for r in same_base if _has_files(r)]
    pool = same_base_with_files if same_base_with_files else same_base

    # 依保單日期選版本
    # 注意：DB 欄位名稱與實際意義相反：
    #   end_date = 銷售起始日（產品開始販售的日期）
    #   start_date = 停售日（通常是 &nbsp;/空，代表仍在售）
    # 正確邏輯：找 end_date（銷售起始日）≤ policy_date 的版本，取其中最晚銷售的那版
    if policy_date and pool:
        in_range = [
            r for r in pool
            if (r["end_date"] or "") <= policy_date
        ]
        best = max(in_range, key=lambda r: r["end_date"] or "") if in_range else \
               max(pool, key=lambda r: r["version"] or 0)
    else:
        best = max(pool, key=lambda r: r["version"] or 0)

    score = _sim(best["base_name"] or best["product_name"], query_base)

    # 找保單條款（-A 結尾）與費率表（-C / 費率表 type）的 R2 key
    clause_key = None
    rate_key = None
    try:
        files = json.loads(best["files"] or "[]")
        for f in files:
            if f.get("file_type") == "保單條款" or f.get("filename", "").upper().endswith("-A.PDF"):
                clause_key = f.get("r2_key")
                break
        # fallback：取第一個有 r2_key 的 PDF
        if not clause_key and files:
            clause_key = next((f.get("r2_key") for f in files if f.get("r2_key")), None)
        # 費率表（-C.pdf，含計劃保障額度表）
        for f in files:
            if f.get("file_type") == "費率表" or f.get("filename", "").upper().endswith("-C.PDF"):
                rate_key = f.get("r2_key")
                break
    except Exception:
        pass

    return {
        "product": dict(best),
        "score": round(score, 2),
        "clause_r2_key": clause_key,
        "rate_r2_key": rate_key,
    }


# ── Step 2：從 R2 下載 PDF ────────────────────────────────────────────────────

def fetch_pdf_from_r2(r2_key: str) -> bytes | None:
    """從 Cloudflare R2 下載 PDF，回傳 bytes；失敗回傳 None。"""
    try:
        r2 = boto3.client(
            "s3",
            endpoint_url=R2_ENDPOINT,
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY,
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
        resp = r2.get_object(Bucket=R2_BUCKET, Key=r2_key)
        return resp["Body"].read()
    except Exception:
        return None


# ── Step 3：解析 PDF 文字 ──────────────────────────────────────────────────────

MAX_CHARS = 6000  # 送給 Claude 的最大字數（避免 token 超量）


def parse_pdf_text(pdf_bytes: bytes) -> str:
    """用 pdfplumber 解析 PDF，回傳前 MAX_CHARS 字的純文字。"""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages_text = []
            total = 0
            for page in pdf.pages:
                text = page.extract_text() or ""
                pages_text.append(text)
                total += len(text)
                if total >= MAX_CHARS:
                    break
            full_text = "\n".join(pages_text)
            return full_text[:MAX_CHARS]
    except Exception:
        return ""


# ── 整合：一次查詢 + 下載 + 解析 ──────────────────────────────────────────────

def get_clause_text(company: str, product_name: str, policy_date: str | None = None) -> tuple[str, float]:
    """
    查詢 tii + 下載 PDF + 解析文字。
    回傳 (clause_text, match_score)，找不到則回傳 ("", 0)。
    """
    match = tii_lookup(company, product_name, policy_date)
    if not match or not match["clause_r2_key"]:
        return "", 0.0

    pdf_bytes = fetch_pdf_from_r2(match["clause_r2_key"])
    if not pdf_bytes:
        return "", match["score"]

    text = parse_pdf_text(pdf_bytes)
    return text, match["score"]


# ── 保障欄位快取（存在 Cloudflare R2，跨部署/跨用戶共用）──────────────────────
# R2 路徑：coverage-cache/{product_id}/{plan}.json
# 同一商品只讀一次條款，之後任何用戶、任何伺服器都直接從 R2 取，不再呼叫 Claude

COVERAGE_FIELDS = [
    "disease_hosp_daily", "accident_hosp_daily", "medical_reimburse", "accident_reimburse",
    "inpatient_surgery", "outpatient_surgery", "specific_treatment", "disability_monthly",
    "long_care_monthly", "critical_illness", "cancer_first", "cancer_hosp_daily",
    "cancer_surgery", "accident_death", "fracture", "coverage_end_age", "is_lifetime",
]

def _r2_cache_key(product_id: str, plan: str) -> str:
    safe_plan = plan.replace("/", "_") or "default"
    return f"coverage-cache/{product_id}/{safe_plan}.json"


def get_coverage_cache(product_id: str, plan: str = "") -> dict | None:
    """從 R2 查快取，找到回傳 dict，找不到回傳 None。"""
    try:
        r2 = boto3.client(
            "s3", endpoint_url=R2_ENDPOINT,
            aws_access_key_id=R2_ACCESS_KEY, aws_secret_access_key=R2_SECRET_KEY,
            config=Config(signature_version="s3v4"), region_name="auto",
        )
        key = _r2_cache_key(product_id, plan)
        resp = r2.get_object(Bucket=R2_BUCKET, Key=key)
        return json.loads(resp["Body"].read().decode("utf-8"))
    except Exception:
        return None


def set_coverage_cache(product_id: str, plan: str, fields: dict):
    """將 Claude 提取的保障欄位存入 R2 快取。"""
    try:
        safe = {}
        for k in COVERAGE_FIELDS:
            v = fields.get(k)
            if v is None:
                continue
            if k == "is_lifetime":
                safe[k] = bool(v)
            elif isinstance(v, (int, float)):
                safe[k] = v
        safe["extracted_at"] = datetime.utcnow().isoformat()

        r2 = boto3.client(
            "s3", endpoint_url=R2_ENDPOINT,
            aws_access_key_id=R2_ACCESS_KEY, aws_secret_access_key=R2_SECRET_KEY,
            config=Config(signature_version="s3v4"), region_name="auto",
        )
        key = _r2_cache_key(product_id, plan)
        r2.put_object(
            Bucket=R2_BUCKET, Key=key,
            Body=json.dumps(safe, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )
    except Exception:
        pass
