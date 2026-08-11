"""
====================================================================
文件用途：模板向量化/灌入服务（管理员 CRUD 与 init_chroma 共用）
====================================================================
作用：
    1. 模板增/改时对 description 做 BGE-M3 向量化并 upsert 到
       ChromaDB doc_templates 集合（vector_id 对齐 MySQL 主键）。
    2. 删除模板时尽力清理向量（失败仅告警，不影响 MySQL 主数据）。
    3. seed_templates 供 scripts/init_chroma.py 复用（幂等种子灌入）。
依赖：
    - chromadb / sentence-transformers（共享 knowledge.get_embedder 单例）
    - app.services.knowledge.KnowledgeUnavailable（统一降级异常）
调用方：
    - app/api/templates.py（管理员 CRUD）
    - scripts/init_chroma.py（种子灌入）
说明：
    - 向量化/Chroma 不可用一律抛 KnowledgeUnavailable，由调用方决定
      回滚 MySQL，保证 MySQL 与向量库永远一致。
====================================================================
"""

from __future__ import annotations

import logging  # 标准库日志
from typing import Any  # 泛型类型

import chromadb  # 向量库 HTTP 客户端

from app.config import settings  # ChromaDB 连接配置
from app.services.embeddings import get_embedder  # 共享 BGE-M3 单例
from app.services.knowledge import KnowledgeUnavailable  # 统一降级异常

logger = logging.getLogger(__name__)  # 模块级日志器

_TEMPLATE_COLLECTION = "doc_templates"  # 模板向量集合

_chroma_client: Any | None = None  # Chroma 客户端单例
_collection: Any | None = None  # 模板集合单例


def _get_collection() -> Any:
    """获取（并按需创建）模板向量集合（cosine 空间）。"""
    global _chroma_client, _collection
    if _collection is None:
        try:
            if _chroma_client is None:
                _chroma_client = chromadb.HttpClient(
                    host=settings.chroma_host, port=settings.chroma_port
                )
            _collection = _chroma_client.get_or_create_collection(
                name=_TEMPLATE_COLLECTION, metadata={"hnsw:space": "cosine"}
            )
        except Exception as exc:  # 连接/创建失败
            raise KnowledgeUnavailable(f"模板向量库不可用: {exc}") from exc
    return _collection


def upsert_vector(name: str, description: str, vector_id: str) -> None:
    """向量化模板描述并 upsert 到 ChromaDB（新增/更新共用，覆盖写）。

    :param name: 模板名称（元数据 template_name）
    :param description: 模板语义描述（向量化对象）
    :param vector_id: ChromaDB 文档 ID（tmpl_xxx）
    :raises KnowledgeUnavailable: 模型加载/向量库不可用
    """
    model = get_embedder()  # BGE-M3 共享单例（失败抛异常由调用方转业务错误）
    vec = model.encode(description, normalize_embeddings=True).tolist()
    _get_collection().upsert(
        ids=[vector_id],
        embeddings=[vec],
        documents=[description],
        metadatas=[{"template_name": name, "category": ""}],
    )


def delete_vector(vector_id: str) -> None:
    """从 ChromaDB 删除模板向量；不可用时仅告警（向量孤儿不影响主数据）。"""
    try:
        _get_collection().delete(ids=[vector_id])
    except Exception as exc:
        logger.warning("[template_seed] 向量删除失败 %s: %s", vector_id, exc)


def seed_templates(db, seeds: list[dict[str, Any]]) -> int:
    """幂等灌入种子模板：向量化 + ChromaDB upsert + MySQL 回填。

    供 scripts/init_chroma.py 调用；返回 0=成功，1=失败。
    已存在的模板（ChromaDB 按 vector_id / MySQL 按名称）跳过。
    """
    from app.crud import templates as tpl_crud  # 延迟导入避免循环

    collection = _get_collection()  # 先探活（失败提前返回）
    model = get_embedder()
    print("模板向量化灌入开始（首次加载模型约 1-2 分钟）...")

    ids: list[str] = []
    embeddings: list[list[float]] = []
    documents: list[str] = []
    metadatas: list[dict] = []

    for idx, seed in enumerate(seeds, start=1):
        doc_id = f"tmpl_{idx:03d}"
        if collection.get(ids=[doc_id])["ids"]:  # 幂等：已存在跳过
            print(f"  [跳过] {doc_id} {seed['name']}（已存在）")
            continue
        vec = model.encode(seed["description"], normalize_embeddings=True).tolist()
        ids.append(doc_id)
        embeddings.append(vec)
        documents.append(seed["description"])
        metadatas.append(
            {"template_name": seed["name"], "category": seed["category"]}
        )
        print(f"  [向量] {doc_id} {seed['name']}")

    if embeddings:
        collection.upsert(
            ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas
        )
        print(f"灌入 {len(embeddings)} 条新向量到 ChromaDB。")
    else:
        print("无新增向量，跳过灌入。")

    try:
        for idx, seed in enumerate(seeds, start=1):
            doc_id = f"tmpl_{idx:03d}"
            existing_tpl = tpl_crud.get_by_name(db, seed["name"])
            if existing_tpl is None:
                tpl_crud.create_template(
                    db,
                    name=seed["name"],
                    description=seed["description"],
                    config=seed["config"],
                    vector_id=doc_id,
                    is_system=True,
                )
                print(f"  [MySQL] 新建模板: {seed['name']} (vector_id={doc_id})")
            elif not existing_tpl.vector_id:
                existing_tpl.vector_id = doc_id
                db.commit()
                print(f"  [MySQL] 回填 vector_id: {seed['name']} -> {doc_id}")
            else:
                print(f"  [MySQL] 跳过: {seed['name']}（已有 vector_id）")
        print("MySQL 回填完成。")
    except Exception as exc:  # MySQL 写入失败
        db.rollback()
        print(f"MySQL 回填失败: {exc}")
        return 1
    return 0
