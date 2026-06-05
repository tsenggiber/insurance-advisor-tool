import hashlib
import os
import jwt
from datetime import datetime, timedelta, timezone

SECRET_KEY = os.environ.get("JWT_SECRET", "please-change-this-secret")
ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 7


def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        salt, dk_hex = password_hash.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
        return dk.hex() == dk_hex
    except Exception:
        return False


def create_token(user_id: int, username: str, is_admin: bool) -> str:
    payload = {
        "sub": str(user_id),
        "username": username,
        "is_admin": is_admin,
        "exp": datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRE_DAYS)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
