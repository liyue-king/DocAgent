"""
====================================================================
文件用途：ChromaDB 初始化脚本（灌入 10 条模板向量）
====================================================================
作用：
    1. 连接 ChromaDB 容器，创建/获取 doc_templates Collection。
    2. 从 seed_templates.json 读取 10 种预设模板。
    3. 用 BGE-M3 对每条模板的 description 做 embedding。
    4. 批量灌入 ChromaDB（幂等：已存在的模板不重复插入）。
    5. 回填 MySQL templates 表（vector_id = tmpl_00N，config 同步写入）。
运行：
    PYTHONPATH=. python scripts/init_chroma.py
依赖：
    - ChromaDB 容器（localhost:8000）
    - MySQL 容器（localhost:3307，需先跑 init_db.py 建表）
    - BGE-M3 模型（首次运行自动下载 ~2GB）
====================================================================
"""

from __future__ import annotations

import json  # 读取种子模板 JSON
import sys  # 退出码
from pathlib import Path  # 跨平台路径

# 首次导入 BGE-M3 会下载模型（约 2GB，需联网）
from sentence_transformers import SentenceTransformer

import chromadb  # 向量库客户端（HTTP）

# ---- 导入本项目的数据库层 ----
from app.config import settings  # ChromaDB 连接配置
from app.db import SessionLocal  # MySQL 会话工厂
from app.crud import templates as tpl_crud  # 模板 CRUD（回填 MySQL）


def init_chroma() -> int:
    """主流程：灌入向量并回填 MySQL。返回 0=成功，1=失败。"""
    # ---------- 1. 连接 ChromaDB ----------
    chroma_client = chromadb.HttpClient(
        host=settings.chroma_host, port=settings.chroma_port
    )
    # 获取或创建 Collection（不传 embedding_function，我们自己算向量）
    collection = chroma_client.get_or_create_collection(name="doc_templates")

    # ---------- 2. 加载 BGE-M3 embedding 模型 ----------
    print("加载 BGE-M3 模型（首次需下载约 2GB，请耐心等待）...")
    model = SentenceTransformer("BAAI/bge-m3")
    print("模型加载完成。")

    # ---------- 3. 读取种子模板 ----------
    seed_path = Path(__file__).resolve().parent / "seed_templates.json"
    with open(seed_path, encoding="utf-8") as f:
        seeds = json.load(f)
    print(f"读取 {len(seeds)} 条种子模板。")

    # ---------- 4. 生成向量并灌入 ChromaDB ----------
    ids: list[str] = []           # ChromaDB document ID（tmpl_001~tmpl_010）
    embeddings: list[list[float]] = []  # 向量
    documents: list[str] = []     # 原始文本
    metadatas: list[dict] = []    # 元数据

    for idx, seed in enumerate(seeds, start=1):
        doc_id = f"tmpl_{idx:03d}"  # 格式 tmpl_001, tmpl_002, ...
        # 检查 ChromaDB 中是否已存在该模板（幂等）
        existing = collection.get(ids=[doc_id])
        if existing["ids"]:  # 已存在，跳过
            print(f"  [跳过] {doc_id} {seed['name']}（已存在）")
            ids.append(doc_id)  # 仍记录 ID 用于回填
            continue

        # 生成向量（BGE-M3: 1024 维）
        vec = model.encode(seed["description"]).tolist()

        ids.append(doc_id)
        embeddings.append(vec)
        documents.append(seed["description"])
        metadatas.append({
            "template_name": seed["name"],
            "category": seed["category"],
        })
        print(f"  [向量] {doc_id} {seed['name']}")

    # 批量灌入（只灌入新增的）
    if len(embeddings) > 0:
        collection.upsert(
            ids=ids[-len(embeddings):] if len(ids) > len(embeddings) else ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas if metadatas else None,
        )
        print(f"灌入 {len(embeddings)} 条新向量到 ChromaDB。")
    else:
        print("无新增向量，跳过灌入。")

    # ---------- 5. 回填 MySQL templates 表 ----------
    db = SessionLocal()
    try:
        for idx, seed in enumerate(seeds, start=1):
            doc_id = f"tmpl_{idx:03d}"
            existing_tpl = tpl_crud.get_by_name(db, seed["name"])
            if existing_tpl is None:
                # 新建模板
                tpl_crud.create_template(
                    db,
                    name=seed["name"],
                    description=seed["description"],
                    config=seed["config"],
                    vector_id=doc_id,
                    is_system=True,
                )
                print(f"  [MySQL] 新建模板: {seed['name']} (vector_id={doc_id})")
            else:
                # 已存在：回填 vector_id（如果之前为空）
                if not existing_tpl.vector_id:
                    existing_tpl.vector_id = doc_id
                    db.commit()
                    print(f"  [MySQL] 回填 vector_id: {seed['name']} -> {doc_id}")
                else:
                    print(f"  [MySQL] 跳过: {seed['name']}（已有 vector_id={existing_tpl.vector_id}）")
        print("MySQL 回填完成。")
    except Exception as e:
        db.rollback()
        print(f"MySQL 回填失败: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()

    print("=== ChromaDB 初始化完成 ===")
    return 0


if __name__ == "__main__":
    sys.exit(init_chroma())
