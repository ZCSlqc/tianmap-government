"""JSON 工具"""

import json
from typing import Any
from loguru import logger


def parse_json(text: str) -> dict | list | None:
    """从文本中提取第一个 JSON 对象/数组"""
    start = text.find("{")
    end = text.rfind("}")
    if start < 0:
        start = text.find("[")
        end = text.rfind("]")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 解析失败: {e}, 内容: {text[:200]}")
            return None
    logger.warning(f"未找到 JSON 对象: {text[:100]}")
    return None
