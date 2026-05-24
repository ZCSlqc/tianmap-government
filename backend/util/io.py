"""通用 IO 工具"""

import json
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Union

from backend.util.log import logger as app_logger


def _tmp_dir() -> Path:
    return Path(__file__).parent.parent.parent / "tmp"


def _safe_name(name: Union[str, list[str], list[int]]) -> str:
    """安全化 name：只保留字母数字和 ._-，截断 50 字符，list 用 _ 衔接。"""
    parts = [str(name)] if isinstance(name, str) else [str(x) for x in name]
    safe = []
    for p in parts:
        p = "".join(c for c in p if c.isalnum() or c in "._-")[:50]
        if p:
            safe.append(p)
    return "_".join(safe)


async def save_json(
    name: Union[str, list[str], list[int]],
    data: Any,
    subdir: str = "",
    silent: bool = False,
) -> Path:
    """保存 JSON 数据到 tmp/ 目录（异步）。

    Args:
        name: 文件名（不含扩展名），支持 str 或 list[str/int]，会自动加时间戳和安全化处理
        data: 要序列化的数据
        subdir: 子目录（如 "amap"、"raw_url"），为空时放在 tmp/ 根目录
        silent: 是否不输出路径日志
    """
    show = app_logger.debug if not silent else lambda *_, **__: None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = _safe_name(name)
    filename = f"{ts}_{safe}.json"
    out_dir = _tmp_dir()
    if subdir:
        out_dir = out_dir / subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    content = json.dumps(data, ensure_ascii=False, indent=2)
    await asyncio.to_thread(path.write_text, content, encoding="utf-8")
    show(f"[保存] {path}")
    return path
