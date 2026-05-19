"""日志统一配置

输出两个文件：
- tmp/log/app.log          — 标准日志（INFO 及以上）
- tmp/log/app_detail.log   — 超详细日志（DEBUG，含完整 JSON 请求/响应）"""

import sys
from pathlib import Path
from loguru import logger

# 移除默认 handler
logger.remove()

_log_dir = Path(__file__).parent.parent.parent / "log"
_log_dir.mkdir(parents=True, exist_ok=True)

# === 标准日志：核心流程（INFO 及以上）===
logger.add(
    _log_dir / "app.log",
    rotation="00:00", retention="7 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
    encoding="utf-8",
)

# === 详细日志：中间数据、重试、API 交互（DEBUG）===
logger.add(
    _log_dir / "app_detail.log",
    rotation="00:00", retention="7 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
    encoding="utf-8",
)

# === 终端日志 ===
logger.add(
    sys.stderr,
    level="DEBUG",
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    colorize=True,
)
