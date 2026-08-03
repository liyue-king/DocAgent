"""
====================================================================
文件用途：tasks 表 ORM 模型（任务核心表，含 Agent 全状态）
====================================================================
作用：
    定义 tasks 表——整个系统的“状态中枢”。一条记录 = 一次文档处理任务，
    记录任务从提交到成功/失败的完整生命周期与运行指标。
依赖：
    - app.db.Base（ORM 基类）
    - app.models.enums.TaskStatus（九态状态枚举）
    - app.config.settings（expires_at 默认时长）
调用方：
    - app/crud/tasks.py（任务 CRUD，全生命周期管理）
    - app/api/routes.py（后续：创建/查询/下载任务）
    - app/agents/*（后续：LangGraph 各节点更新状态）
字段说明：
    - id：UUID 字符串，与 Celery task_id 一致（跨系统对齐）。
    - status：九态枚举，对应 LangGraph 状态机与前端六态视图。
    - agent_state_snapshot：LangGraph 全量状态快照（JSON），便于排查。
    - expires_at = created_at + 24h（任务与文件的生命周期边界）。
====================================================================
"""

from __future__ import annotations  # 延迟求值注解：配合 TYPE_CHECKING 解决前向引用报红

from datetime import datetime, timedelta  # 时间戳与时间差计算
from decimal import Decimal  # 高精度金额类型（cost_usd 列）
from typing import TYPE_CHECKING, Any  # 类型检查标记 + 任意 JSON 类型

from sqlalchemy import (  # SQLAlchemy 核心组件（多行导入，ruff 排序）
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy import Enum as SAEnum  # SQLAlchemy 枚举类型（用于生成 MySQL ENUM）
from sqlalchemy.dialects.mysql import DATETIME, DECIMAL, JSON, TINYINT  # MySQL 专用类型
from sqlalchemy.orm import (  # SQLAlchemy 2.0 映射 API
    Mapped,
    mapped_column,
    relationship,
)

from app.config import settings  # 读取任务过期时长配置
from app.db import Base  # ORM 公共基类
from app.models.enums import TaskStatus  # 任务状态枚举

if TYPE_CHECKING:
    # 仅用于类型检查/IDE 提示，运行时不会真正导入（避免循环导入）
    from app.models.agent_log import AgentLog
    from app.models.template import Template
    from app.models.user import User


class Task(Base):
    """任务核心模型：对应 tasks 表。"""

    __tablename__ = "tasks"  # 表名

    # 主键：UUID 字符串（36 位），与 Celery task_id 保持一致
    id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="UUID (与Celery task_id一致)")

    # ---------------- 归属与模板 ----------------
    # 所属用户：外键 -> users.id，默认匿名游客 id=1
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False, default=1, server_default="1"
    )
    # 命中的模板：外键 -> templates.id，模板删除时置 NULL
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("templates.id", ondelete="SET NULL"), nullable=True
    )

    # ---------------- 文件与提示词 ----------------
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)  # 用户自然语言需求
    input_file_name: Mapped[str] = mapped_column(String(255), nullable=False)  # 上传文件名
    input_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # 文件哈希（去重/校验）
    input_file_path: Mapped[str] = mapped_column(String(500), nullable=False)  # MinIO 输入对象路径
    output_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)  # MinIO 输出对象路径（成功后回填）

    # ---------------- Agent 状态机 ----------------
    # 任务状态：九态枚举，values_callable 让 ENUM 存小写值，对齐蓝图 DDL
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, values_callable=lambda e: [m.value for m in e], name="task_status"),
        default=TaskStatus.PENDING,  # 初始状态：待处理
        server_default="pending",
    )
    # 进度百分比：0-100（检索 0-30 / 规划 30-60 / 执行 60-90 / 校验 90-100）
    progress: Mapped[int] = mapped_column(TINYINT(unsigned=True), default=0, server_default="0")
    # 当前步骤描述（如"正在修改第3章标题"，前端展示）
    current_step: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 校验失败重试次数（上限 = settings.max_retry_count = 3）
    retry_count: Mapped[int] = mapped_column(TINYINT(unsigned=True), default=0, server_default="0")

    # ---------------- 运行指标 ----------------
    # LangGraph 全量状态快照（JSON），问题排查利器
    agent_state_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, comment="LangGraph全量状态快照")
    # LLM 累计消耗 token 数（成本核算）
    llm_total_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # LLM 费用（USD，6 位小数，unsigned 非负，对齐蓝图 DDL）
    cost_usd: Mapped[Decimal] = mapped_column(
        DECIMAL(10, 6, unsigned=True), default=Decimal(0), server_default="0.000000"
    )
    # 处理耗时（毫秒）
    processing_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ---------------- 时间线 ----------------
    started_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)  # Worker 开始处理时间
    completed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)  # 成功/失败收尾时间
    # 过期时间：默认 now + 24h（读取配置），生命周期兜底
    expires_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        nullable=False,
        default=lambda: datetime.now() + timedelta(hours=settings.task_expire_hours),
        comment="created_at + 24小时",
    )
    # 创建时间：毫秒精度
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), default=datetime.now, server_default=text("CURRENT_TIMESTAMP(3)")
    )
    # 更新时间：毫秒精度，更新时自动刷新
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        default=datetime.now,
        server_default=text("CURRENT_TIMESTAMP(3)"),
        onupdate=datetime.now,
    )

    # ---------------- 关系 ----------------
    user: Mapped[User] = relationship(back_populates="tasks")  # 多对一：任务 -> 用户
    template: Mapped[Template] = relationship(back_populates="tasks")  # 多对一：任务 -> 模板
    # 一对多：任务 -> 日志；级联删除（删任务连带删日志），被动删除依赖数据库 ON DELETE CASCADE
    logs: Mapped[list[AgentLog]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )

    # ---------------- 索引（对齐蓝图 DDL，加速高频查询） ----------------
    __table_args__ = (
        Index("idx_user_status", "user_id", "status"),      # 按用户+状态查询（我的任务列表）
        Index("idx_status_created", "status", "created_at"), # 按状态+时间查询（列表/清理任务）
        Index("idx_expires_at", "expires_at"),               # 过期任务扫描（清理任务）
    )

    def __repr__(self) -> str:  # pragma: no cover
        """调试友好的对象描述。"""
        return f"<Task id={self.id} status={self.status}>"
