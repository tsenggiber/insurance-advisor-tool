#!/usr/bin/env python3
"""
pre_cache_coverage.py
批次預存常見附約保障欄位到 R2 cache。
已有快取的自動跳過，安全可重跑。

用法：
  python3 pre_cache_coverage.py          # 正式跑
  python3 pre_cache_coverage.py --dry    # 只統計數量，不呼叫 API
  python3 pre_cache_coverage.py --company 國泰人壽  # 只跑特定公司
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

import anthropic
from tii_lookup import (
    TII_DB_PATH, fetch_pdf_from_r2, parse_pdf_text,
    get_coverage_cache, set_coverage_cache, COVERAGE_FIELDS,
)

# ── 設定 ──────────────────────────────────────────────────────────────────────

DEFAULT_COMPANIES = [
    "國泰人壽", "台灣人壽", "南山人壽", "富邦人壽",
    "新光人壽", "中國人壽", "全球人壽", "遠雄人壽",
]
TARGET_CATEGORIES = ["健康保險", "傷害保險", "失能扶助保險"]
SKIP_KEYWORDS     = ["主約", "儲蓄", "投資連結", "利率變動"]
CALL_INTERVAL     = 5.0  # 每次 API call 之間的間隔（秒），避免 rate limit（50k tokens/min）
MAX_RETRY         = 3    # 遇到 rate limit 最多重試次數

_COVERAGE_EXTRACT_TOOL = {
    "name": "extract_policy_coverage",
    "description": "從條款文字中提取此保單的保障給付細項",
    "input_schema": {
        "type": "object",
        "required": ["disease_hosp_daily", "medical_reimburse",
                     "accident_hosp_daily", "accident_reimburse"],
        "properties": {
            "disease_hosp_daily":  {"type": "number"},
            "accident_hosp_daily": {"type": "number"},
            "inpatient_surgery":   {"type": "number"},
            "outpatient_surgery":  {"type": "number"},
            "specific_treatment":  {"type": "number"},
            "medical_reimburse":   {"type": "number"},
            "accident_reimburse":  {"type": "number"},
            "deductible":          {"type": "number"},
            "disability_monthly":  {"type": "number"},
            "long_care_monthly":   {"type": "number"},
            "critical_illness":    {"type": "number"},
            "cancer_first":        {"type": "number"},
            "cancer_hosp_daily":   {"type": "number"},
            "cancer_surgery":      {"type": "number"},
            "accident_death":      {"type": "number"},
            "fracture":            {"type": "number"},
            "coverage_end_age":    {"type": "integer"},
            "is_lifetime":         {"type": "boolean"},
        }
    }
}

# ── 查詢待處理清單 ─────────────────────────────────────────────────────────────

def get_products(companies: list[str]) -> list[dict]:
    """取各公司最新版本的目標附約清單（去重）。"""
    conn = sqlite3.connect(TII_DB_PATH)
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(companies))
    skip_cond = " AND ".join(f"product_name NOT LIKE '%{kw}%'" for kw in SKIP_KEYWORDS)
    cat_placeholders = ",".join("?" * len(TARGET_CATEGORIES))

    rows = conn.execute(f"""
        SELECT p.product_id, p.company_name, p.product_name, p.base_name,
               p.version, p.files
        FROM tii_products p
        INNER JOIN (
            SELECT base_name, company_name, MAX(version) as max_ver
            FROM tii_products
            WHERE status='done'
              AND files LIKE '%-A.pdf%'
              AND company_name IN ({placeholders})
              AND category IN ({cat_placeholders})
              AND {skip_cond}
            GROUP BY base_name, company_name
        ) latest
        ON p.base_name = latest.base_name
           AND p.company_name = latest.company_name
           AND p.version = latest.max_ver
        WHERE p.status='done'
        ORDER BY p.company_name, p.base_name
    """, companies + TARGET_CATEGORIES).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_clause_and_rate_keys(files_json: str) -> tuple[str | None, str | None]:
    """從 files JSON 取條款(-A)與費率表(-C)的 R2 key。"""
    try:
        files = json.loads(files_json or "[]")
        clause = next(
            (f["r2_key"] for f in files
             if f.get("file_type") == "保單條款" or
             f.get("filename", "").upper().endswith("-A.PDF")), None)
        rate = next(
            (f["r2_key"] for f in files
             if f.get("file_type") == "費率表" or
             f.get("filename", "").upper().endswith("-C.PDF")), None)
        return clause, rate
    except Exception:
        return None, None


# ── 核心：呼叫 Claude 提取一個商品的保障欄位 ──────────────────────────────────

def enrich_product(client: anthropic.Anthropic, product: dict,
                   plan: str = "") -> dict | None:
    clause_key, rate_key = get_clause_and_rate_keys(product["files"])
    if not clause_key:
        return None

    pdf_bytes = fetch_pdf_from_r2(clause_key)
    if not pdf_bytes:
        return None

    clause_text = parse_pdf_text(pdf_bytes)
    if not clause_text:
        return None  # 掃描版 PDF，pdfplumber 抽不出文字，跳過

    rate_text = ""
    if rate_key:
        rate_pdf = fetch_pdf_from_r2(rate_key)
        if rate_pdf:
            rate_text = parse_pdf_text(rate_pdf)

    name = product["product_name"]
    plan_hint = plan or "（依條款判斷，若有計劃別請提取最低計劃的數值）"

    hint = (
        f"商品名稱：{name}\n"
        f"投保計劃：{plan_hint}\n"
        "【重要】請只依條款/費率表文字填入數字，看不到的填0，不要猜測。\n\n"
        "===條款節錄===\n" + clause_text[:2000] + "\n\n"
        + (f"===費率表節錄（含計劃保障額度表）===\n{rate_text[:2000]}\n\n" if rate_text else "")
        + "請從以上文字找出正確的保障給付金額（找不到填0）：\n"
        "・disease_hosp_daily：住院病房費用限額（元/日）\n"
        "・medical_reimburse：住院醫療費實支上限（元，填基本限額）\n"
        "・accident_reimburse：意外醫療費用實支上限（元）\n"
        "・inpatient_surgery：外科手術費用限額（元/次）。若條款同時涵蓋住院和門診外科手術，填此欄\n"
        "・outpatient_surgery：【嚴格定義】真正的門診外科手術費用限額（元/次）。\n"
        "  ※「住院前後門診費用」「住院前後門診費保險金」= 掛號補貼，不是手術，填0\n"
        "  ※ 無單獨門診手術條款時填0，不要猜測\n"
        "・specific_treatment：出院後特殊治療費用限額（元/年，如放射線治療、化療）\n"
        "・accident_hosp_daily：意外住院日額（元/日）\n"
        "・disability_monthly：失能月扶助金（元/月，只填月給付型）\n"
        "・long_care_monthly：長照月給付（元/月）\n"
        "・critical_illness：重大疾病/失能一次金（元）\n"
        "・cancer_first：初次罹癌一次金（元）\n"
        "・cancer_hosp_daily：癌症住院日額（元/日）\n"
        "・cancer_surgery：癌症手術給付（元/次）\n"
        "・accident_death：意外身故保額（元）\n"
        "・fracture：骨折保險金（元）\n"
        "・is_lifetime：保障至終身或99歲填 true\n"
    )

    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",  # 用 Haiku，便宜 10 倍
        max_tokens=512,
        tools=[_COVERAGE_EXTRACT_TOOL],
        tool_choice={"type": "tool", "name": "extract_policy_coverage"},
        messages=[{"role": "user", "content": hint}]
    )
    tool_block = next((b for b in resp.content if b.type == "tool_use"), None)
    if not tool_block:
        return None

    extracted = {}
    for k, v in tool_block.input.items():
        if v is None:
            continue
        if isinstance(v, bool):
            extracted[k] = v
        elif isinstance(v, (int, float)) and float(v) > 0:
            extracted[k] = v
    return extracted if extracted else None


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry",     action="store_true", help="只統計，不呼叫 API")
    parser.add_argument("--company", type=str, default=None, help="只處理特定公司")
    args = parser.parse_args()

    companies = [args.company] if args.company else DEFAULT_COMPANIES
    products  = get_products(companies)

    print(f"\n找到 {len(products)} 筆獨立商品（最新版本）")
    if args.dry:
        # 統計還沒快取的數量
        need_cache = 0
        for p in products:
            if not get_coverage_cache(p["product_id"], ""):
                need_cache += 1
        print(f"其中 {need_cache} 筆尚未快取（{len(products) - need_cache} 筆已有快取）")
        est_usd = need_cache * 0.003  # Haiku 成本大幅降低
        print(f"預估費用：~${est_usd:.1f} USD ≈ NT${est_usd*32:.0f}")
        return

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    done = skip_cached = skip_empty = error = 0

    for i, p in enumerate(products, 1):
        pid  = p["product_id"]
        name = p["product_name"]

        # 已有快取就跳過
        if get_coverage_cache(pid, ""):
            skip_cached += 1
            continue

        print(f"[{i}/{len(products)}] {p['company_name']} | {name[:40]}")

        api_called = False
        for attempt in range(MAX_RETRY):
            try:
                extracted = enrich_product(client, p, plan="")
                if extracted is None:
                    print(f"  → 跳過（空白 PDF 或無法提取）")
                    skip_empty += 1
                else:
                    set_coverage_cache(pid, "", extracted)
                    fields_found = [k for k in COVERAGE_FIELDS if extracted.get(k)]
                    print(f"  → 快取成功：{', '.join(fields_found) or '（無保障數字）'}")
                    done += 1
                    api_called = True
                break
            except Exception as e:
                msg = str(e)
                if "rate_limit" in msg or "429" in msg:
                    wait = 60 * (attempt + 1)
                    print(f"  → Rate limit，等 {wait} 秒後重試...")
                    time.sleep(wait)
                    api_called = True
                else:
                    print(f"  → 錯誤：{msg[:80]}")
                    error += 1
                    break

        # 只有真正呼叫 API 才等 5 秒；空白 PDF 跳過只等 0.5 秒
        time.sleep(CALL_INTERVAL if api_called else 0.5)

    print(f"\n完成：成功 {done}，已有快取跳過 {skip_cached}，空PDF跳過 {skip_empty}，錯誤 {error}")


if __name__ == "__main__":
    main()
