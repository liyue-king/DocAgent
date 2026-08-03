"""
====================================================================
文件用途：planner —— 排版规划节点（确定性快路径 + LLM 增量路径）
====================================================================
作用：
    生成原子操作队列 task_queue。双路径设计（蓝图 6.2）：
    - 确定性快路径：纯模板匹配，按模板 config 对 DOM 段落分组生成指令，
      0 token、<1s、planner_mode="deterministic"；
    - LLM 增量路径：检测到用户个性化需求（或 EntryGuard 强制切换）时，
      在确定性队列基础上调用 LLM 生成少量"增量/覆盖"指令（~200 tokens），
      temperature=0，失败自动回退确定性结果；
    - 重试增量修补：Validator 返回 missed 后，仅针对未达标段落、未达标
      维度生成修补指令（非全量重规划），planner_llm_calls 不再增加。
依赖：
    - app.services.llm.chat_json（DeepSeek 客户端，延迟调用）
    - app.agents.nodes._common（notify）
====================================================================
"""

from __future__ import annotations

import json  # 序列化提示词
import logging  # 标准库日志
from typing import Any  # 泛型类型

from app.agents.nodes._common import notify  # 日志 + 持久化
from app.models import LogLevel, TaskStatus  # 枚举

logger = logging.getLogger(__name__)  # 模块级日志器
NODE_NAME = "planner"  # 节点名

# action 白名单（与 entry_guard 保持一致，防止 LLM 输出越权指令）
ACTION_WHITELIST = {
    "set_font",
    "set_font_size",
    "set_bold",
    "set_italic",
    "set_line_spacing",
    "set_paragraph_space",
}

# 个性化需求关键词：命中任意一个即认为用户要求覆盖模板默认样式 → LLM 增量路径
_PERSONALIZATION_KEYWORDS = (
    "不要加粗",
    "不要粗",
    "改成",
    "改为",
    "换成",
    "调成",
    "调整",
    "修改",
    "设置",
    "字号",
    "字体",
    "楷体",
    "仿宋",
    "黑体",
    "宋体",
    "加粗",
    "斜体",
    "行距",
    "间距",
    "缩进",
    "小四",
    "四号",
    "五号",
    "三号",
    "小二",
    "二号",
)


def _op_set_font(pid: int, cfg: dict[str, Any]) -> dict[str, Any]:
    return {"action": "set_font", "para_ids": [pid], "font": cfg["font_name"]}


def _op_set_font_size(pid: int, cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": "set_font_size",
        "para_ids": [pid],
        "size_pt": cfg["font_size_pt"],
    }


def _op_set_bold(pid: int, cfg: dict[str, Any]) -> dict[str, Any]:
    return {"action": "set_bold", "para_ids": [pid], "bold": cfg.get("bold", False)}


def _op_set_line_spacing(pid: int, cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": "set_line_spacing",
        "para_ids": [pid],
        "rule": cfg.get("line_spacing_rule", "MULTIPLE"),
        "value": cfg.get("line_spacing_value"),
    }


def _op_set_paragraph_space(pid: int, cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": "set_paragraph_space",
        "para_ids": [pid],
        "space_before_pt": cfg.get("space_before_pt", 0),
        "space_after_pt": cfg.get("space_after_pt", 0),
    }


# 校验维度 → 指令构造器映射（重试增量修补用）
_DIM_OP_BUILDERS: dict[str, Any] = {
    "font": _op_set_font,
    "font_size": _op_set_font_size,
    "bold": _op_set_bold,
    "line_spacing": _op_set_line_spacing,
    "paragraph_space": _op_set_paragraph_space,
}


def _needs_llm(prompt: str) -> bool:
    """判断用户提示词是否含个性化需求（命中关键词即走 LLM 增量路径）。"""
    if not prompt:
        return False
    return any(kw in prompt for kw in _PERSONALIZATION_KEYWORDS)


