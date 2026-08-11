"""
====================================================================
文件用途：LangGraph 多智能体状态机（蓝图 6.2 流转逻辑落地）
====================================================================
流转拓扑：
    START → supervisor → rag_searcher → planner → entry_guard
              │  解析失败(↓error_node)            │  非法指令(→planner LLM重试 / 兜底)
              │                                   ▼
              │                              executor
              │                                   │  执行失败(→error_node)
              │                                   ▼
              │                              validator
              │                                   │  passed=False 且 retry<3 (→planner 增量修补)
              │                                   │  passed=True (→success_node)
              │                                   └  passed=False 且 retry>=3 (→error_node)
              ▼
         error_node ──► END            success_node ──► END

说明：
    - Checkpointer 用 SqliteSaver（蓝图 P1 原定 Redis db=3 降级原因：单机
      solo worker 下 SQLite 更稳、零额外依赖、DB 文件随卷持久化）；状态全
      部可序列化（docx 对象不进 state，节点各自从文件重建）。
====================================================================
"""

from __future__ import annotations

import os  # checkpoint 目录创建
import sqlite3  # SqliteSaver 底层连接
from typing import Any  # 泛型类型

from langgraph.checkpoint.sqlite import SqliteSaver  # 断点持久化
from langgraph.graph import END, START, StateGraph  # LangGraph 图构建

from app.agents.nodes import (  # 节点与条件路由
    entry_guard_node,
    error_node,
    executor_node,
    planner_node,
    rag_searcher_node,
    route_after_executor,
    route_after_guard,
    route_after_validator,
    success_node,
    supervisor_node,
    validator_node,
)
from app.agents.state import DocAgentState  # 状态模式

# 节点名常量（与蓝图 6.2 对齐）
SUPERVISOR = "supervisor"
RAG_SEARCHER = "rag_searcher"
PLANNER = "planner"
ENTRY_GUARD = "entry_guard"
EXECUTOR = "executor"
VALIDATOR = "validator"
SUCCESS = "success_node"
ERROR = "error_node"


def route_after_supervisor(state: dict[str, Any]) -> str:
    """Supervisor 条件路由：解析失败/已取消→error_node，否则→rag_searcher。"""
    return ERROR if state.get("status") in ("failed", "cancelled") else RAG_SEARCHER


_checkpointer: SqliteSaver | None = None  # 进程内单例（worker 长驻复用连接）


def get_checkpointer() -> SqliteSaver:
    """获取 SqliteSaver 单例：SQLite 连接在整个 Worker 进程生命周期内复用。

    :return: SqliteSaver 实例（每次任务中断/恢复共享同一 DB 文件）
    """
    global _checkpointer
    if _checkpointer is None:
        from app.config import settings  # 延迟导入避免循环

        db_path = settings.checkpoint_db_path
        if db_path != ":memory:" and os.path.dirname(db_path):
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
        # check_same_thread=False：LangGraph 任务在独立线程执行，连接跨线程复用
        _checkpointer = SqliteSaver(
            sqlite3.connect(db_path, check_same_thread=False)
        )
    return _checkpointer


def build_graph():
    """装配并编译 LangGraph 状态机（含重试闭环 + SqliteSaver 断点持久化）。

    :return: 已编译的可执行图
    """
    graph = StateGraph(DocAgentState)

    # ---- 注册节点 ----
    graph.add_node(SUPERVISOR, supervisor_node)  # 主调度 / 文档解析
    graph.add_node(RAG_SEARCHER, rag_searcher_node)  # 混合检索选模板
    graph.add_node(PLANNER, planner_node)  # 双路径生成原子指令
    graph.add_node(ENTRY_GUARD, entry_guard_node)  # 指令合法性校验
    graph.add_node(EXECUTOR, executor_node)  # 逐条执行 + 备份
    graph.add_node(VALIDATOR, validator_node)  # 五项覆盖率校验
    graph.add_node(SUCCESS, success_node)  # 成功收尾
    graph.add_node(ERROR, error_node)  # 失败收尾

    # ---- 主链路 ----
    graph.add_edge(START, SUPERVISOR)
    graph.add_conditional_edges(  # 解析失败→error，成功→rag
        SUPERVISOR,
        route_after_supervisor,
        {RAG_SEARCHER: RAG_SEARCHER, ERROR: ERROR},
    )
    graph.add_edge(RAG_SEARCHER, PLANNER)
    graph.add_edge(PLANNER, ENTRY_GUARD)

    # ---- EntryGuard 分支：合法→executor，非法→planner(LLM重试/兜底)，取消→error ----
    graph.add_conditional_edges(
        ENTRY_GUARD,
        route_after_guard,
        {EXECUTOR: EXECUTOR, PLANNER: PLANNER, ERROR: ERROR},
    )

    # ---- Executor 分支：成功→validator，失败→error ----
    graph.add_conditional_edges(
        EXECUTOR,
        route_after_executor,
        {VALIDATOR: VALIDATOR, ERROR: ERROR},
    )

    # ---- Validator 重试闭环：passed→success，未达标→planner(增量修补)，耗尽→error ----
    graph.add_conditional_edges(
        VALIDATOR,
        route_after_validator,
        {SUCCESS: SUCCESS, PLANNER: PLANNER, ERROR: ERROR},
    )

    # ---- 收尾 ----
    graph.add_edge(SUCCESS, END)
    graph.add_edge(ERROR, END)

    return graph.compile(checkpointer=get_checkpointer())


def run_agent(initial_state: dict[str, Any]) -> dict[str, Any]:
    """便捷入口：编译并执行一次完整任务流。

    :param initial_state: 初始状态，至少含 task_id / user_prompt / working_file_path /
                          input_file_path（API 层构造，可含 output_file_path）
    :return: 终态状态字典（含 status / validation_report / agent_logs 等）
    """
    # thread_id = task_id：Checkpointer 按任务维度存储断点，中断后可续跑
    config = {"configurable": {"thread_id": initial_state.get("task_id") or "default"}}
    return build_graph().invoke(initial_state, config=config)
