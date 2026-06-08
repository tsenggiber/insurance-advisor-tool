import re
import traceback
import concurrent.futures
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

import anthropic
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from models import AnalysisRequest, PptxRequest, LoginRequest, UserCreate, ExtractRequest, ProductCreate, SetExpiry, RateTableRequest

_anthropic = anthropic.Anthropic()
from analyzer import analyze_coverage
from pptx_generator import generate_pptx
from database import (get_db, init_db, lookup_product, insert_product, insert_report,
                      log_api_usage, get_cost_summary, sync_db_to_r2,
                      save_client_session, list_client_sessions, get_client_session, delete_client_session)
from auth import verify_password, create_token, decode_token


FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="Insurance Advisor Tool API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 提供前端靜態檔案（build 後）
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登入")
    try:
        return decode_token(authorization[7:])
    except Exception:
        raise HTTPException(status_code=401, detail="Token 無效或已過期")


def get_admin_user(user: dict = Depends(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="需要管理員權限")
    return user


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/login")
def login(req: LoginRequest):
    import secrets
    from datetime import date
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, display_name, is_active, is_admin, expires_at, device_token FROM users WHERE username=?",
            (req.username,)
        ).fetchone()
    if not row or not verify_password(req.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")
    if not row["is_active"]:
        raise HTTPException(status_code=403, detail="帳號已停用，請聯絡管理員")
    if row["expires_at"] and row["expires_at"] < date.today().isoformat():
        raise HTTPException(status_code=403, detail="帳號已到期，請聯絡管理員續費")

    # 裝置鎖定
    db_token = row["device_token"]
    if db_token:
        if req.device_token != db_token:
            raise HTTPException(status_code=403, detail="此帳號已綁定其他裝置，如需更換請聯絡管理員")
        new_device_token = db_token
    else:
        new_device_token = req.device_token or secrets.token_hex(32)
        with get_db() as conn:
            conn.execute("UPDATE users SET device_token=? WHERE id=?", (new_device_token, row["id"]))
            conn.commit()

    token = create_token(row["id"], row["username"], bool(row["is_admin"]))
    return {
        "token": token,
        "username": row["username"],
        "display_name": row["display_name"],
        "is_admin": bool(row["is_admin"]),
        "device_token": new_device_token,
    }


@app.get("/admin/users")
def admin_list_users(user: dict = Depends(get_admin_user)):
    with get_db() as conn:
        rows = conn.execute("""
            SELECT u.id, u.username, u.display_name, u.is_active, u.is_admin,
                   u.created_at, u.expires_at,
                   (u.device_token IS NOT NULL) as has_device,
                   COUNT(al.id) as analysis_count
            FROM users u
            LEFT JOIN analysis_logs al ON al.user_id = u.id
            GROUP BY u.id
            ORDER BY u.created_at
        """).fetchall()
    return [dict(r) for r in rows]


@app.post("/admin/users")
def admin_create_user(req: UserCreate, user: dict = Depends(get_admin_user)):
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count >= 10:
            raise HTTPException(status_code=400, detail="已達最多 10 個帳號限制")
        from auth import hash_password
        try:
            conn.execute(
                "INSERT INTO users (username, password_hash, display_name, is_admin) VALUES (?,?,?,?)",
                (req.username, hash_password(req.password), req.display_name, int(req.is_admin))
            )
            conn.commit()
        except Exception:
            raise HTTPException(status_code=400, detail="帳號名稱已存在")
    return {"ok": True}


@app.patch("/admin/users/{user_id}/expires")
def admin_set_expires(user_id: int, req: SetExpiry, user: dict = Depends(get_admin_user)):
    with get_db() as conn:
        if not conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone():
            raise HTTPException(status_code=404, detail="找不到此帳號")
        conn.execute("UPDATE users SET expires_at=? WHERE id=?", (req.expires_at, user_id))
        conn.commit()
    return {"expires_at": req.expires_at}


@app.patch("/admin/users/{user_id}/reset-device")
def admin_reset_device(user_id: int, user: dict = Depends(get_admin_user)):
    with get_db() as conn:
        if not conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone():
            raise HTTPException(status_code=404, detail="找不到此帳號")
        conn.execute("UPDATE users SET device_token=NULL WHERE id=?", (user_id,))
        conn.commit()
    return {"ok": True}


@app.patch("/admin/users/{user_id}/toggle")
def admin_toggle_user(user_id: int, user: dict = Depends(get_admin_user)):
    with get_db() as conn:
        row = conn.execute("SELECT is_active, is_admin FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="找不到此帳號")
        if row["is_admin"] and int(user["sub"]) == user_id:
            raise HTTPException(status_code=400, detail="不能停用自己的帳號")
        new_status = 0 if row["is_active"] else 1
        conn.execute("UPDATE users SET is_active=? WHERE id=?", (new_status, user_id))
        conn.commit()
    return {"is_active": bool(new_status)}


@app.get("/admin/costs")
def admin_get_costs(user: dict = Depends(get_admin_user)):
    return get_cost_summary()


@app.post("/analyze")
def analyze(req: AnalysisRequest, user: dict = Depends(get_current_user)):
    try:
        # 嘗試從 tii 抓每張保單的條款文字
        from tii_lookup import get_clause_text
        clause_texts = {}
        for p in req.policies:
            policy_date = getattr(p, "policy_date", None) or None
            text, score = get_clause_text(p.company, p.product_name, policy_date)
            if text:
                clause_texts[f"{p.company}｜{p.product_name}"] = text

        result, usage = analyze_coverage(req.client, req.policies, clause_texts)
        user_id = int(user["sub"])
        with get_db() as conn:
            conn.execute(
                "INSERT INTO analysis_logs (user_id, client_name) VALUES (?,?)",
                (user_id, req.client.name)
            )
            conn.commit()
        log_api_usage("analyze", "claude-sonnet-4-6", usage["input_tokens"], usage["output_tokens"], user_id)
        return result
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


_COVERAGE_EXTRACT_TOOL = {
    "name": "extract_policy_coverage",
    "description": "從條款文字中提取此保單的保障給付細項",
    "input_schema": {
        "type": "object",
        "required": ["disease_hosp_daily", "medical_reimburse", "accident_hosp_daily", "accident_reimburse"],
        "properties": {
            "disease_hosp_daily":  {"type": "number", "description": "疾病住院日額（元/日），無則0"},
            "accident_hosp_daily": {"type": "number", "description": "意外住院日額（元/日），無則0"},
            "inpatient_surgery":   {"type": "number", "description": "外科手術費用限額（元/次）。若條款同時涵蓋住院與門診外科手術（如新住院醫療附約），填此欄，無則0"},
            "outpatient_surgery":  {"type": "number", "description": "真正的門診外科手術費用限額（元/次）。注意：「住院前後門診費用」「住院前後門診費保險金」是掛號/診療費補貼，絕對不是門診手術，填0。無單獨門診手術條款則填0"},
            "specific_treatment":  {"type": "number", "description": "出院後特殊治療費用限額（元/年），如放射線治療、化療，無則0"},
            "medical_reimburse":   {"type": "number", "description": "住院醫療費用實支實付上限（元）。填1-30天的基本限額，不填倍數後最大值，無則0"},
            "accident_reimburse":  {"type": "number", "description": "意外醫療實支實付上限（元），無則0"},
            "deductible":          {"type": "number", "description": "實支自負額（元），無則0"},
            "disability_monthly":  {"type": "number", "description": "失能月給付（元/月），無則0"},
            "long_care_monthly":   {"type": "number", "description": "長照月給付（元/月），無則0"},
            "critical_illness":    {"type": "number", "description": "重大疾病/特定傷病一次金（元），無則0"},
            "cancer_first":        {"type": "number", "description": "初次罹癌一次金（元），無則0"},
            "cancer_hosp_daily":   {"type": "number", "description": "癌症住院日額（元/日），無則0"},
            "cancer_surgery":      {"type": "number", "description": "癌症手術給付（元/次），無則0"},
            "accident_death":      {"type": "number", "description": "意外身故保額（元），無則0"},
            "fracture":            {"type": "number", "description": "骨折保險金（元），無則0"},
            "coverage_end_age":    {"type": "integer", "description": "保障終止年齡（歲）"},
            "is_lifetime":         {"type": "boolean", "description": "是否終身型保障"},
        }
    }
}


def _enrich_one_policy(p: dict) -> dict:
    """
    Phase 1：從商品名稱規則推斷保障欄位（快速）。
    Phase 2：下載 tii 條款 PDF，用 Claude 提取細部保障（精確）。
    """
    from tii_lookup import tii_lookup, fetch_pdf_from_r2, parse_pdf_text

    updated = dict(p)
    name = p.get("product_name", "") or ""
    amt  = float(p.get("coverage_amount", 0) or 0)

    has_detail = any(float(p.get(k, 0) or 0) > 0 for k in [
        "disease_hosp_daily", "accident_hosp_daily", "medical_reimburse",
        "accident_reimburse", "disability_monthly", "accident_death",
        "cancer_first", "critical_illness"
    ])

    # ── Phase 1：規則推斷 ─────────────────────────────────────────────────────
    if not has_detail and amt > 0:
        if "傷害保險" in name and "醫療" not in name and "失能" not in name:
            updated["accident_death"] = amt
        elif ("實支" in name or "實支實付" in name) and ("意外" in name or "傷害" in name):
            updated["accident_reimburse"] = amt
        elif ("實支" in name or "實支實付" in name):
            updated["medical_reimburse"] = amt
        elif "住院費用" in name and "團體" not in name:
            # 住院費用保險附約可能同時含實支實付＋住院日額
            # Phase 1 暫以 medical_reimburse 填入，讀條款後會覆蓋為正確拆分值
            updated["medical_reimburse"] = amt
        elif "日額" in name and ("意外" in name or "傷害" in name):
            updated["accident_hosp_daily"] = amt
        elif "失能扶助金" in name or "失能生活費" in name:
            updated["disability_monthly"] = amt
        elif "重大傷病" in name or "特定傷病" in name or "重大疾病" in name:
            updated["critical_illness"] = amt
        # 一年定期失能 (非扶助金) → 一次金，歸入 critical_illness
        elif "失能" in name and "扶助金" not in name and "長照" not in name:
            updated["critical_illness"] = amt

    # ── Phase 2：查快取 → 有則直接用，無則 Claude 讀條款後存快取 ────────────────
    try:
        from tii_lookup import (tii_lookup, fetch_pdf_from_r2, parse_pdf_text,
                                 get_coverage_cache, set_coverage_cache,
                                 get_manual_cache, COVERAGE_FIELDS)

        match = tii_lookup(p.get("company", ""), name)
        if not match or not match.get("clause_r2_key"):
            # 老商品不在TII → 查手動覆蓋 cache
            manual = get_manual_cache(p.get("company", ""), name)
            if manual:
                for k in COVERAGE_FIELDS:
                    v = manual.get(k)
                    if v is None:
                        continue
                    if k == "is_lifetime":
                        updated[k] = bool(v)
                    elif isinstance(v, (int, float)) and float(v) > 0:
                        updated[k] = v
            return updated

        product_id = match["product"].get("product_id", "")

        # 從商品名稱取出計劃別（計劃一/二/三 或 甲型/丁型）
        plan_m = re.search(r'計劃([一二三四五六七八九])', name)
        plan = f"計劃{plan_m.group(1)}" if plan_m else ""
        if not plan:
            type_m = re.search(r'[（(]([甲乙丙丁])型', name)
            if type_m:
                plan = f"{type_m.group(1)}型"

        # ── 快取命中：直接套用，不呼叫 Claude ─────────────────────────────────
        cached = get_coverage_cache(product_id, plan) if product_id else None
        if cached:
            for k in COVERAGE_FIELDS:
                v = cached.get(k)
                if v is None:
                    continue
                if k == "is_lifetime":
                    updated[k] = bool(v)
                elif isinstance(v, (int, float)) and float(v) > 0:
                    updated[k] = v
            return updated

        # ── 快取未命中：下載 PDF + 呼叫 Claude ────────────────────────────────
        pdf_bytes = fetch_pdf_from_r2(match["clause_r2_key"])
        if not pdf_bytes:
            return updated

        clause_text = parse_pdf_text(pdf_bytes)
        if not clause_text:
            return updated

        # 同時讀費率表 PDF（含計劃保障額度表），給 Claude 正確的計劃限額
        rate_text = ""
        rate_key = match.get("rate_r2_key")
        if rate_key:
            rate_pdf = fetch_pdf_from_r2(rate_key)
            if rate_pdf:
                rate_text = parse_pdf_text(rate_pdf)

        plan_hint = plan or "（依條款判斷）"

        hint = (
            f"商品名稱：{name}\n"
            f"投保計劃：{plan_hint}\n"
            f"保費類型：{p.get('premium_type', '')}\n"
            "【重要】掃描保額欄位可能是舊資料或主約金額，不可直接使用，請以條款/費率表中的計劃限額為準。\n\n"
            "===條款節錄===\n" + clause_text[:2000] + "\n\n"
            + (f"===費率表節錄（含計劃保障額度表）===\n{rate_text[:2000]}\n\n" if rate_text else "")
            + "【閱讀規則 — 每次都必須遵守】\n"
            "1. 手術給付使用「級距×倍率」制：必須讀手術分級表，找出實際的每單位基準金額，填入欄位。不可預設任何數字。\n"
            "2. 住院日額可能有多層：「住院中日額」與「出院療養保險金」是不同條款，金額與天數各不相同，須分別讀取。\n"
            "3. 擇優型實支實付 = 雙重理賠：disease_hosp_daily 與 medical_reimburse 兩欄都要填，不是二選一。\n"
            "4. 住院費用保險附約（含擇優型）可能同時含實支實付＋住院日額，兩欄都要掃描填值。\n"
            "5. outpatient_surgery 陷阱：「住院前後門診費用」「住院前後門診費保險金」= 掛號補貼，不是手術，填0。\n"
            "6. 重大疾病/癌症有給付觸發條件，只記錄條款明定的給付金額，不推測。\n"
            "7. 若費率表有計劃保障額度表，對照「投保計劃」取對應行的數字，不取其他計劃的數字。\n\n"
            "請從以上文字找出正確的保障給付金額，填入對應欄位（找不到填0）：\n"
            "・disease_hosp_daily：住院日額（元/日）。若條款有住院中日額＋出院療養兩段，填住院中日額\n"
            "・medical_reimburse：住院醫療費實支上限（元，填1-30天基本限額，不填倍數後最大值）\n"
            "・accident_reimburse：意外醫療費用實支上限（元）\n"
            "・inpatient_surgery：外科手術費用限額（元/次）。若條款同時涵蓋住院和門診外科手術，填此欄\n"
            "・outpatient_surgery：真正的門診外科手術費用限額（元/次）。無單獨門診手術條款填0\n"
            "・specific_treatment：出院後特殊治療費用限額（元/年，如腫瘤放化療）\n"
            "・accident_hosp_daily：意外住院日額（元/日）\n"
            "・disability_monthly：失能月扶助金（元/月）【只填月給付型，一次金請填 critical_illness】\n"
            "・long_care_monthly：長照月給付（元/月）\n"
            "・critical_illness：重大疾病/特定傷病/失能一次金（元）\n"
            "・cancer_first：初次罹癌一次金（元）\n"
            "・cancer_hosp_daily：癌症住院日額（元/日）\n"
            "・cancer_surgery：癌症手術給付（元/次）\n"
            "・accident_death：意外身故保額（元）\n"
            "・fracture：骨折保險金（元）\n"
            "・is_lifetime：保障至終身或99歲填 true\n"
            "同一條款可同時填多個欄位。"
        )

        resp = _anthropic.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            tools=[_COVERAGE_EXTRACT_TOOL],
            tool_choice={"type": "tool", "name": "extract_policy_coverage"},
            messages=[{"role": "user", "content": hint}]
        )
        log_api_usage("coverage-extract", "claude-sonnet-4-6",
                      resp.usage.input_tokens, resp.usage.output_tokens)
        tool_block = next((b for b in resp.content if b.type == "tool_use"), None)
        if tool_block:
            extracted = {}
            for k, v in tool_block.input.items():
                if v is None:
                    continue
                if isinstance(v, bool):
                    updated[k] = v
                    extracted[k] = v
                elif isinstance(v, (int, float)) and float(v) > 0:
                    updated[k] = v
                    extracted[k] = v
            # 存入快取，下次同商品直接取用
            if product_id and extracted:
                set_coverage_cache(product_id, plan, extracted)

    except Exception:
        pass

    return updated


_EXTRACT_TOOL = {
    "name": "output_policies",
    "description": "輸出從保單文件中辨識到的保單清單",
    "input_schema": {
        "type": "object",
        "required": ["policies"],
        "properties": {
            "policies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["company", "insurance_type", "product_name",
                                 "coverage_amount", "annual_premium", "premium_type", "coverage_end_age"],
                    "properties": {
                        "company":          {"type": "string"},
                        "insurance_type":   {"type": "string", "enum": ["壽險","醫療險","癌症險","意外險","失能險","長照險","儲蓄險"]},
                        "product_name":     {"type": "string"},
                        "coverage_amount":  {"type": "number", "description": "主要保障金額（元），無法辨識填0"},
                        "annual_premium":   {"type": "number", "description": "年繳保費（元），月繳請乘12，無法辨識填0"},
                        "premium_type":     {"type": "string", "enum": ["自然保費","平準保費"]},
                        "coverage_end_age": {"type": "integer", "description": "保障終止年齡，無法辨識填75"},
                        "policy_date":        {"type": "string",  "description": "核保日期或生效日期，民國格式如 110/05/01，無法辨識填空字串"},
                        "is_lifetime":        {"type": "boolean", "description": "是否為終身型保障（保障至99歲或終身）"},
                        "occupation_class":   {"type": "integer", "description": "職業類別 1-6，傷害險/意外險才需填，其他險種填 null"},
                        "disease_hosp_daily":   {"type": "number", "description": "疾病住院日額（元/日），無則填0"},
                        "accident_hosp_daily":  {"type": "number", "description": "意外住院日額（元/日），無則填0"},
                        "inpatient_surgery":    {"type": "number", "description": "住院手術每次給付（元），無則填0"},
                        "outpatient_surgery":   {"type": "number", "description": "門診手術每次給付（元），無則填0"},
                        "specific_treatment":   {"type": "number", "description": "特定處置每次給付（元），無則填0"},
                        "medical_reimburse":    {"type": "number", "description": "醫療實支實付上限（元），無則填0"},
                        "accident_reimburse":   {"type": "number", "description": "意外實支實付上限（元），無則填0"},
                        "deductible":           {"type": "number", "description": "實支實付自負額（元），無則填0"},
                        "disability_monthly":   {"type": "number", "description": "失能月給付（元/月），無則填0"},
                        "long_care_monthly":    {"type": "number", "description": "長照月給付（元/月），無則填0"},
                        "critical_illness":     {"type": "number", "description": "重大疾病或特定傷病一次金（元），無則填0"},
                        "cancer_first":         {"type": "number", "description": "初次罹癌一次金（元），無則填0"},
                        "cancer_hosp_daily":    {"type": "number", "description": "癌症住院日額（元/日），無則填0"},
                        "cancer_surgery":       {"type": "number", "description": "癌症手術每次給付（元），無則填0"},
                        "accident_death":       {"type": "number", "description": "意外身故保額（元），無則填0"},
                        "fracture":             {"type": "number", "description": "骨折保險金（元），無則填0"},
                    }
                }
            }
        }
    }
}


