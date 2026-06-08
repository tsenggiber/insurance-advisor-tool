"""
rate_lookup.py
從 tii PDF（R2）提取費率表，快取至 tii_scraper.db，供保費曲線使用。
使用 pdfplumber 解析表格，不依賴 Claude API（省成本、更穩定）。
"""

import io
import json
import re
import sqlite3
from pathlib import Path

import boto3
import pdfplumber
from botocore.config import Config

TII_DB_PATH = Path(__file__).parent.parent.parent / "tii_scraper.db"

R2_ACCOUNT_ID = "56279c540b6e49a298a89749be5f996b"
R2_ACCESS_KEY = "32602fa20182a65f4388be8457df62bc"
R2_SECRET_KEY = "de21f16d0ab5873cc0e77f548cfc06e323a51ecbb5b8d74fa9c879dfe13f83ca"
R2_BUCKET     = "tii-policies"
R2_ENDPOINT   = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"


# ── DB 快取 ───────────────────────────────────────────────────────────────────

def _get_cached(product_id: str, gender: str, occupation_class: int | None,
                plan: str | None = None) -> list[dict] | None:
    if not TII_DB_PATH.exists():
        return None
    conn = sqlite3.connect(TII_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        if occupation_class:
            period_filter = f"第{occupation_class}類"
            rows = conn.execute(
                "SELECT age, rate_per_10k, period FROM rate_tables WHERE product_id=? AND period=? ORDER BY age",
                (product_id, period_filter)
            ).fetchall()
        elif plan:
            # 計劃型：完全比對；型別（甲型/丁型）：前綴比對（取第1類為代表）
            if plan.endswith("型"):
                rows = conn.execute(
                    "SELECT age, rate_per_10k, period FROM rate_tables WHERE product_id=? AND period=? ORDER BY age",
                    (product_id, f"{plan}第1類")
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT age, rate_per_10k, period FROM rate_tables WHERE product_id=? AND period=? ORDER BY age",
                    (product_id, plan)
                ).fetchall()
        else:
            # 醫療型（有性別）或 any 性別
            rows = conn.execute(
                "SELECT age, rate_per_10k, period FROM rate_tables WHERE product_id=? AND gender IN (?,?) ORDER BY age",
                (product_id, gender, "any")
            ).fetchall()
        return [dict(r) for r in rows] if rows else None
    finally:
        conn.close()


def _store_rates(product_id: str, rates: list[dict]):
    """rates: [{gender, age, period, rate_per_10k}, ...]"""
    if not TII_DB_PATH.exists() or not rates:
        return
    conn = sqlite3.connect(TII_DB_PATH)
    try:
        conn.executemany(
            """INSERT OR REPLACE INTO rate_tables (product_id, gender, age, period, rate_per_10k)
               VALUES (:product_id, :gender, :age, :period, :rate_per_10k)""",
            [{"product_id": product_id, **r} for r in rates]
        )
        conn.commit()
    finally:
        conn.close()


# ── R2 下載 ───────────────────────────────────────────────────────────────────

def _fetch_r2(r2_key: str) -> bytes | None:
    try:
        r2 = boto3.client(
            "s3",
            endpoint_url=R2_ENDPOINT,
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY,
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
        return r2.get_object(Bucket=R2_BUCKET, Key=r2_key)["Body"].read()
    except Exception:
        return None


# ── PDF 解析 ──────────────────────────────────────────────────────────────────

def _parse_num(s: str) -> float | None:
    """'4,099' → 4099.0；失敗回 None"""
    try:
        return float(s.replace(",", "").replace("，", "").strip())
    except Exception:
        return None


def _expand_age_range(age_str: str) -> list[int]:
    """'35~39' → [35,36,37,38,39]；'0~14' → [0..14]；'36' → [36]"""
    age_str = age_str.strip()
    m = re.match(r'(\d+)[~～\-–](\d+)', age_str)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return list(range(lo, hi + 1))
    try:
        return [int(age_str)]
    except Exception:
        return []


def _parse_medical_rate_table(text: str) -> list[dict]:
    """
    解析醫療/壽險費率表：
    格式：保險年齡(歲) 男性 女性 男性 女性 ...（多計劃）
    或每列：年齡區間 費率1 費率2 ...
    回傳 [{gender, age, period, rate_per_10k}, ...]
    """
    results = []
    seen = set()  # (gender, plan, age) 防止重複覆蓋
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    # 找標題行（含「計劃」或「男性」「女性」的行）
    header_idx = None
    plan_labels = []
    for i, line in enumerate(lines):
        if '男性' in line and '女性' in line:
            header_idx = i
            # 解析計劃名（M10, M20 等在標題行或上一行）
            plan_line = lines[i - 1] if i > 0 else ""
            plans = re.findall(r'[A-Z]\d+', plan_line)
            plan_labels = plans if plans else [""]
            break

    if header_idx is None:
        return []

    # 計算每個計劃的男女欄位數
    male_count   = text.count('男性')
    female_count = text.count('女性')
    cols_per_plan = 2  # male + female

    for line in lines[header_idx + 1:]:
        # 跳過注意事項、空行
        if '註' in line or len(line) < 4:
            continue
        tokens = re.split(r'\s+', line)
        if not tokens:
            continue

        # 第一個 token 是年齡（區間或單一）
        ages = _expand_age_range(tokens[0])
        if not ages:
            continue

        nums = [_parse_num(t) for t in tokens[1:]]
        nums = [n for n in nums if n is not None]
        if not nums:
            continue

        # 每個計劃兩個數：男、女
        for plan_i, plan in enumerate(plan_labels or [""]):
            m_idx = plan_i * 2
            f_idx = plan_i * 2 + 1
            male_rate   = nums[m_idx] if m_idx < len(nums) else None
            female_rate = nums[f_idx] if f_idx < len(nums) else None

            for age in ages:
                if male_rate is not None:
                    k = ("male", plan, age)
                    if k not in seen:
                        seen.add(k)
                        results.append({"gender": "male",   "age": age, "period": plan or None, "rate_per_10k": male_rate})
                if female_rate is not None:
                    k = ("female", plan, age)
                    if k not in seen:
                        seen.add(k)
                        results.append({"gender": "female", "age": age, "period": plan or None, "rate_per_10k": female_rate})

    return results


def _expand_age_range_str(s: str) -> list[int]:
    """
    '0-14歲' / '0~14歲' → [0..14]
    '16歲以上' / '16 歲以上' → [16..99]
    '15 歲' → [15]
    """
    open_ended = '以上' in s
    s = s.replace('歲', '').replace('以上', '').strip()
    m = re.match(r'(\d+)\s*[-~～]\s*(\d+)', s)
    if m:
        return list(range(int(m.group(1)), int(m.group(2)) + 1))
    m2 = re.match(r'^(\d+)$', s.strip())
    if m2:
        lo = int(m2.group(1))
        return list(range(lo, 100)) if open_ended else [lo]
    return []


def _parse_accident_rate_table(text: str) -> list[dict]:
    """
    支援兩種傷害險費率表格式：
    格式A（列=職業類別，欄=年齡）：
        職業類別  0~15歲  16~44歲  45~75歲
        1         41      49       80
    格式B（欄=職業類別，列=年齡）：
        職業類別
        第一類 第二類 第三類 ...
        年齡
        0-14歲 4.5 5.6 ...
    """
    results = []
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    header_idx = None
    for i, line in enumerate(lines):
        if '職業類別' in line:
            header_idx = i
            break

    if header_idx is None:
        return []

    seen = set()  # (period, age) 防止重複覆蓋

    # ── 格式A：職業類別 在同一行且包含年齡區間 ──────────────────────────────
    age_ranges_a = re.findall(r'(\d+)[~～](\d+)', lines[header_idx])
    if age_ranges_a:
        for line in lines[header_idx + 1:]:
            tokens = re.split(r'\s+', line)
            if not tokens or not tokens[0].isdigit():
                continue
            occ_class = int(tokens[0])
            nums = [_parse_num(t) for t in tokens[1:] if _parse_num(t) is not None]
            for j, (lo_s, hi_s) in enumerate(age_ranges_a):
                if j >= len(nums):
                    break
                rate = nums[j]
                for age in range(int(lo_s), int(hi_s) + 1):
                    key = (f"第{occ_class}類", age)
                    if key not in seen:
                        seen.add(key)
                        results.append({"gender": "any", "age": age,
                                        "period": f"第{occ_class}類", "rate_per_10k": rate})
        return results

    # ── 格式B：欄=職業類別（第一類…），列=年齡 ───────────────────────────────
    NUM_MAP = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}
    class_count = 0
    data_start = None
    for i in range(header_idx + 1, min(header_idx + 5, len(lines))):
        cnt = len(re.findall(r'第[一二三四五六\d]類', lines[i]))
        if cnt > 0:
            class_count = cnt
            data_start = i + 1
            break

    if class_count == 0:
        return []

    for i in range(data_start or header_idx + 2, len(lines)):
        line = lines[i]
        tokens = re.split(r'\s+', line)
        if not tokens:
            continue
        ages = _expand_age_range_str(tokens[0])
        if not ages:
            continue
        nums = [_parse_num(t) for t in tokens[1:] if _parse_num(t) is not None]
        for cls_idx in range(min(class_count, len(nums))):
            rate = nums[cls_idx]
            period = f"第{cls_idx + 1}類"
            for age in ages:
                key = (period, age)
                if key not in seen:
                    seen.add(key)
                    results.append({"gender": "any", "age": age,
                                    "period": period, "rate_per_10k": rate})

    return results


def _parse_plan_rate_table(text: str) -> list[dict]:
    """
    計劃型費率表格式（列=計劃，欄=年齡層）：
        年齡層組 0~14  15~24  25~34  35~44  45~54
        計劃一   2,139  2,221  2,650  3,212  4,039
        計劃二   2,954  3,083  3,667  4,463  5,600
    費率為「絕對年繳保費（元）」，非 per 10,000。
    存入 rate_per_10k 欄位（實為年繳額），gender='any'，period='計劃X'。

    注意：同一 PDF 可能有第二張「計劃保障限額表」，其列也以「計劃X」開頭。
    用 seen 集合確保第一張費率表的值不被第二張覆蓋。
    """
    results = []
    seen = set()  # (period, age) 防止第二張表覆蓋第一張費率
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    header_idx = None
    age_ranges = []
    for i, line in enumerate(lines):
        ranges = re.findall(r'(\d+)[~～](\d+)', line)
        if ranges and ('年齡' in line or '計劃' not in line):
            header_idx = i
            age_ranges = ranges
            break

    if not age_ranges:
        return []

    for line in lines[(header_idx or 0) + 1:]:
        m = re.match(r'計劃([一二三四五])', line)
        if not m:
            continue
        period = f"計劃{m.group(1)}"

        tokens = re.split(r'\s+', line)
        nums = [_parse_num(t) for t in tokens[1:] if _parse_num(t) is not None]

        for j, (lo_s, hi_s) in enumerate(age_ranges):
            if j >= len(nums):
                break
            rate = nums[j]
            for age in range(int(lo_s), int(hi_s) + 1):
                key = (period, age)
                if key not in seen:  # 只存第一次出現的值（正確費率）
                    seen.add(key)
                    results.append({"gender": "any", "age": age,
                                    "period": period, "rate_per_10k": rate})

    return results


def _extract_plan_from_name(product_name: str) -> str | None:
    """從商品名稱提取計劃別或型別。
    '計劃二' → '計劃二'
    '(甲型-實支實付)' → '甲型'
    '(丁型-日額)' → '丁型'
    """
    m = re.search(r'計劃([一二三四五\d])', product_name)
    if m:
        return f"計劃{m.group(1)}"
    m2 = re.search(r'[（(]([甲乙丙丁])型', product_name)
    if m2:
        return f"{m2.group(1)}型"
    return None


def _extract_from_pdf_via_claude(pdf_bytes: bytes) -> list[dict]:
    """
    pdfplumber 解析不出文字時（掃描圖像 PDF），
    把每一頁轉成圖像後用 Claude vision 提取費率表。
    支援兩種格式：
    A) 型別×職業類別固定費率（如年年平安傷害醫療）
    B) 職業類別×年齡費率
    """
    import base64, os, anthropic as _ant
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return []

    results = []
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    client = _ant.Anthropic(api_key=api_key) if api_key else _ant.Anthropic()
    for page in doc:
        try:
            pix = page.get_pixmap(dpi=144)
            img_bytes = pix.tobytes("png")
            img_b64 = base64.standard_b64encode(img_bytes).decode()

            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64",
                                                      "media_type": "image/png", "data": img_b64}},
                        {"type": "text", "text": (
                            "這是一張台灣保險費率表圖片。請判斷格式並提取數據：\n\n"
                            "格式A（若有「型別」欄，如甲型/乙型/丙型/丁型）：\n"
                            "輸出CSV：型別,職業類別,保險金額,年繳保費\n"
                            "範例：甲型,1,10000,163\n\n"
                            "格式B（若有「職業類別」和「年齡」）：\n"
                            "輸出CSV：職業類別,年齡,費率\n"
                            "範例：1,36,49\n\n"
                            "第一行輸出格式名稱(A或B)，後面輸出CSV，不需要其他說明文字。"
                        )}
                    ]
                }]
            )
            csv_text = resp.content[0].text.strip() if resp.content else ""
            if not csv_text:
                continue

            lines = csv_text.split('\n')
            fmt = lines[0].strip().upper() if lines else ""

            if 'A' in fmt:
                # 格式A：型別,職業類別,保險金額,年繳保費
                for line in lines[1:]:
                    parts = [p.strip() for p in line.split(',')]
                    if len(parts) < 4:
                        continue
                    try:
                        type_name = parts[0]   # e.g. "甲型"
                        occ = int(parts[1])
                        coverage = float(parts[2].replace(',', ''))
                        premium  = float(parts[3].replace(',', ''))
                        if coverage <= 0:
                            continue
                        rate_per_10k = premium / coverage * 10000
                        period = f"{type_name}第{occ}類"
                        for age in range(0, 100):
                            results.append({"gender": "any", "age": age,
                                            "period": period, "rate_per_10k": rate_per_10k})
                    except Exception:
                        continue
            else:
                # 格式B：職業類別,年齡,費率
                for line in lines[1:]:
                    parts = [p.strip() for p in line.split(',')]
                    if len(parts) < 3:
                        continue
                    try:
                        occ  = int(parts[0])
                        age  = int(parts[1])
                        rate = float(parts[2].replace(',', ''))
                        results.append({"gender": "any", "age": age,
                                        "period": f"第{occ}類", "rate_per_10k": rate})
                    except Exception:
                        continue
        except Exception:
            continue

    return results


