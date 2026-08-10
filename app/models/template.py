"""
====================================================================
文件用途：templates 表 ORM 模型（排版模板实体）
====================================================================
作用：
    定义 templates 表。系统内置 10 种预设模板（学术/商务/政府/个人），
    每套模板的样式配置以 JSON 形式存放在 config 列中。
依赖：
    - app.db.Base（ORM 基类）
调用方：
    - app/crud/templates.py（模板 CRUD）
    - scripts/init_db.py（灌入 10 种模板，后续）
说明：
    - config 列：样式配置 JSON（如正文宋体小四、标题黑体三号、1.5 倍行距）。
    - vector_id 列：与 ChromaDB 中向量文档 ID 对齐（tmpl_001 等）。
    - usage_count 列：模板命中计数，用于 RAG 检索效果统计。
====================================================================
"""

from __future__ import annotations  # 延迟求值注解：配合 TYPE_CHECKING 解决前向引用报红

from datetime import datetime  # 时间戳类型
from typing import TYPE_CHECKING, Any  # 类型检查标记 + 任意 JSON 类型

from sqlalchemy import Boolean, Integer, String, Text, text  # 列类型与 SQL 表达式
from sqlalchemy.dialects.mysql import (  # MySQL 专用 DATETIME(3) 与 JSON 类型
    DATETIME,
    JSON,
)
from sqlalchemy.orm import (  # SQLAlchemy 2.0 映射 API
    Mapped,
    mapped_column,
    relationship,
)

from app.db import Base  # ORM 公共基类

if TYPE_CHECKING:
    # 仅用于类型检查/IDE 提示，运行时不会真正导入（避免循环导入）
    from app.models.task import Task


class Template(Base):
    """排版模板模型：对应 templates 表。"""

    __tablename__ = "templates"  # 表名

    # 主键：自增整数
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 模板名称（如：学术论文 / 商务标书）
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    # 模板语义描述（供 RAG 检索匹配）
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # 样式配置 JSON（paragraph_styles 等，见蓝图 5.1 范例）
    config: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, comment="样式配置JSON"
    )
    # ChromaDB 向量文档 ID（tmpl_001，与向量库对齐）
    vector_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="ChromaDB向量ID"
    )
    # 是否系统内置模板（内置模板不可删除）
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # 命中使用次数（RAG 统计用）
    usage_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # 创建时间：毫秒精度
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        default=datetime.now,
        server_default=text("CURRENT_TIMESTAMP(3)"),
    )

    # 关系：一个模板被多个任务使用（反向导航 template.tasks）
    tasks: Mapped[list[Task]] = relationship(back_populates="template")

    def __repr__(self) -> str:  # pragma: no cover
        """调试友好的对象描述。"""
        return f"<Template id={self.id} name={self.name}>"
