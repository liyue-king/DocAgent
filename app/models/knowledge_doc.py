"""
====================================================================
文件用途：user_knowledge_docs 表 ORM 模型（用户自定义知识库文档）
====================================================================
作用：
    记录用户上传到“我的知识库”的文档清单：标题、分类、原始文件名、
    切块数量与 MinIO 原文备份位置，用于列表展示、删除与统计。
依赖：
    - app.db.Base（ORM 基类）
调用方：
    - app/crud/knowledge_docs.py（文档清单 CRUD）
    - app/api/knowledge.py（我的知识库接口）
说明：
    - doc_id 为稳定文档标识，同时写入向量集合的 metadata，
      删除文档时按 (user_id, doc_id) 精准清理向量片段。
    - 每个用户的知识库相互独立：向量检索与清单查询都带 user_id 条件。
====================================================================
"""

from __future__ import annotations

from datetime import datetime  # 时间戳
from typing import TYPE_CHECKING  # 类型检查标记

from sqlalchemy import (  # SQLAlchemy 核心组件
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.mysql import DATETIME  # MySQL 专用类型
from sqlalchemy.orm import Mapped, mapped_column, relationship  # SQLAlchemy 2.0 映射

from app.db import Base  # ORM 公共基类

if TYPE_CHECKING:
    from app.models.user import User


class KnowledgeDoc(Base):
    """用户知识库文档模型：对应 user_knowledge_docs 表。"""

    __tablename__ = "user_knowledge_docs"  # 表名

    # 主键：自增大整数
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 所属用户：外键 -> users.id
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    # 稳定文档标识（写入向量 metadata，删除时使用）
    doc_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    # 文档标题
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # 分类（用户自定义，默认“其他”）
    category: Mapped[str] = mapped_column(
        String(50), default="其他", server_default="其他"
    )
    # 原始文件名（粘贴文本上传时为空）
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 切块数量
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # MinIO 原文备份位置（备份失败时为空）
    minio_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 创建 / 更新时间（毫秒精度）
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        default=datetime.now,
        server_default=text("CURRENT_TIMESTAMP(3)"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        default=datetime.now,
        server_default=text("CURRENT_TIMESTAMP(3)"),
        onupdate=datetime.now,
    )

    # 关系：文档 -> 用户（反向 user.knowledge_docs）
    user: Mapped[User] = relationship(back_populates="knowledge_docs")

    # 索引：按用户查文档清单（新 → 旧）
    __table_args__ = (Index("idx_knowledge_docs_user", "user_id", "created_at"),)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<KnowledgeDoc id={self.id} user_id={self.user_id} title={self.title}>"
