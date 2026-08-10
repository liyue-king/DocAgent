"""
====================================================================
文件用途：user_knowledge_docs 表 CRUD（用户自定义知识库文档）
====================================================================
作用：
    提供用户知识库文档清单的增删查：按用户列出、按主键查询
    （带用户归属校验）、创建记录、删除记录。
依赖：
    - sqlalchemy.orm.Session（数据库会话）
    - app.models.KnowledgeDoc（文档模型）
调用方：
    - app/api/knowledge.py（我的知识库接口）
说明：
    - 所有查询强制带 user_id，保证“每个人的知识库独立”。
    - 向量片段删除由 service 层负责，CRUD 只管 MySQL 清单。
====================================================================
"""

from __future__ import annotations

from sqlalchemy.orm import Session  # 数据库会话类型

from app.models import KnowledgeDoc  # 文档模型


def create_doc(
    db: Session,
    *,
    user_id: int,
    doc_id: str,
    title: str,
    category: str = "其他",
    filename: str | None = None,
    chunk_count: int = 0,
    minio_key: str | None = None,
) -> KnowledgeDoc:
    """创建用户知识库文档记录。"""
    doc = KnowledgeDoc(
        user_id=user_id,
        doc_id=doc_id,
        title=title,
        category=category or "其他",
        filename=filename,
        chunk_count=chunk_count,
        minio_key=minio_key,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def list_docs_by_user(
    db: Session, user_id: int, limit: int = 100, offset: int = 0
) -> list[KnowledgeDoc]:
    """按用户列出知识库文档（新 → 旧）。"""
    return (
        db.query(KnowledgeDoc)
        .filter(KnowledgeDoc.user_id == user_id)
        .order_by(KnowledgeDoc.created_at.desc(), KnowledgeDoc.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def count_docs_by_user(db: Session, user_id: int) -> int:
    """统计用户的文档总数。"""
    return (
        db.query(KnowledgeDoc)
        .filter(KnowledgeDoc.user_id == user_id)
        .count()
    )


def get_doc_for_user(db: Session, user_id: int, doc_id: str) -> KnowledgeDoc | None:
    """按 doc_id 查询文档，且必须是该用户自己的文档。"""
    return (
        db.query(KnowledgeDoc)
        .filter(KnowledgeDoc.doc_id == doc_id, KnowledgeDoc.user_id == user_id)
        .first()
    )


def delete_doc(db: Session, doc: KnowledgeDoc) -> None:
    """删除文档记录（向量片段清理由 service 层调用方负责）。"""
    db.delete(doc)
    db.commit()
