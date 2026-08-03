"""
====================================================================
文件用途：LLM 客户端（DeepSeek / OpenAI 兼容 Chat Completions）
====================================================================
作用：
    供 Planner 的 LLM 增量路径调用，输出结构化 JSON 原子指令。
    使用 httpx 直连 Chat Completions 接口（不依赖 openai SDK），
    统一处理：JSON 解析（兼容 markdown 代码块）、失败重试、token 统计。
依赖：
    - httpx（已安装）
    - app.config.settings（provider / api_key / base_url / model）
调用方：
    - app/agents/nodes/planner.py（LLM 增量路径 / EntryGuard 兜底切换）
说明：
    - LLM 调用失败（无 Key / 网络异常 / 返回非法 JSON）时抛出
      LlmUnavailable，由 Planner 回退到确定性结果，保证流程不中断。
    - 单次调用 token 数随返回结构一并给出，供成本核算（≤￥0.05/文档）。
====================================================================
"""

from __future__ import annotations

import json  # 解析 LLM 返回 JSON
import logging  # 标准库日志
import re  # 提取 markdown 代码块
from typing import Any  # 泛型类型

import httpx  # HTTP 客户端（同步模式）

from app.config import settings  # LLM 配置

logger = logging.getLogger(__name__)  # 模块级日志器


class LlmUnavailable(Exception):
    """LLM 服务不可用（无 Key / 网络异常 / 配额不足）时抛出。"""


def _resolve_config() -> tuple[str, str, str]:
    """按 provider 解析 (api_key, base_url, model)。

    :raises LlmUnavailable: provider 未配置或对应 Key 为空
    """
    provider = (settings.llm_provider or "deepseek").lower()
    if provider == "openai":
        api_key = settings.openai_api_key
        base_url = settings.openai_base_url
        model = settings.llm_model or "gpt-4o-mini"
    else:  # deepseek（默认）
        api_key = settings.deepseek_api_key
        base_url = settings.deepseek_base_url
        model = settings.llm_model or "deepseek-chat"
    if not api_key:
        raise LlmUnavailable("未配置 LLM API Key，请检查 .env")
    return api_key, base_url, model


def _extract_json(raw: str) -> Any:
    """从 LLM 返回文本中提取 JSON（兼容 markdown ```json 代码块）。

    :param raw: LLM 原始返回文本
    :return: 解析后的 Python 对象
    :raises ValueError: 无法提取到合法 JSON
    """
    text = raw.strip()
    # 去除 markdown 代码块围栏（```json ... ```）
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    # 尝试直接解析；失败则截取第一个 [ 到最后一个 ]（JSON 数组）
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise  # 兜底：重新抛出原解析错误


def chat_json(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.0,
    max_retries: int = 1,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """调用 LLM 并解析返回的 JSON。

    :param system_prompt: 系统提示词（限定输出 JSON 结构）
    :param user_prompt: 用户提示词（模板配置 + DOM 摘要 + 需求）
    :param temperature: 采样温度，规划类任务固定 0（确定性）
    :param max_retries: 失败重试次数（默认 1 次）
    :param timeout: 单次请求超时（秒）
    :return: {"data": <解析后的 JSON>, "total_tokens": int, "model": str}
    :raises LlmUnavailable: 多次重试仍失败
    """
    api_key, base_url, model = _resolve_config()
    url = f"{base_url.rstrip('/')}/chat/completions"  # POST 端点
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "stream": False,
    }

    last_err: Exception | None = None
    for attempt in range(max_retries + 1):  # 首次 + max_retries 次重试
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()  # 非 2xx 抛异常（含 429 限流 / 400 参数错误）
            body = resp.json()
            content = body["choices"][0]["message"]["content"]  # LLM 文本
            usage = body.get("usage", {})  # token 统计
            data = _extract_json(content)  # 解析 JSON
            return {
                "data": data,
                "total_tokens": int(usage.get("total_tokens", 0)),
                "model": model,
            }
        except Exception as exc:  # 网络 / 状态码 / JSON 解析失败均重试
            last_err = exc
            logger.warning("LLM 调用失败（第 %d 次）: %s", attempt + 1, exc)
            if attempt < max_retries:
                continue
    raise LlmUnavailable(f"LLM 多次调用失败: {last_err}") from last_err
