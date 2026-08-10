"""
====================================================================
文件用途：用户自定义知识库 API 路由（我的知识库）
====================================================================
接口（统一前缀 /api/v1/knowledge）：
    1. GET    /             —— 我的文档清单（新 → 旧）
    2. POST   /             —— 上传文档到我的知识库（txt/md/docx 或粘贴文本）
    3. DELETE /{doc_id}     —— 删除我的某篇文档（含向量片段与原文备份）
    4. GET    /stats        —— 我的知识库统计（文档数 + 片段数）
错误码：
    1001 参数错误       1002 文件过大
    1401 知识库不可用   2001 文档不存在或不属于当前用户
说明：
    - 所有接口要求登录，且只操作当前用户自己的文档（user_id 隔离）。
    - 平台共享知识库（管理员维护，RAG）走 /api/v1/rag/*。
====================================================================
"""

from __future__ import annotations

import logging  # 标准库日志
from typing import Annotated, Any  # 依赖注入标注

from fastapi import APIRouter, Depends, File, Form, UploadFile  # 路由与依赖
from sqlalchemy.orm import Session  # 数据库会话类型

from app.api.auth import get_current_user  # 登录依赖
from app.config import settings  # 大小限制
from app.crud import knowledge_docs as docs_crud  # 文档清单 CRUD
from app.db import get_db  # 会话注入
from app.models import KnowledgeDoc, User  # 模型
from app.services import knowledge  # 知识库服务
from app.services.knowledge import KnowledgeUnavailable  # 知识库异常
from app.services.storage import storage  # MinIO 原文清理

logger = logging.getLogger(__name__)  # 模块级日志器

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])  # 我的知识库路由

_MAX_KB_FILE_MB = 5  # 知识文档大小上限（MB）


def _ok(**data: Any) -> dict[str, Any]:
    """成功响应：{"code":0, **data}。"""
    return {"code": 0, **data}


def _err(code: int, msg: str) -> dict[str, Any]:
    """业务错误响应：{"code":N, "msg":...}（HTTP 200）。"""
    return {"code": code, "msg": msg}


def serialize_doc(doc: KnowledgeDoc) -> dict[str, Any]:
    """文档清单序列化（供前端列表展示）。"""
    return {
        "doc_id": doc.doc_id,
        "title": doc.title,
        "category": doc.category,
        "filename": doc.filename,
        "chunk_count": doc.chunk_count,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


@router.get("")
def list_my_docs(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)] = None,
) -> dict[str, Any]:
    """我的知识库文档清单（新 → 旧）。"""
    docs = docs_crud.list_docs_by_user(db, user.id)
    return _ok(docs=[serialize_doc(d) for d in docs])


@router.post("")
async def upload_my_doc(
    title: Annotated[str, Form()],
    file: Annotated[UploadFile | None, File()] = None,
    content: Annotated[str, Form()] = "",
    category: Annotated[str, Form()] = "其他",
    user: Annotated[User, Depends(get_current_user)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
) -> dict[str, Any]:
    """上传文档到我的知识库：文本抽取 → 切块向量化 → 清单落库。

    multipart/form-data：
        title      必填，文档标题
        file       可选，.docx/.txt/.md 文件
        content    可选，直接粘贴文本（file 为空时使用）
        category   可选，分类（默认“其他”）
    """
    title = title.strip()
    if not title:
        return _err(1001, "参数错误：请填写文档标题")

    # ---- 1. 文本来源：文件优先，其次粘贴文本 ----
    data: bytes | None = None
    if file is not None and file.filename:
        data = await file.read()
        if len(data) > _MAX_KB_FILE_MB * 1024 * 1024:
            return _err(1002, f"文件过大：知识文档最大 {_MAX_KB_FILE_MB}MB")
        try:
            text = knowledge.extract_text(file.filename, data)
        except KnowledgeUnavailable as exc:
            return _err(1401, str(exc))
        raw_name = file.filename
    else:
        text = content.strip()
        raw_name = None
    if not text.strip():
        return _err(1001, "参数错误：文档内容为空（上传文件或粘贴文本）")

    # ---- 2. 切块向量化（用户独立集合） ----
    try:
        doc_id, chunk_count = knowledge.add_user_document(
            user_id=user.id,
            title=title,
            category=category.strip() or "其他",
            text=text,
        )
    except KnowledgeUnavailable as exc:
        return _err(1401, str(exc))
    if chunk_count == 0:
        return _err(1401, "文档未能切分出有效片段，请检查内容")

    # ---- 3. 原文备份 MinIO（失败不阻断） ----
    minio_key = None
    if data is not None and raw_name:
        minio_key = knowledge.store_original(raw_name, data)

    # ---- 4. 文档清单落库 ----
    try:
        doc = docs_crud.create_doc(
            db,
            user_id=user.id,
            doc_id=doc_id,
            title=title,
            category=category.strip() or "其他",
            filename=raw_name,
            chunk_count=chunk_count,
            minio_key=minio_key,
        )
    except Exception as exc:  # 清单落库失败：向量已入库，尽力回滚并告警
        logger.error("[knowledge] 文档清单落库失败: %s", exc)
        try:
            knowledge.delete_user_document(user.id, doc_id)
        except Exception:
            logger.warning("[knowledge] 落库失败回滚向量片段失败: %s", exc)
        return _err(4001, f"内部错误：文档记录创建失败（{exc}）")

    return _ok(
        doc_id=doc.doc_id,
        title=doc.title,
        category=doc.category,
        chunks=doc.chunk_count,
        msg=f"文档已加入我的知识库（{doc.chunk_count} 个片段）",
    )


@router.delete("/{doc_id}")
def delete_my_doc(
    doc_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)] = None,
) -> dict[str, Any]:
    """删除我的某篇文档：清理向量片段 + 原文备份 + 清单记录。"""
    doc = docs_crud.get_doc_for_user(db, user.id, doc_id)
    if doc is None:
        return _err(2001, "文档不存在或不属于当前用户")

    # ---- 1. 清理向量片段（失败不阻断清单删除，但上报） ----
    removed = 0
    try:
        removed = knowledge.delete_user_document(user.id, doc_id)
    except KnowledgeUnavailable as exc:
        logger.warning("[knowledge] 删除向量片段失败: %s", exc)

    # ---- 2. 清理 MinIO 原文（尽力而为） ----
    if doc.minio_key:
        try:
            storage.delete_object(doc.minio_key, bucket=settings.minio_knowledge_bucket)
        except Exception as exc:
            logger.warning("[knowledge] 删除原文备份失败: %s", exc)

    # ---- 3. 删除清单记录 ----
    docs_crud.delete_doc(db, doc)
    return _ok(msg=f"文档已删除（清理 {removed} 个片段）")


@router.get("/stats")
def my_knowledge_stats(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)] = None,
) -> dict[str, Any]:
    """我的知识库统计：文档数 + 片段数。"""
    total_docs = docs_crud.count_docs_by_user(db, user.id)
    try:
        total_chunks = knowledge.count_user_chunks(user.id)
    except KnowledgeUnavailable as exc:
        return _err(1401, str(exc))
    return _ok(total_docs=total_docs, total_chunks=total_chunks)
