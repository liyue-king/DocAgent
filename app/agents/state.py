"""
====================================================================
文件用途：DocAgentState —— LangGraph 多智能体状态模式（蓝图 6.1 原样落地）
====================================================================
作用：
    定义整个 LangGraph 状态机的共享状态 Schema：输入（用户需求/任务 ID）、
    RAG 结果、文档 DOM、文件引用、规划与执行、校验闭环、LLM 追踪、控制位。
依赖：
    - typing（TypedDict / List / Dict / Any / Literal / Optional）
调用方：
    - app/agents/nodes/*.py（各节点读取/更新状态字段）
    - app/agents/graph.py（StateGraph(state_schema)）
说明（v5.2 序列化安全约束）：
    - 状态**全部可序列化**（docx 对象不放进 state）：Executor 与 Validator 各自
      从文件路径重建文档对象，Checkpointer（SqliteSaver）可安全持久化全部字段。
    - `doc_dom_serial` 是纯数据 DOM（id/style/text/font/size/bold/行距/段间距），
      供 Planner 决策与状态快照落库。
    - 除蓝图字段外，补充了 3 个**内部路由控制字段**（entry_guard_* / started_at_ts），
      仅用于图内条件边路由与耗时统计，不对外暴露。
====================================================================
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict  # 状态类型定义


class DocAgentState(TypedDict):
    # ── 输入 ──
    user_prompt: str  # 用户自然语言需求
    task_id: str  # 任务 UUID（与 MySQL tasks.id / Celery task_id 一致）

    # ── RAG 结果 ──
    retrieved_templates: list[dict[str, Any]]  # 混合检索召回结果（多路）
    selected_template_id: int  # 命中模板主键（Chroma tmpl_xxx 对齐）
    selected_template_config: dict[str, Any]  # 模板 JSON（paragraph_styles）

    # ── 文档解析（v5.2 序列化安全约束）──
    doc_dom_serial: dict[
        str, Any
    ]  # 纯数据 DOM：段落 id/style/text/font/size/bold/行距/段间距（可序列化，入 Checkpointer）

    # ── 文件引用（MinIO 备份 + 本地工作副本）──
    input_file_path: str  # MinIO 输入对象 Key
    backup_object_key: str  # MinIO 备份对象 Key（修改前已存入）
    working_file_path: str  # 本地临时工作文件路径（API 层从 MinIO 下载生成）
    output_file_path: str  # 输出文件本地路径

    # ── 规划与执行 ──
    task_queue: list[dict[str, Any]]  # 原子指令列表
    current_task_index: int  # 当前执行指令下标
    executed_count: int  # 已成功执行的指令数
    execution_errors: list[
        dict[str, Any]
    ]  # 逐条执行失败记录：[{"index":3,"action":"set_font","para_id":5,"reason":"空段落无run"}]

    # ── 校验闭环（Validator 输出重试所需增量信息）──
    validation_report: dict[
        str, Any
    ]  # {"coverage":0.95,"total":10,"matched":8,"missed":[{para_id,style,expected,actual,reason}],"passed":False}
    retry_count: int  # 校验失败重试次数（上限 settings.max_retry_count=3）

    # ── LLM 使用追踪 ──
    planner_mode: Literal["deterministic", "llm_augmented"]  # 当前 Planner 路径
    planner_llm_calls: int  # 本轮 LLM 调用次数（含重试）

    # ── 控制 ──
    status: Literal[
        "idle", "retrieving", "planning", "executing", "validating", "done", "failed"
    ]
    error_message: str  # 失败/降级原因（供前端展示）
    agent_logs: list[str]  # 带时间戳的日志行（"[HH:MM:SS] xxx"），前端终端展示
    llm_total_tokens: int  # LLM 累计消耗 token（成本核算）

    # ── 内部路由控制（非蓝图字段，仅图内条件边使用）──
    entry_guard_replans: int  # EntryGuard 触发重规划次数（防无限循环，最多 1 次）
    entry_guard_fallback: bool  # 是否已触发硬编码兜底（全部宋体 12pt）
    started_at_ts: float  # 图启动时间戳（秒），success_node 计算处理耗时
