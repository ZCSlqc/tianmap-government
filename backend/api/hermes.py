"""Hermes Agent 调用封装

API 调用模块，所有网络请求统一在此处理。"""

import asyncio
import aiohttp
from typing import Any
from loguru import logger

from backend.api.config import HERMES_HOST, HERMES_PORT, HERMES_KEY, HERMES_MAX_RETRIES, HERMES_MAX_TOKENS

BASE_URL = f"http://{HERMES_HOST}:{HERMES_PORT}/v1/chat/completions"
HEALTH_URL = f"http://{HERMES_HOST}:{HERMES_PORT}/health"


async def health() -> bool:
    """Hermes 健康检查"""
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


async def _chat_once(messages: list[dict], session_id: str = "",
                     max_tokens: int | None = None) -> str | None:
    """单次 Agent 请求"""
    if max_tokens is None:
        max_tokens = HERMES_MAX_TOKENS
    if not await health():
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


async def chat(messages: list[dict], session_id: str = "", max_tokens: int | None = None,
               retries: int | None = None) -> str | None:
    """Agent 请求，重试 retries 次"""
    for _ in range(retries if retries is not None else HERMES_MAX_RETRIES):
        result = await _chat_once(messages, session_id, max_tokens)
        if result:
            return result
        logger.warning("[Hermes] 返回为空，重试")
        await asyncio.sleep(0.5)
    return None


async def chat_return_json(messages: list[dict], session_id: str = "", max_tokens: int | None = None,
                           retries: int | None = None) -> dict | None:
    """Agent 请求 + 提取 JSON，网络失败重试 chat，解析失败重试"""
    import json

    for _ in range(retries if retries is not None else HERMES_MAX_RETRIES):
        text = await _chat_once(messages, session_id, max_tokens)
        if not text:
            continue
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            logger.debug("[Hermes] 响应中未找到 JSON 对象")
            continue
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError as e:
            logger.debug(f"[Hermes] JSON 解析失败: {e}")
            continue

    logger.debug("[Hermes] JSON 提取全部失败")
    return None