def build_style_ops(
    template_config: dict[str, Any], doc_dom_serial: dict[str, Any]
) -> list[dict[str, Any]]:
    """确定性快路径：按模板 config 对 DOM 段落按样式分组生成原子指令。

    :param template_config: 模板 config（含 paragraph_styles）
    :param doc_dom_serial: 可序列化 DOM（段落 id/style）
    :return: 原子指令队列
    """
    styles = template_config.get("paragraph_styles", {})
    # 按样式分组段落 id
    style_group: dict[str, list[int]] = {}
    for p in doc_dom_serial.get("paragraphs", []):
        s = p.get("style", "other")
        if s in ("heading_1", "heading_2", "heading_3", "normal"):
            style_group.setdefault(s, []).append(p["id"])

    ops: list[dict[str, Any]] = []
    for style_key, para_ids in style_group.items():
        cfg = styles.get(style_key)
        if not cfg:
            continue  # 模板未定义该样式，跳过
        # 五个维度整组指令（para_ids 为整组）
        ops.append(
            {"action": "set_font", "para_ids": para_ids, "font": cfg["font_name"]}
        )
        ops.append(
            {
                "action": "set_font_size",
                "para_ids": para_ids,
                "size_pt": cfg["font_size_pt"],
            }
        )
        ops.append(
            {"action": "set_bold", "para_ids": para_ids, "bold": cfg.get("bold", False)}
        )
        ops.append(
            {
                "action": "set_line_spacing",
                "para_ids": para_ids,
                "rule": cfg.get("line_spacing_rule", "MULTIPLE"),
                "value": cfg.get("line_spacing_value"),
            }
        )
        ops.append(
            {
                "action": "set_paragraph_space",
                "para_ids": para_ids,
                "space_before_pt": cfg.get("space_before_pt", 0),
                "space_after_pt": cfg.get("space_after_pt", 0),
            }
        )
    return ops


def build_missed_patch_ops(
    template_config: dict[str, Any], validation_report: dict[str, Any]
) -> list[dict[str, Any]]:
    """重试增量修补：仅针对 missed 段落的未达标维度生成指令。

    :param template_config: 模板 config
    :param validation_report: Validator 输出（missed 含 para_id/style/reason）
    :return: 增量修补指令队列（空列表表示无遗漏）
    """
    styles = template_config.get("paragraph_styles", {})
    ops: list[dict[str, Any]] = []
    for miss in validation_report.get("missed", []):
        para_id = miss.get("para_id")
        style = miss.get("style")
        cfg = styles.get(style)
        if para_id is None or not cfg:
            continue  # 样式未定义或无段号，跳过
        # reason 形如 "font,line_spacing"，逐维度生成对应修补指令
        dims = [
            d.strip() for d in (miss.get("reason") or "font").split(",") if d.strip()
        ]
        for dim in dims:
            builder = _DIM_OP_BUILDERS.get(dim)
            if builder:
                ops.append(builder(para_id, cfg))
    return ops


