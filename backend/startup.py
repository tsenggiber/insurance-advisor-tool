"""
啟動前執行：從 R2 下載 tii_scraper.db 與 app.db（若本地不存在）。
"""
import os
import sys
from pathlib import Path

R2_ACCOUNT_ID = "56279c540b6e49a298a89749be5f996b"
R2_ACCESS_KEY = "32602fa20182a65f4388be8457df62bc"
R2_SECRET_KEY = "de21f16d0ab5873cc0e77f548cfc06e323a51ecbb5b8d74fa9c879dfe13f83ca"
R2_BUCKET     = "tii-policies"

_DEFAULT_TII_DB = str(Path(__file__).parent.parent / "tii_scraper.db")
TII_DB_PATH = os.environ.get("TII_DB_PATH", _DEFAULT_TII_DB)

_DEFAULT_APP_DB = str(Path(__file__).parent / "app.db")
APP_DB_PATH = os.environ.get("DB_PATH", _DEFAULT_APP_DB)


def get_r2():
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY,
        aws_secret_access_key=R2_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def download_if_missing(r2, r2_key: str, local_path: str):
    if Path(local_path).exists():
        size = Path(local_path).stat().st_size
        print(f"[startup] {r2_key} already exists ({size:,} bytes)")
        return
    print(f"[startup] Downloading {r2_key} → {local_path} ...")
    try:
        r2.download_file(R2_BUCKET, r2_key, local_path)
        size = Path(local_path).stat().st_size
        print(f"[startup] Downloaded {r2_key} ({size:,} bytes)")
    except Exception as e:
        err = str(e)
        if "NoSuchKey" in err or "404" in err:
            print(f"[startup] {r2_key} not in R2 yet, will be created fresh")
        else:
            print(f"[startup] WARNING: Failed to download {r2_key}: {e}", file=sys.stderr)


try:
    r2 = get_r2()
    download_if_missing(r2, "tii_scraper.db", TII_DB_PATH)
    download_if_missing(r2, "app.db", APP_DB_PATH)
except Exception as e:
    print(f"[startup] WARNING: R2 connection failed: {e}", file=sys.stderr)
