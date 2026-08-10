"""
====================================================================
文件用途：混合检索器（RAG：向量语义 + BM25 关键词 + RRF 融合）
====================================================================
作用：
    结合 ChromaDB 向量语义检索与 BM25 关键词检索，通过 RRF
    （Reciprocal Rank Fusion）融合两路结果，返回最佳匹配模板。
依赖：
    - chromadb（向量库 HTTP 客户端）
    - sentence-transformers + BAAI/bge-m3（embedding 模型）
    - rank_bm25（BM25 关键词检索）
    - jieba（中文分词，供 BM25 使用）
调用方：
    - app/agents/nodes/rag_searcher（后续：LangGraph RAG Agent 节点）
    - scripts/init_chroma.py（灌库后回填 vector_id）
说明：
    - 相似度三档（蓝图统一口径）：≥0.7 高置信、0.5~0.7 中置信(warning)、<0.5 降级通用模板。
    - RRF 公式：score = Σ[1/(k+rank)]，k=60。
====================================================================
"""

from __future__ import annotations

import json  # 读取种子模板 JSON
import warnings  # 控制 huggingface/torch 噪音
from pathlib import Path  # 跨平台路径处理
from typing import Any  # 泛型类型

warnings.filterwarnings("ignore", category=UserWarning)  # 抑制 huggingface 下载日志

import chromadb  # 向量库客户端（HTTP 模式连接容器）
from rank_bm25 import BM25Okapi  # BM25 关键词检索算法

# ---- jieba 分词（不可用时自动降级为字符级 n-gram） ----
try:
    import jieba  # 中文分词（BM25 用）

    _JIEBA_OK = True
except ImportError:
    _JIEBA_OK = False
    jieba = None  # 占位，后续用 _tokenize 的 fallback 分支


class HybridRetriever:
    """混合检索器：向量 + BM25 → RRF 融合 → 最佳模板。"""

    # RRF 常数：k 越大排名越平滑
    RRF_K = 60

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """中文分词：jieba 可用则用，不可用则降级为字符级 n-gram（2-3 字符）。"""
        if _JIEBA_OK and jieba is not None:
            return list(jieba.cut(text))
        # 字符级 n-gram：对中文按 2-3 字符滑动窗口切分（零依赖）
        chars = [c for c in text if "\u4e00" <= c <= "\u9fff"]  # 只取中文字符
        tokens = chars[:]  # 单字
        for i in range(len(chars) - 1):
            tokens.append(chars[i] + chars[i + 1])  # 双字
        for i in range(len(chars) - 2):
            tokens.append(chars[i] + chars[i + 1] + chars[i + 2])  # 三字
        return tokens or [" "]

    def __init__(
        self,
        chroma_host: str = "localhost",
        chroma_port: int = 8000,
        collection_name: str = "doc_templates",
        seed_path: str | None = None,
    ):
        """
        :param chroma_host: ChromaDB 主机地址
        :param chroma_port: ChromaDB 端口
        :param collection_name: 向量 Collection 名
        :param seed_path: seed_templates.json 路径（BM25 语料源）
        """
        # 连接 ChromaDB 容器（HTTP 模式）
        self.chroma_client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
        self.collection = self.chroma_client.get_or_create_collection(collection_name)

        # 加载 BGE-M3 embedding 模型（进程内共享单例，首次自动下载 ~2GB）
        from app.services.embeddings import get_embedder

        self.embedding = get_embedder()

        # 加载种子模板 JSON 作为 BM25 语料
        if seed_path is None:
            seed_path = str(
                Path(__file__).parents[2] / "scripts" / "seed_templates.json"
            )
        with open(seed_path, encoding="utf-8") as f:
            seeds: list[dict[str, Any]] = json.load(f)
        self.template_list = seeds  # 保留原始列表（按索引对应 BM25）

        # 构建 BM25 索引：每条模板的 description 做分词
        corpus = [s["description"] for s in seeds]  # 语料
        tokenized = [self._tokenize(d) for d in corpus]  # 分词（jieba 或字符级降级）
        self.bm25 = BM25Okapi(tokenized)

    def search(self, prompt: str, top_k: int = 5) -> dict[str, Any]:
        """执行混合检索，返回最佳模板及置信度。

        :param prompt: 用户自然语言需求（如"我要严谨的论文格式"）
        :param top_k: 各路召回数量（向量和 BM25 各取 top_k）
        :return: {"template_name", "template_index", "config", "vector_score",
                  "bm25_rank", "rrf_score", "confidence", "confidence_level"}
        """
        # ----- 第一路：向量语义检索 -----
        query_vec = self.embedding.encode(
            prompt, normalize_embeddings=True
        ).tolist()  # BGE-M3 向量化（归一化，配合 cosine 空间）
        vec_result = self.collection.query(
            query_embeddings=[query_vec],
            n_results=min(top_k, self.collection.count()),  # 不超过总量
            include=["documents", "distances", "metadatas"],
        )
        # 向量排名（按距离升序，距离小 = 相似度高）
        vec_ranks: dict[int, int] = {}  # {template_index: rank}，rank 从 1 开始
        for rank, (doc_id, distance) in enumerate(
            zip(vec_result["ids"][0], vec_result["distances"][0]), start=1
        ):
            idx = int(doc_id.replace("tmpl_", "")) - 1  # tmpl_001 → index 0
            vec_ranks[idx] = rank
        vector_score = 1.0 - vec_result["distances"][0][0]  # 余弦相似度（top-1）

        # ----- 第二路：BM25 关键词检索 -----
        tokens = self._tokenize(prompt)  # 分词（jieba 或字符级降级）
        bm25_scores = self.bm25.get_scores(tokens)  # 每个模板的 BM25 得分
        # BM25 排名（按得分降序）
        bm25_ranked = sorted(
            range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True
        )[:top_k]
        bm25_ranks: dict[int, int] = {
            idx: rank for rank, idx in enumerate(bm25_ranked, start=1)
        }

        # ----- RRF 融合排序 -----
        rrf_scores: dict[int, float] = {}  # {template_index: rrf_score}
        for idx in range(len(self.template_list)):
            score = 0.0
            if idx in vec_ranks:
                score += 1.0 / (self.RRF_K + vec_ranks[idx])  # 向量路贡献
            if idx in bm25_ranks:
                score += 1.0 / (self.RRF_K + bm25_ranks[idx])  # BM25 路贡献
            rrf_scores[idx] = score

        # RRF 得分最高的模板
        best_idx = max(rrf_scores, key=rrf_scores.get)
        best_template = self.template_list[best_idx]

        # ----- 置信度判定（蓝图三档） -----
        if vector_score >= 0.7:
            confidence_level = "high"
        elif vector_score >= 0.5:
            confidence_level = "medium"
        else:
            confidence_level = "low"

        return {
            "template_name": best_template["name"],
            "template_index": best_idx,
            "config": best_template["config"],
            "vector_score": round(vector_score, 4),
            "bm25_rank": bm25_ranks.get(best_idx),
            "vec_rank": vec_ranks.get(best_idx),
            "rrf_score": round(rrf_scores[best_idx], 6),
            "confidence": round(vector_score, 4),
            "confidence_level": confidence_level,
        }
