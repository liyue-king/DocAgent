"""
====================================================================
文件用途：BGE-M3 Embedding 模型共享单例
====================================================================
作用：
    进程内只加载一次 sentence-transformers 模型（BAAI/bge-m3），
    供模板检索（doc_templates）与知识库检索（docagent_knowledge）
    共用，避免重复加载 ~2GB 模型占用内存。
依赖：
    - sentence-transformers（已安装）
调用方：
    - app/services/rag.py（模板混合检索）
    - app/services/knowledge.py（行业知识库检索/向量化）
说明：
    - 模型首次加载较慢（即使本地缓存也需 30-60s），使用 lazy 单例
      保证 API 启动不阻塞；失败抛 LlmUnavailable 由调用方降级。
====================================================================
"""

from __future__ import annotations

import logging  # 标准库日志
from typing import Any  # 泛型类型

logger = logging.getLogger(__name__)  # 模块级日志器

_embedder: Any | None = None  # 模型单例（None=未加载）


def get_embedder() -> Any:
    """获取（并按需加载）BGE-M3 embedding 模型单例。

    :return: SentenceTransformer 实例
    :raises Exception: 模型加载失败（依赖缺失/下载失败/内存不足）
    """
    global _embedder
    if _embedder is None:
        import warnings  # 抑制 huggingface/torch 噪音

        warnings.filterwarnings("ignore", category=UserWarning)
        from sentence_transformers import SentenceTransformer  # 延迟导入

        logger.info("[embeddings] 加载 BGE-M3 模型（首次约 1-2 分钟）...")
        _embedder = SentenceTransformer("BAAI/bge-m3")
        logger.info("[embeddings] BGE-M3 模型加载完成")
    return _embedder