@app.post("/extract-policies")
def extract_policies(req: ExtractRequest, user: dict = Depends(get_current_user)):
    try:
        raw = req.image_base64
        if "," in raw:
            header, data = raw.split(",", 1)
            m = re.search(r"data:([^;]+)", header)
            media_type = m.group(1) if m else "image/jpeg"
        else:
            data, media_type = raw, "image/jpeg"

        response = _anthropic.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8192,
            tools=[_EXTRACT_TOOL],
            tool_choice={"type": "tool", "name": "output_policies"},
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": data}
                    },
                    {
                        "type": "text",
                        "text": (
                            "請從這張圖片中辨識所有保單資訊。圖片可能是：正式保單文件、保險公司系統截圖、保單查詢列表、對帳單等任何形式。\n"
                            "只要能辨識到保單號碼、商品名稱、承保日、保額等任一欄位，就請輸出對應的保單資料。\n"
                            "若圖中有主約＋多張附約，每張各輸出一筆。\n"
                            "保費類型判斷：終身壽險/儲蓄險/養老險 → 平準保費；醫療附約/意外附約/定期附約（年繳費率隨年齡變動）→ 自然保費。\n"
                            "終身判斷：保障至99/100歲或標示「終身」→ is_lifetime=true。\n"
                            "保費欄位：若圖中只有舊的保費數字，仍請填入；若看不到填0。\n"
                            "職業類別：傷害/意外險看到「第N類」請填 occupation_class=N。\n"
                            "計劃別：若保單名後有計劃別（如計劃一/二/三），請一併納入 product_name，如「新住院醫療保險附約計劃二」。\n"
                            "住院費用保險附約：保額欄若顯示「計劃N：日額XXX元」，請將 XXX 填入 coverage_amount（這是每日實支上限）。\n"
                            "細部金額：依圖中記載盡量填入，看不到填0。\n"
                            "請用 output_policies 工具回傳所有找到的保單，找不到任何保單才回傳空陣列。"
                        )
                    }
                ]
            }]
        )

        print(f"[extract] stop_reason={response.stop_reason}, blocks={len(response.content)}")
        log_api_usage("extract-policies", "claude-sonnet-4-6",
                      response.usage.input_tokens, response.usage.output_tokens,
                      int(user["sub"]))
        tool_block = next((b for b in response.content if b.type == "tool_use"), None)
        if not tool_block:
            raise ValueError("Claude 未回傳辨識結果")

        policies = tool_block.input.get("policies", [])
        for p in policies:
            match = lookup_product(p["company"], p["product_name"])
            if match:
                p["premium_type"] = match["product"]["premium_type"]
                p["db_status"]    = "verified"
                p["db_score"]     = match["score"]
            else:
                p["db_status"] = "unverified"
                p["db_score"]  = 0

        return {"policies": policies}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/rate-table")
def get_rate_table(req: RateTableRequest, user: dict = Depends(get_current_user)):
    """查詢保單費率表（優先從快取，否則從 R2 PDF 提取）"""
    try:
        from rate_lookup import get_rate_table
        rates = get_rate_table(req.company, req.product_name, req.gender, req.occupation_class)
        if not rates:
            return {"rates": [], "source": "not_found"}
        return {"rates": rates, "source": "db" if len(rates) > 0 else "not_found"}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/products")
def list_products(user: dict = Depends(get_current_user)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM products ORDER BY company, product_name"
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/products")
def add_product(req: ProductCreate, user: dict = Depends(get_current_user)):
    ok = insert_product(
        req.company, req.product_name, req.insurance_type,
        req.premium_type, req.coverage_end_age, user["username"]
    )
    if not ok:
        raise HTTPException(status_code=400, detail="新增失敗，請重試")
    return {"ok": True}


@app.post("/enrich-policies")
def enrich_policies_endpoint(body: dict, user: dict = Depends(get_current_user)):
    """
    並行讀取所有保單的條款 PDF，提取正確保障細項。
    回傳 enriched policies（含 disease_hosp_daily, medical_reimburse 等欄位）。
    """
    policies_input = body.get("policies", [])
    if not policies_input:
        return {"policies": []}
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(_enrich_one_policy, p) for p in policies_input]
            enriched = [f.result() for f in futures]
        return {"policies": enriched}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/report-product")
