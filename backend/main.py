import re
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

import anthropic
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from models import AnalysisRequest, PptxRequest, LoginRequest, UserCreate, ExtractRequest, ProductCreate, SetExpiry

_anthropic = anthropic.Anthropic()
from analyzer import analyze_coverage
from pptx_generator import generate_pptx
from database import get_db, init_db, lookup_product, insert_product
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


@app.post("/analyze")
def analyze(req: AnalysisRequest, user: dict = Depends(get_current_user)):
    try:
        result = analyze_coverage(req.client, req.policies)
        with get_db() as conn:
            conn.execute(
                "INSERT INTO analysis_logs (user_id, client_name) VALUES (?,?)",
                (int(user["sub"]), req.client.name)
            )
            conn.commit()
        return result
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


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
                        "company":         {"type": "string"},
                        "insurance_type":  {"type": "string", "enum": ["壽險","醫療險","癌症險","意外險","失能險","長照險","儲蓄險"]},
                        "product_name":    {"type": "string"},
                        "coverage_amount": {"type": "number", "description": "保障金額（元），無法辨識填0"},
                        "annual_premium":  {"type": "number", "description": "年繳保費（元），月繳請乘12，無法辨識填0"},
                        "premium_type":    {"type": "string", "enum": ["自然保費","平準保費"]},
                        "coverage_end_age":{"type": "integer", "description": "保障終止年齡，無法辨識填75"},
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
            max_tokens=2048,
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
                            "請從這份保單文件中辨識所有保單資訊。\n"
                            "保費類型判斷原則：文件上有寫「自然保費」、或是醫療/意外附約（費率隨年齡增加）→ 填「自然保費」；"
                            "主約或儲蓄型（保費固定）→ 填「平準保費」。\n"
                            "請用 output_policies 工具回傳所有找到的保單，找不到任何保單則回傳空陣列。"
                        )
                    }
                ]
            }]
        )

        tool_block = next((b for b in response.content if b.type == "tool_use"), None)
        if not tool_block:
            raise ValueError("Claude 未回傳辨識結果")

        policies = tool_block.input["policies"]
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
