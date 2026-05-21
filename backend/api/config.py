"""统一配置，从 .env 加载，所有模块共享。"""

import os
from pathlib import Path
from dotenv import load_dotenv

_loaded = False
if not _loaded:
    _env_path = Path(__file__).resolve().parent.parent / ".." / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
    _loaded = True

# AMap
AMAP_KEY: str = os.getenv("AMAP_KEY", "")
AMAP_RADIUS: int = int(os.getenv("AMAP_RADIUS", 2000))
AMAP_MAX_RETRIES: int = int(os.getenv("AMAP_MAX_RETRIES", 3))

# Hermes
HERMES_HOST: str = os.getenv("HERMES_HOST", "0.0.0.0")
HERMES_PORT: int = int(os.getenv("HERMES_PORT", "8643"))
HERMES_KEY: str = os.getenv("HERMES_KEY", "12345678")
HERMES_MAX_RETRIES: int = int(os.getenv("HERMES_MAX_RETRIES", 3))
HERMES_MAX_TOKENS: int = int(os.getenv("HERMES_MAX_TOKENS", 1024))
