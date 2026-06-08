"""
啟動前執行：若 /data/tii_scraper.db 不存在，從 R2 下載。
"""
import os
import sys
from pathlib import Path

TII_DB_PATH = os.environ.get("TII_DB_PATH", "")

if not TII_DB_PATH:
    print("[startup] TII_DB_PATH not set, skipping download")
    sys.exit(0)

if Path(TII_DB_PATH).exists():
    size = Path(TII_DB_PATH).stat().st_size
    print(f"[startup] tii_scraper.db already exists ({size:,} bytes)")
    sys.exit(0)

print(f"[startup] Downloading tii_scraper.db → {TII_DB_PATH} ...")

try:
    import boto3
    from botocore.config import Config

    R2_ACCOUNT_ID = "56279c540b6e49a298a89749be5f996b"
    R2_ACCESS_KEY = "32602fa20182a65f4388be8457df62bc"
    R2_SECRET_KEY = "de21f16d0ab5873cc0e77f548cfc06e323a51ecbb5b8d74fa9c879dfe13f83ca"

    r2 = boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY,
        aws_secret_access_key=R2_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )
    r2.download_file("tii-policies", "tii_scraper.db", TII_DB_PATH)
    size = Path(TII_DB_PATH).stat().st_size
    print(f"[startup] Downloaded successfully ({size:,} bytes)")
except Exception as e:
    print(f"[startup] WARNING: Failed to download tii_scraper.db: {e}", file=sys.stderr)
    # 不中斷啟動 — 沒有 tii 資料仍可使用基本功能