def report_product(body: dict, user: dict = Depends(get_current_user)):
    company      = body.get("company", "")
    product_name = body.get("product_name", "")
    note         = body.get("note", "")
    if not company or not product_name:
        raise HTTPException(status_code=400, detail="缺少必填欄位")
    ok = insert_report(company, product_name, user["username"], note)
    if not ok:
        raise HTTPException(status_code=500, detail="回報失敗")
    return {"ok": True}


@app.get("/reports")
def list_reports(user: dict = Depends(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="無權限")
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM product_reports ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/reports/{report_id}/resolve")
def resolve_report(report_id: int, body: dict, user: dict = Depends(get_current_user)):
    """管理員確認回報：加入 products 資料表並標記為已處理。"""
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="無權限")
    with get_db() as conn:
        row = conn.execute("SELECT * FROM product_reports WHERE id=?", (report_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="找不到該回報")

    insurance_type   = body.get("insurance_type", "醫療險")
    premium_type     = body.get("premium_type", "自然保費")
    coverage_end_age = int(body.get("coverage_end_age", 75))

    insert_product(row["company"], row["product_name"], insurance_type,
                   premium_type, coverage_end_age, user["username"])

    with get_db() as conn:
        conn.execute("UPDATE product_reports SET status='done' WHERE id=?", (report_id,))
        conn.commit()
    sync_db_to_r2()
    return {"ok": True}


@app.post("/client-sessions")
def create_session(body: dict, user: dict = Depends(get_current_user)):
    client_name = body.get("client_name", "").strip()
    client_data = body.get("client", {})
    policies    = body.get("policies", [])
    if not client_name:
        raise HTTPException(status_code=400, detail="缺少客戶姓名")
    sid = save_client_session(int(user["sub"]), client_name, client_data, policies)
    return {"id": sid}


@app.get("/client-sessions")
def list_sessions(user: dict = Depends(get_current_user)):
    return list_client_sessions(int(user["sub"]))


@app.get("/client-sessions/{session_id}")
def get_session(session_id: int, user: dict = Depends(get_current_user)):
    s = get_client_session(session_id, int(user["sub"]))
    if not s:
        raise HTTPException(status_code=404, detail="找不到紀錄")
    return s


@app.delete("/client-sessions/{session_id}")
def remove_session(session_id: int, user: dict = Depends(get_current_user)):
    if not delete_client_session(session_id, int(user["sub"])):
        raise HTTPException(status_code=404, detail="找不到紀錄")
    return {"ok": True}


@app.post("/download-pptx")
def download_pptx(req: PptxRequest, user: dict = Depends(get_current_user)):
    try:
        pptx_bytes = generate_pptx(req.client, req.policies, req.advisor, req.analysis)
        filename = f"insurance_analysis_{req.client.name}.pptx"
        return Response(
            content=pptx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# 前端 SPA catch-all（所有非 API 路由回傳 index.html）
@app.get("/{full_path:path}")
def serve_frontend(full_path: str):
    if FRONTEND_DIST.exists():
        index = FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(index)
    return {"message": "frontend not built"}
