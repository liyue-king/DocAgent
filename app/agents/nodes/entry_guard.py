"""
====================================================================
文件用途：entry_guard —— Planner 输出合法性校验节点（v5.2 验证关口）
====================================================================
作用：
    逐条校验 task_queue：action 是否在白名单、para_ids 是否非空且不越界、
    必填字段是否齐全。校验失败时的强制兜底（蓝图 9 容错矩阵）：
    - 若 Planner 处于确定性路径 → 自动切换到 LLM 路径重试 1 次（回跳 planner）；
    - 若已为 LLM 路径 → 保留原格式直通（不再硬编码改动全部段落，
      避免破坏用户不需要改动的格式；原样输出 + 警告日志）。
依赖：
    - app.agents.nodes.planner.ACTION_WHITELIST（白名单唯一来源）
    - app.agents.nodes._common（notify）
====================================================================
"""

from __future__ import annotations

from typing import Any  # 泛型类型

from app.agents.nodes._common import notify  # 日志 + 持久化
from app.agents.nodes.planner import ACTION_WHITELIST  # 复用 planner 白名单
from app.models import LogLevel, TaskStatus  # 枚举

NODE_NAME = "entry_guard"  # 节点名

# 各 action 必填字段（字段缺失即判非法）
_REQUIRED_FIELDS: dict[str, set[str]] = {
    "set_font": {"font"},
    "set_font_size": {"size_pt"},
    "set_bold": {"bold"},
    "set_italic": {"italic"},
    "set_line_spacing": {"rule"},
    "set_paragraph_space": {"space_before_pt", "space_after_pt"},
}


def validate_queue(
    task_queue: list[dict[str, Any]], paragraph_count: int
) -> tuple[bool, list[str]]:
    """校验指令队列合法性。

    :param task_queue: Planner 输出的原子指令队列
    :param paragraph_count: 文档段落总数（para_ids 越界判定；0 表示未知）
    :return: (是否全部合法, 错误列表)
    """
    errors: list[str] = []
    if not isinstance(task_queue, list) or not task_queue:
        return False, ["任务队列为空"]
    for op in task_queue:
        if not isinstance(op, dict):
            errors.append(f"指令非字典对象: {op}")
            continue
        action = op.get("action")
        if action not in ACTION_WHITELIST:
            errors.append(f"action 不在白名单内: {action}")
        # para_ids 非空且不越界
        para_ids = op.get("para_ids")
        if not isinstance(para_ids, list) or not para_ids:
            errors.append(f"[{action}] para_ids 为空或非列表")
        else:
            for pid in para_ids:
                if not isinstance(pid, int) or isinstance(pid, bool):
                    errors.append(f"[{action}] para_id 非法: {pid}")
                elif paragraph_count and (pid < 0 or pid >= paragraph_count):
                    errors.append(f"[{action}] para_id 越界: {pid}")
        # 必填字段
        for field in _REQUIRED_FIELDS.get(action, set()):
            if field not in op or op[field] is None:
                errors.append(f"[{action}] 必填字段缺失: {field}")
    return (not errors), errors


def entry_guard_node(state: dict[str, Any]) -> dict[str, Any]:
    """校验节点：拦截非法指令并执行兜底切换。

    :param state: 当前状态（含 task_queue / doc_dom_serial / planner_mode）
    :return: 状态更新；status="executing"→进入 executor，status="planning"→回跳 planner
    """
    task_queue = state.get("task_queue") or []
    paragraph_count = (state.get("doc_dom_serial") or {}).get("paragraph_count", 0)
    updates: dict[str, Any] = {}

    valid, errors = validate_queue(task_queue, paragraph_count)
    if valid:
        logs = notify(
            state,
            f"任务队列校验通过（{len(task_queue)} 条指令），开始执行",
            NODE_NAME,
            level=LogLevel.INFO,
            status=TaskStatus.EXECUTING,
            progress=60,
            step="开始执行样式修改",
        )
        updates.update({"agent_logs": logs, "status": "executing", "error_message": ""})
        return updates

    # ---- 非法指令：兜底策略 ----
    detail = "；".join(errors[:5])
    planner_mode = state.get("planner_mode", "deterministic")
    replans = state.get("entry_guard_replans", 0)

    if planner_mode == "deterministic" and replans == 0:
        # 确定性路径 → 切换 LLM 路径重规划 1 次
        logs = notify(
            state,
            f"规划输出非法（{detail}），自动切换 LLM 路径重规划",
            NODE_NAME,
            level=LogLevel.ERROR,
            status=TaskStatus.PLANNING,
            progress=45,
            step="规划异常，切换LLM重试",
        )
        updates.update(
            {
                "agent_logs": logs,
                "planner_mode": "llm_augmented",  # 强制走 LLM 增量路径
                "entry_guard_replans": 1,  # 防无限循环
                "status": "planning",
                "error_message": f"规划输出非法：{detail}",
            }
        )
    else:
        # 已为 LLM 路径（或已重规划过）→ 保留原格式直通：空队列让 executor
        # 原样保存输出，不再强制改动全部段落（硬编码全改会破坏用户不需要
        # 改动的格式）。entry_guard_fallback 标记供前端提示"未做修改"。
        logs = notify(
            state,
            f"规划输出非法（{detail}），已保留原格式直通输出（未做任何样式修改）",
            NODE_NAME,
            level=LogLevel.WARNING,
            status=TaskStatus.EXECUTING,
            progress=60,
            step="保留原格式",
        )
        updates.update(
            {
                "agent_logs": logs,
                "task_queue": [],  # 空队列 → executor 原样保存
                "entry_guard_fallback": True,
                "status": "executing",
                "error_message": f"规划输出非法，已保留原格式：{detail}",
            }
        )
    return updates


def route_after_guard(state: dict[str, Any]) -> str:
    """EntryGuard 条件路由：executing→executor，planning→回跳 planner，
    cancelled→error_node（用户取消短路，避免回跳 planner 死循环）。

    :param state: 当前状态
    :return: 下一节点名
    """
    status = state.get("status")
    if status == "executing":
        return "executor"
    if status == "cancelled":
        return "error_node"
    return "planner"
