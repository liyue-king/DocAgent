"""
====================================================================
文件用途：业务枚举定义（与蓝图 MySQL ENUM 严格对齐）
====================================================================
作用：
    定义任务状态（TaskStatus）与日志级别（LogLevel）两类枚举，
    供 ORM 模型、CRUD 层、LangGraph 状态机统一使用。
依赖：
    - Python 标准库 enum
调用方：
    - app/models/task.py（status 列的类型）
    - app/models/agent_log.py（log_level 列的类型）
    - app/crud/tasks.py（状态流转）
说明：
    - 枚举继承 str：值可直接写入数据库，也能与字符串直接比较。
    - values_callable 配合 SAEnum 时，数据库存的是 .value（小写）。
====================================================================
"""

import enum  # 导入标准库枚举模块


class TaskStatus(str, enum.Enum):
    """任务状态（9 个值，对齐 tasks.status ENUM 与三端状态映射）。"""

    PENDING = "pending"  # 已提交，等待 Worker 处理
    RETRIEVING = "retrieving"  # RAG 模板检索中
    PLANNING = "planning"  # Planner 生成原子指令中
    EXECUTING = "executing"  # Executor 执行文档修改中
    VALIDATING = "validating"  # Validator 校验样式覆盖率中
    RETRYING = "retrying"  # 校验未通过，重规划中（前端黄色闪烁）
    SUCCESS = "success"  # 处理成功（可下载）
    FAILED = "failed"  # 处理失败
    EXPIRED = "expired"  # 已过期（24h 生命周期结束）


class LogLevel(str, enum.Enum):
    """Agent 日志级别（对齐 agent_logs.log_level ENUM）。"""

    INFO = "INFO"  # 常规步骤日志
    WARNING = "WARNING"  # 警告（如匹配度一般、校验未满 100%）
    ERROR = "ERROR"  # 错误（任务失败时的详情）
