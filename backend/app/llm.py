import logging
from typing import Any

import httpx

from app.config import settings
from app.tools import TOOL_DEFINITIONS

logger = logging.getLogger(__name__)


class LLMError(Exception):
    pass


async def chat_completion(messages: list[dict[str, Any]]) -> dict[str, Any]:
    url = f"{settings.llm_base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "tools": TOOL_DEFINITIONS,
        "tool_choice": "auto",
        "temperature": 0.2,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.exception("LLM provider request failed")
        raise LLMError("大模型服务暂时不可用，请检查 API 配置或稍后重试。") from exc
    try:
        message = result["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        logger.error("LLM provider returned an unexpected response shape")
        raise LLMError("大模型返回了无法识别的响应，请稍后重试。") from exc
    if not isinstance(message, dict):
        logger.error("LLM provider message is not an object")
        raise LLMError("大模型返回了无法识别的响应，请稍后重试。")
    return message