def _sanity_check(rates: list[dict]) -> bool:
    """
    基本合理性驗證：檢查費率範圍是否合理。
    - 計劃型：年繳保費應在 500~50,000 之間
    - 一般型（per 10k）：費率應在 0.5~5,000 之間
    回傳 False 表示解析結果異常，需要放棄或重試。
    """
    if not rates:
        return False
    period = rates[0].get("period", "") or ""
    vals = [r["rate_per_10k"] for r in rates]
    if period.startswith("計劃"):
        # 計劃型：絕對年繳保費
        return all(500 <= v <= 50_000 for v in vals)
    else:
        # 一般型：per 10,000 費率
        return all(0.5 <= v <= 10_000 for v in vals)


def _extract_from_pdf(pdf_bytes: bytes) -> list[dict]:
    """主解析：依格式自動選擇 parser；文字極少時改用 Claude vision。"""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception:
        return []

    if '職業類別' in text:
        result = _parse_accident_rate_table(text)
        if result and _sanity_check(result):
            return result

    if '計劃' in text and re.search(r'計劃[一二三四五]', text):
        result = _parse_plan_rate_table(text)
        if result and _sanity_check(result):
            return result

    result = _parse_medical_rate_table(text)
    if result and _sanity_check(result):
        return result

    # 文字太少（掃描圖）→ Claude vision
    if len(text.strip()) < 50:
        return _extract_from_pdf_via_claude(pdf_bytes)

    return []


