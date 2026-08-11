"""
====================================================================
文件用途：supervisor_node —— 主调度入口节点
====================================================================
作用：
    1. 记录图启动时间（processing_time 统计基准）；
    2. 解析本地工作副本 working_file_path，生成可序列化 DOM
       （doc_dom_serial）供 Planner 决策；解析失败则直接进入 error_node；
    3. 更新任务状态为 retrieving，调度下一节点（默认 rag_searcher）。
依赖：
    - app.services.docx_parser（parse_docx / build_dom_serial）
    - app.agents.nodes._common（notify）
调用方：
    - app/agents/graph.py（图起点）
说明：
    - doc_dom 字段此处保持 None（仅存纯数据的 doc_dom_serial）；
      含 para_obj 引用的完整 DOM 由 Executor 打开工作文件时重建，
      避免跨节点持有失效的段落对象引用。
====================================================================
"""

from __future__ import annotations

import time  # 启动时间戳
from typing import Any  # 泛型类型

from app.agents.nodes._common import is_cancelled, notify  # 取消判定 / 日志持久化
from app.models import LogLevel, TaskStatus  # 枚举
from app.services.docx_parser import build_dom_serial, parse_docx  # DOM 解析

NODE_NAME = "supervisor"  # 节点名（入库 agent_node 用）


def supervisor_node(state: dict[str, Any]) -> dict[str, Any]:
    """主调度节点：解析工作文档并初始化序列化 DOM。

    :param state: 当前状态（需含 task_id / user_prompt / working_file_path）
    :return: 状态更新（含 agent_logs / status / 解析结果或错误）
    """
    working_file = state.get("working_file_path", "")
    started_at = state.get("started_at_ts")

    # ---- 0. 取消检查：已取消 → 提前退出（error_node 收尾，DB 保持 cancelled）----
    if is_cancelled(state.get("task_id", "")):
        return {"status": "cancelled", "error_message": "任务已取消"}

    # ---- 1. 记录启动时间（仅首次）----
    updates: dict[str, Any] = {}
    if started_at is None:
        started_at = time.time()
        updates["started_at_ts"] = started_at

    # ---- 2. 解析工作文档（失败→error_node）----
    try:
        dom = parse_docx(working_file)  # 打开本地工作副本
        updates["doc_dom_serial"] = build_dom_serial(dom)  # 纯数据 DOM（供 Planner）
        para_count = dom["paragraph_count"]
        logs = notify(
            state,
            f"任务已受理：解析文档完成，共 {para_count} 个段落，开始模板检索",
            NODE_NAME,
            level=LogLevel.INFO,
            status=TaskStatus.RETRIEVING,
            progress=5,
            step="解析用户需求，启动检索",
        )
        updates["agent_logs"] = logs
        updates["status"] = "retrieving"
    except Exception as exc:  # 文件损坏 / 路径缺失
        msg = f"文档解析失败：{exc}"
        logs = notify(
            state,
            msg,
            NODE_NAME,
            level=LogLevel.ERROR,
            status=TaskStatus.FAILED,
            progress=100,
            step="文档解析失败",
        )
        updates["agent_logs"] = logs
        updates["status"] = "failed"
        updates["error_message"] = msg
    return updates
