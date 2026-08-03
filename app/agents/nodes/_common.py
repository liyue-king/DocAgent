"""
====================================================================
文件用途：智能体节点公共工具（日志 / 持久化 / Key 生成）
====================================================================
作用：
    提供各节点共用的辅助函数：
    1. notify() —— 追加时间戳日志行到 state.agent_logs，并尽力写入
       MySQL（agent_logs 表 + tasks 表状态/进度/步骤）。数据库不可用
       时仅降级为控制台日志，绝不中断主流程。
    2. 输出/输入对象 Key 生成（对齐蓝图 5.3 规范）。
依赖：
    - app.models（LogLevel / TaskStatus 枚举）
调用方：
    - app/agents/nodes/*.py（全部节点）
说明：
    - 持久化失败被整体 try/except 包裹：编排层与基础设施解耦，
      基础设施未就绪时状态机仍可在内存中完整跑通（测试友好）。
====================================================================
"""

from __future__ import annotations

import logging  # 标准库日志
from datetime import datetime  # 时间戳格式化
from typing import Any  # 泛型类型

from app.models import LogLevel, TaskStatus  # 日志级别 / 任务状态枚举

logger = logging.getLogger(__name__)  # 模块级日志器


def make_log(message: str) -> str:
    """生成带时间戳的日志行（对齐前端终端格式 [HH:MM:SS] 正文）。"""
    return f"[{datetime.now().strftime('%H:%M:%S')}] {message}"


def append_log(state: dict[str, Any], message: str) -> list[str]:
    """在现有 agent_logs 基础上追加一行日志，返回新列表。

    :param state: 当前状态字典
    :param message: 日志正文
    :return: 追加后的完整日志列表（节点需随返回值写回）
    """
    logs = list(state.get("agent_logs") or [])
    logs.append(make_log(message))
    return logs


def _persist(
    task_id: str,
    agent_node: str,
    message: str,
    level: LogLevel,
    status: TaskStatus | None,
    progress: int | None,
    step: str | None,
    **extra_fields: Any,
) -> None:
    """写入 MySQL（agent_logs 追加 + tasks 状态推进），失败仅告警。

    :param task_id: 任务 UUID（空则跳过，测试场景无任务上下文）
    :param agent_node: 产生日志的节点名
    :param message: 日志正文
    :param level: 日志级别
    :param status: 需更新的任务状态（可空）
    :param progress: 需更新的进度（可空）
    :param step: 需更新的当前步骤描述（可空）
    :param extra_fields: 其它需同步到 tasks 表的列（如 template_id），
                         由 update_task 白名单校验后写入
    """
    if not task_id:  # 无任务上下文（如离线单测）直接跳过
        return
    try:
        from app.crud.agent_logs import add_log  # 延迟导入避免循环依赖
        from app.crud.tasks import update_task
        from app.db import SessionLocal  # 每次调用独立会话，避免跨节点共享

        db = SessionLocal()
        try:
            add_log(
                db, task_id=task_id, agent_node=agent_node, message=message, level=level
            )
            fields: dict[str, Any] = {}
            if status is not None:
                fields["status"] = status
            if progress is not None:
                fields["progress"] = progress
            if step is not None:
                fields["current_step"] = step
            fields.update(extra_fields)  # 扩展字段（update_task 内部有列白名单）
            if fields:
                update_task(db, task_id, **fields)
        finally:
            db.close()
    except Exception as exc:  # 数据库未就绪 / 表缺失等：降级为控制台日志
        logger.warning("[%s] 持久化失败(不影响主流程): %s", agent_node, exc)


def notify(
    state: dict[str, Any],
    message: str,
    agent_node: str,
    level: LogLevel = LogLevel.INFO,
    status: TaskStatus | None = None,
    progress: int | None = None,
    step: str | None = None,
    **extra_fields: Any,
) -> list[str]:
    """日志 + 持久化的统一入口：追加日志行并尽力落库。

    :param state: 当前状态字典
    :param message: 日志正文
    :param agent_node: 节点名
    :param level: 日志级别
    :param status/progress/step: 需同步到 tasks 表的状态字段
    :param extra_fields: 其它需同步的列（如 template_id）
    :return: 追加后的完整日志列表（节点随返回值写回 state.agent_logs）
    """
    logs = append_log(state, message)
    _persist(
        state.get("task_id", ""),
        agent_node,
        message,
        level,
        status,
        progress,
        step,
        **extra_fields,
    )
    return logs


def build_object_key(task_id: str, file_name: str, *, modified: bool = False) -> str:
    """构造 MinIO 对象 Key（对齐蓝图 5.3：{y}/{m}/{d}/{task_id}/...）。

    :param task_id: 任务 UUID
    :param file_name: 原始文件名
    :param modified: True 生成输出 Key（modified_ 前缀），False 生成输入 Key
    :return: 对象 Key（不含桶名前缀，桶由 storage 层决定）
    """
    d = datetime.now()
    prefix = "modified_" if modified else ""
    return f"{d:%Y/%m/%d}/{task_id}/{prefix}{file_name}"


def estimate_cost_usd(total_tokens: int) -> float:
    """粗略估算 LLM 费用（USD）：DeepSeek 平均约 $2/M token（混合输入输出）。

    确定性路径 total_tokens=0 → 费用 0，天然满足单文档成本约束。

    :param total_tokens: LLM 累计 token 数
    :return: 估算费用（美元，6 位精度内）
    """
    return round(total_tokens * 0.000002, 6)