# ── 主入口 ────────────────────────────────────────────────────────────────────

def get_rate_table(company: str, product_name: str, gender: str,
                   occupation_class: int | None = None) -> list[dict] | None:
    """
    查詢費率表。
    - 醫療/壽險：gender='male'/'female'，回傳 [{age, rate_per_10k, period}, ...]
    - 意外險：occupation_class=2，回傳 [{age, rate_per_10k, period}, ...]
    """
    if not TII_DB_PATH.exists():
        return None

    from tii_lookup import tii_lookup
    match = tii_lookup(company, product_name)
    if not match:
        return None

    product    = match["product"]
    product_id = product["product_id"]
    plan       = _extract_plan_from_name(product_name)  # e.g. "計劃二"

    # 查 DB 快取
    cached = _get_cached(product_id, gender, occupation_class, plan)
    if cached:
        return cached

    # 找費率表 PDF（優先 file_type='費率表'）
    files = []
    try:
        all_files = json.loads(product.get("files") or "[]")
        rate_files = [f for f in all_files if f.get("file_type") == "費率表"]
        files = rate_files or all_files
    except Exception:
        pass

    extracted = None
    for f in files:
        r2_key = f.get("r2_key")
        if not r2_key:
            continue
        pdf_bytes = _fetch_r2(r2_key)
        if not pdf_bytes:
            continue
        extracted = _extract_from_pdf(pdf_bytes)
        if extracted:
            break

    if not extracted:
        return None

    _store_rates(product_id, extracted)

    # 回傳指定性別 / 職業類別 / 計劃別
    if occupation_class:
        period_filter = f"第{occupation_class}類"
        return [r for r in extracted if r.get("period") == period_filter] or None
    if plan:
        if plan.endswith("型"):
            # 固定費率型別（甲型/丁型）：取第1類為代表（比率恆=1，曲線為平線）
            return [r for r in extracted if r.get("period") == f"{plan}第1類"] or None
        return [r for r in extracted if r.get("period") == plan] or None
    # 醫療型：gender 或 any
    return [r for r in extracted if r.get("gender") in (gender, "any")] or None
