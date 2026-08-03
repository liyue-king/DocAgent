"""
====================================================================
文件用途：agent_logs 表 ORM 模型（Agent 执行日志）
====================================================================
作用：
    定义 agent_logs 表。记录每个 Agent 节点的执行步骤日志，
    是前端“黑底绿字滚动日志终端”的持久化数据源。
依赖：
    - app.db.Base（ORM 基类）
    - app.models.enums.LogLevel（日志级别枚举）
调用方：
    - app/crud/agent_logs.py（日志追加/查询）
    - app/agents/*（后续：各节点写入日志）
说明：
    - task_id 外键 ON DELETE CASCADE：任务删除时日志一并删除。
    - idx_task_id_created 索引：按任务查最近日志的高频查询。
====================================================================
"""

from __future__ import annotations  # 延迟求值注解：配合 TYPE_CHECKING 解决前向引用报红

from datetime import datetime  # 时间戳类型
from typing import TYPE_CHECKING  # 类型检查专用标记

from sqlalchemy import (  # 列类型与 SQL 表达式
    BigInteger,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy import Enum as SAEnum  # SQLAlchemy 枚举类型（用于生成 MySQL ENUM）
from sqlalchemy.dialects.mysql import DATETIME  # MySQL 专用 DATETIME（毫秒精度）
from sqlalchemy.orm import (  # SQLAlchemy 2.0 映射 API
    Mapped,
    mapped_column,
    relationship,
)

from app.db import Base  # ORM 公共基类
from app.models.enums import LogLevel  # 日志级别枚举

if TYPE_CHECKING:
    # 仅用于类型检查/IDE 提示，运行时不会真正导入（避免循环导入）
    from app.models.task import Task


class AgentLog(Base):
    """Agent 执行日志模型：对应 agent_logs 表。"""

    __tablename__ = "agent_logs"  # 表名

    # 主键：自增大整数
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 所属任务：外键 -> tasks.id，删除任务时级联删除日志
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    # 产生日志的 Agent 节点名（supervisor/rag_searcher/planner/executor/validator）
    agent_node: Mapped[str] = mapped_column(String(30), nullable=False)
    # 日志级别：INFO/WARNING/ERROR（存枚举值，对齐蓝图 DDL）
    log_level: Mapped[LogLevel] = mapped_column(
        SAEnum(LogLevel, values_callable=lambda e: [m.value for m in e], name="log_level"),
        default=LogLevel.INFO,
        server_default="INFO",
    )
    # 日志正文（如"正在修改第3章标题"）
    log_message: Mapped[str] = mapped_column(Text, nullable=False)
    # 创建时间：毫秒精度
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), default=datetime.now, server_default=text("CURRENT_TIMESTAMP(3)")
    )

    # 关系：多对一，日志 -> 任务
    task: Mapped[Task] = relationship(back_populates="logs")

    # 索引：按 (task_id, created_at) 查询最近日志
    __table_args__ = (
        Index("idx_task_id_created", "task_id", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        """调试友好的对象描述。"""
        return f"<AgentLog id={self.id} node={self.agent_node} level={self.log_level}>"
