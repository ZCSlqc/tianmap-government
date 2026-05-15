"""Hermes Agent 调用封装

API 调用模块，所有网络请求统一在此处理。"""

import asyncio
import aiohttp
import os
import requests
from typing import Any
from dotenv import load_dotenv
from loguru import logger
from pathlib import Path

_env_path = Path(__file__).resolve().parent.parent / ".." / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

HERMES_HOST = os.getenv("HERMES_HOST", "0.0.0.0")
HERMES_PORT = os.getenv("HERMES_PORT", "8643")
HERMES_KEY = os.getenv("HERMES_KEY", "12345678")

BASE_URL = f"http://{HERMES_HOST}:{HERMES_PORT}/v1/chat/completions"
HEALTH_URL = f"http://{HERMES_HOST}:{HERMES_PORT}/health"


async def _health_once() -> bool:
    """单次健康检查"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(HEALTH_URL, timeout=aiohttp.ClientTimeout(total=5)) as r:
                ok = r.status == 200 and (await r.json()).get("status") == "ok"
                if not ok:
                    logger.warning("[Hermes] API 健康检查失败")
                return ok
    except Exception:
        logger.error("[Hermes] 连接失败")
        return False


def health() -> bool:
    """同步健康检查（兼容旧调用）"""
    try:
        r = requests.get(HEALTH_URL, timeout=5)
        ok = r.status_code == 200 and r.json().get("status") == "ok"
        if not ok:
            logger.warning("[Hermes] API 健康检查失败")
        return ok
    except Exception as e:
        logger.error(f"[Hermes] 连接失败: {e}")
        return False


async def _chat_once(messages: list[dict], session_id: str = "",
                     max_tokens: int = 1024) -> str | None:
    """单次 Agent 请求"""
    if not await _health_once():
        logger.error("[Hermes] Agent 不可用，跳过请求")
        return None

    payload: dict[str, Any] = {"model": "", "messages": messages, "max_tokens": max_tokens}
    if session_id:
        payload["session_id"] = session_id
    headers = {"Authorization": f"Bearer {HERMES_KEY}", "Content-Type": "application/json"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                BASE_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=120),
            ) as r:
                r.raise_for_status()
                result = await r.json()
                return result["choices"][0]["message"]["content"]
    except asyncio.TimeoutError:
        logger.error("[Hermes] 请求超时")
        return None
    except aiohttp.ClientError as e:
        logger.error(f"[Hermes] 请求异常: {e}")
        return None
    except (KeyError, IndexError) as e:
        logger.error(f"[Hermes] 响应解析失败: {e}")
        return None


async def chat(messages: list[dict], session_id: str = "", max_tokens: int = 1024,
               retries: int = 3) -> str | None:
    """Agent 请求，重试 _AMAP_MAX_RETRIES 次"""
    for attempt in range(1, retries + 1):
        result = await _chat_once(messages, session_id, max_tokens)
        if result:
            return result
        logger.warning(f"[Hermes] 第 {attempt} 次返回为空")
        if attempt < retries:
            await asyncio.sleep(0.5 * attempt)
    return None
