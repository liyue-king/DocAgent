"""
====================================================================
文件用途：ORM 模型聚合出口（模型包的门面）
====================================================================
作用：
    集中导入并导出全部模型类与枚举，让调用方只需写
    `from app.models import User, Template, Task, AgentLog` 一行。
依赖：
    - app.db.Base             （模型基类）
    - app/models 下的各模型与枚举模块
调用方：
    - app/crud/*.py   （数据访问层）
    - scripts/init_db.py 等初始化脚本（后续创建）
说明：
    - 导入顺序经过设计：全部模型在这里注册，SQLAlchemy 才能
      解析表之间的外键与 relationship 关系。
====================================================================
"""

from app.db import Base  # 导入 ORM 公共基类（重导出，供建表脚本使用）
from app.models.agent_log import AgentLog  # Agent 执行日志模型
from app.models.enums import LogLevel, TaskStatus  # 日志级别 / 任务状态枚举
from app.models.knowledge_doc import KnowledgeDoc  # 用户自定义知识库文档
from app.models.payment import Payment  # 支付订单模型
from app.models.task import Task  # 任务核心模型（九态状态机）
from app.models.template import Template  # 排版模板模型
from app.models.user import User  # 用户模型（P0 匿名游客 id=1）

# 对外公开的符号白名单：from app.models import * 时只导入这些
__all__ = [
    "AgentLog",
    "Base",
    "KnowledgeDoc",
    "LogLevel",
    "Payment",
    "Task",
    "TaskStatus",
    "Template",
    "User",
]