def _llm_augment(
    template_config: dict[str, Any],
    doc_dom_serial: dict[str, Any],
    prompt: str,
    base_queue: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """LLM 增量路径：在基础队列上生成增量/覆盖指令。

    :param template_config: 模板 config
    :param doc_dom_serial: 文档段落摘要
    :param prompt: 用户需求
    :param base_queue: 确定性基础队列
    :return: (增量指令列表, 本次消耗 token 数)；LLM 失败返回 ([], 0)
    """
    system_prompt = (
        "你是文档排版规划助手。根据模板配置、文档段落结构与用户需求，"
        "输出额外或覆盖的原子排版指令。要求：仅输出 JSON 数组，"
        '每个元素形如 {"action":"set_font","para_ids":[0],"font":"楷体"}。'
        "action 必须是 set_font/set_font_size/set_bold/set_italic/"
        "set_line_spacing/set_paragraph_space 之一。若无额外需求输出 []。"
    )
    # 段落摘要：id / style / 文本前 30 字，避免超长
    summary = [
        {"id": p["id"], "style": p.get("style"), "text": (p.get("text") or "")[:30]}
        for p in doc_dom_serial.get("paragraphs", [])[:200]
    ]
    user_prompt = (
        f"模板配置：{json.dumps(template_config, ensure_ascii=False)}\n"
        f"文档段落摘要：{json.dumps(summary, ensure_ascii=False)}\n"
        f"用户需求：{prompt}\n"
        f"已有指令队列：{json.dumps(base_queue, ensure_ascii=False)}\n"
        "请针对用户个性化需求，输出增量/覆盖指令 JSON 数组。"
    )
    try:
        from app.services.llm import chat_json  # 延迟导入（Key 未配置时抛异常）

        resp = chat_json(system_prompt, user_prompt, temperature=0.0, max_retries=1)
        data = resp["data"]
        tokens = resp["total_tokens"]
    except Exception as exc:  # LLM 不可用 / 解析失败 → 回退确定性队列
        logger.warning("[planner] LLM 增量路径失败，回退确定性队列: %s", exc)
        return [], 0

    if not isinstance(data, list):  # LLM 未按约定输出数组
        return [], tokens
    # 白名单过滤 + 必填字段校验，非法指令丢弃（entry_guard 二次兜底）
    extra: list[dict[str, Any]] = []
    for op in data:
        if not isinstance(op, dict):
            continue
        if op.get("action") not in ACTION_WHITELIST:
            continue
        if not isinstance(op.get("para_ids"), list) or not op["para_ids"]:
            continue
        extra.append(op)
    return extra, tokens


def planner_node(state: dict[str, Any]) -> dict[str, Any]:
    """规划节点：双路径生成 task_queue（含重试增量修补）。

    :param state: 当前状态（含模板配置 / doc_dom_serial / 用户需求 / 校验报告）
    :return: 状态更新（task_queue / planner_mode / token 统计 / agent_logs / status）
    """
    template_config = state.get("selected_template_config") or {}
    doc_dom_serial = state.get("doc_dom_serial") or {"paragraphs": []}
    user_prompt = state.get("user_prompt", "")
    validation_report = state.get("validation_report") or {}
    retry_count = state.get("retry_count", 0)
    planner_mode = state.get("planner_mode", "deterministic")

    updates: dict[str, Any] = {}
    extra_ops: list[dict[str, Any]] = []
    used_tokens = 0
    llm_calls = state.get("planner_llm_calls", 0)

    # ---- 分支 1：重试增量修补（仅针对 missed 段落）----
    if retry_count > 0 and validation_report.get("missed"):
        task_queue = build_missed_patch_ops(template_config, validation_report)
        logs = notify(
            state,
            f"校验未通过，重试第 {retry_count} 次：仅对 {len(validation_report.get('missed', []))} "
            f"个未达标段落增量修补，生成 {len(task_queue)} 条指令",
            NODE_NAME,
            level=LogLevel.WARNING,
            status=TaskStatus.PLANNING,
            progress=45,
            step=f"增量修补(第{retry_count}次)",
        )
    # ---- 分支 2：首轮规划（确定性 / LLM 增量）----
    else:
        base_queue = build_style_ops(template_config, doc_dom_serial)  # 确定性快路径
        # 个性化需求 或 EntryGuard 强制切换 → LLM 增量
        if _needs_llm(user_prompt) or planner_mode == "llm_augmented":
            extra_ops, used_tokens = _llm_augment(
                template_config, doc_dom_serial, user_prompt, base_queue
            )
            llm_calls = llm_calls + 1  # 计入本次 LLM 调用（含失败尝试）
            mode = "llm_augmented"
            log_msg = (
                f"规划完成（LLM 增量路径）：基础 {len(base_queue)} 条 + 个性化增量 {len(extra_ops)} 条，"
                f"共 {len(base_queue) + len(extra_ops)} 条原子指令"
            )
        else:
            mode = "deterministic"
            log_msg = (
                f"规划完成（确定性快路径）：生成 {len(base_queue)} 条原子指令，0 token"
            )
        task_queue = base_queue + extra_ops  # 合并
        logs = notify(
            state,
            log_msg,
            NODE_NAME,
            level=LogLevel.INFO,
            status=TaskStatus.PLANNING,
            progress=45,
            step="生成排版指令队列",
        )

    updates["task_queue"] = task_queue
    updates["planner_mode"] = (
        mode if retry_count == 0 else planner_mode
    )  # 修补轮不改变路径标识
    updates["planner_llm_calls"] = llm_calls
    updates["llm_total_tokens"] = state.get("llm_total_tokens", 0) + used_tokens
    updates["agent_logs"] = logs
    updates["status"] = "planning"
    return updates
