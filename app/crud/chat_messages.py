"""
====================================================================
文件用途：chat_messages 表 CRUD（聊天记录数据访问）
====================================================================
作用：
    提供聊天记录的写入与历史查询，按 user_id 严格隔离。
调用方：
    - app/api/chat.py（聊天落库 / 历史查询）
====================================================================
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import ChatMessage


def add_message(
    db: Session,
    user_id: int,
    role: str,
    content: str,
    sources: list[dict[str, Any]] | None = None,
) -> ChatMessage:
    """写入一条聊天记录（用户提问或助手回答）。"""
    msg = ChatMessage(
        user_id=user_id,
        role=role,
        content=content,
        sources=sources or [],
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def list_messages(
    db: Session, user_id: int, limit: int = 100
) -> list[ChatMessage]:
    """查询用户最近的聊天记录（新 → 旧，供前端倒序展示）。"""
    return (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == user_id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(limit)
        .all()
    )


def serialize_message(msg: ChatMessage) -> dict[str, Any]:
    """聊天记录序列化（供前端展示）。"""
    return {
        "id": msg.id,
        "role": msg.role,
        "content": msg.content,
        "sources": msg.sources or [],
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }
