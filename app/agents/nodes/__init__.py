"""
====================================================================
文件用途：智能体节点聚合出口（节点包门面）
====================================================================
作用：
    集中导入并导出全部 LangGraph 节点函数与条件路由函数，供
    app/agents/graph.py 装配状态机。调用方只需：
        from app.agents.nodes import supervisor_node, executor_node, ...
依赖：
    - app/agents/nodes 下各节点模块
说明：
    - 条件路由函数（route_after_*）与节点函数分离，便于 StateGraph
      add_conditional_edges 直接引用。
====================================================================
"""

from app.agents.nodes.entry_guard import (  # EntryGuard 校验 + 路由
    entry_guard_node,
    route_after_guard,
)
from app.agents.nodes.error import error_node  # 失败收尾
from app.agents.nodes.executor import (  # 文档执行 + 路由
    executor_node,
    route_after_executor,
)
from app.agents.nodes.planner import ACTION_WHITELIST, planner_node  # 排版规划
from app.agents.nodes.rag_searcher import rag_searcher_node  # RAG 混合检索
from app.agents.nodes.success import success_node  # 成功收尾
from app.agents.nodes.supervisor import supervisor_node  # 主调度
from app.agents.nodes.validator import (  # 覆盖率校验 + 路由
    route_after_validator,
    validator_node,
)

# 对外公开符号白名单
__all__ = [
    "ACTION_WHITELIST",
    "entry_guard_node",
    "error_node",
    "executor_node",
    "planner_node",
    "rag_searcher_node",
    "route_after_executor",
    "route_after_guard",
    "route_after_validator",
    "success_node",
    "supervisor_node",
    "validator_node",
]
