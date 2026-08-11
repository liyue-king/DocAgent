"""
====================================================================
文件用途：chat_messages 表 ORM 模型（用户专属聊天记录）
====================================================================
作用：
    保存登录用户与 AI 助手的每一轮对话（用户提问 + 助手回答），
    供前端再次打开聊天时恢复历史记录。
依赖：
    - app.db.Base（ORM 基类）
调用方：
    - app/crud/chat_messages.py（读写）
    - app/api/chat.py（聊天时自动落库 / 历史查询）
说明：
    - role 取值 user / assistant。
    - sources 保存回答引用的知识片段（JSON 数组），仅助手消息有值。
====================================================================
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, BigInteger, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.user import User


class ChatMessage(Base):
    """聊天记录模型：对应 chat_messages 表。"""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        default=datetime.now,
        server_default=text("CURRENT_TIMESTAMP(3)"),
    )

    user: Mapped[User] = relationship(back_populates="chat_messages")

    __table_args__ = (Index("idx_chat_user_created", "user_id", "created_at"),)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ChatMessage id={self.id} user={self.user_id} role={self.role}>"
