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
    - MySQL templates 表（语料/竞争池/配置的唯一真源，种子 JSON 仅兜底）
调用方：
    - app/agents/nodes/rag_searcher（LangGraph RAG Agent 节点）
    - scripts/init_chroma.py（灌库后回填 vector_id）
说明：
    - 相似度三档（蓝图统一口径）：≥0.7 高置信、0.5~0.7 中置信(warning)、<0.5 降级通用模板。
    - RRF 公式：score = Σ[1/(k+rank)]，k=60。
    - **三源合一（v6.1）**：语料（BM25）、竞争池（RRF）、配置（config）全部以
      MySQL templates 表为准（TTL 30s 缓存，跨进程一致性），向量 ID（vector_id）
      对齐 MySQL 主键作为两路融合的唯一 key。修复：BM25 只含种子、RRF 只比种子、
      config 取种子等三处不同源问题。
====================================================================
"""

from __future__ import annotations

import json  # 读取种子模板 JSON（MySQL 不可用时兜底）
import logging  # 标准库日志
import time  # 模板列表 TTL 缓存
import warnings  # 控制 huggingface/torch 噪音
from pathlib import Path  # 跨平台路径处理
from typing import Any  # 泛型类型

warnings.filterwarnings("ignore", category=UserWarning)  # 抑制 huggingface 下载日志

import chromadb  # 向量库客户端（HTTP 模式连接容器）
from rank_bm25 import BM25Okapi  # BM25 关键词检索算法

from app.config import settings  # 读取应用配置（Chroma 地址等）

logger = logging.getLogger(__name__)  # 模块级日志器

# ---- jieba 分词（不可用时自动降级为字符级 n-gram） ----
try:
    import jieba  # 中文分词（BM25 用）

    _JIEBA_OK = True
except ImportError:
    _JIEBA_OK = False
    jieba = None  # 占位，后续用 _tokenize 的 fallback 分支


class HybridRetriever:
    """混合检索器：向量 + BM25 → RRF 融合 → 最佳模板。

    语料真源 = MySQL templates 表（TTL 缓存）；种子 JSON 仅作 MySQL 不可用时的兜底。
    """

    # RRF 常数：k 越大排名越平滑
    RRF_K = 60
    # 模板列表 TTL（秒）：新增/编辑模板后最多延迟该时长进入检索
    TEMPLATES_CACHE_TTL = 30.0

    def __init__(
        self,
        chroma_host: str | None = None,
        chroma_port: int | None = None,
        collection_name: str = "doc_templates",
        seed_path: str | None = None,
    ):
        """
        :param chroma_host: ChromaDB 主机地址
        :param chroma_port: ChromaDB 端口
        :param collection_name: 向量 Collection 名
        :param seed_path: seed_templates.json 路径（MySQL 兜底语料源）
        """
        # 默认从配置读取（本机为 8002，避免 8000 被其他进程占用时顶掉 Chroma）
        chroma_host = chroma_host or settings.chroma_host
        chroma_port = chroma_port or settings.chroma_port
        # 连接 ChromaDB 容器（HTTP 模式）
        self.chroma_client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
        self.collection = self.chroma_client.get_or_create_collection(collection_name)

        # 加载 BGE-M3 embedding 模型（进程内共享单例，首次自动下载 ~2GB）
        from app.services.embeddings import get_embedder

        self.embedding = get_embedder()

        # 种子路径（MySQL 不可用时的兜底语料）
        self._seed_path = seed_path or str(
            Path(__file__).parents[2] / "scripts" / "seed_templates.json"
        )
        # 模板列表缓存（None=未加载/缓存过期）
        self._templates_cache: list[dict[str, Any]] | None = None
        self._templates_ts: float = 0.0

    # ------------------------------------------------------------------
    # 模板列表加载（唯一真源：MySQL；兜底：种子 JSON）
    # ------------------------------------------------------------------

    def _load_seed_fallback(self) -> list[dict[str, Any]]:
        """MySQL 不可用时的种子兜底（结构对齐 MySQL 模板记录）。"""
        with open(self._seed_path, encoding="utf-8") as f:
            seeds: list[dict[str, Any]] = json.load(f)
        return [
            {
                "id": None,  # 种子无 MySQL 主键（避免回填不存在的 id 触发外键违约）
                "vector_id": f"tmpl_{i + 1:03d}",  # 对齐 init_chroma 灌库 ID
                "name": s["name"],
                "description": s["description"],
                "config": s["config"],
            }
            for i, s in enumerate(seeds)
        ]

    def _load_templates(self) -> list[dict[str, Any]]:
        """加载全量模板列表（MySQL 真源，TTL 缓存，失败降级种子）。

        每次加载都是"读当前 MySQL 全量"——新增/编辑/删除模板经 TTL 缓存
        周期后自动进入语料与竞争池（跨进程安全，不依赖事件通知）。

        :return: [{id, vector_id, name, description, config}, ...]
        """
        now = time.monotonic()
        if (
            self._templates_cache is not None
            and now - self._templates_ts < self.TEMPLATES_CACHE_TTL
        ):
            return self._templates_cache
        try:
            from app.crud.templates import list_templates  # 延迟导入
            from app.db import SessionLocal

            db = SessionLocal()
            try:
                rows = list_templates(db)
            finally:
                db.close()
            templates = [
                {
                    "id": t.id,
                    "vector_id": t.vector_id or f"tmpl_{t.id:03d}",
                    "name": t.name,
                    "description": t.description,
                    "config": t.config or {},
                }
                for t in rows
            ]
            if templates:  # MySQL 有数据 → 采用
                self._templates_cache = templates
                self._templates_ts = now
                return templates
            logger.warning("[rag] MySQL 模板表为空，降级种子语料")
        except Exception as exc:  # DB 未就绪 → 种子兜底
            logger.warning("[rag] 模板列表加载失败，降级种子语料: %s", exc)
        self._templates_cache = self._load_seed_fallback()
        self._templates_ts = now
        return self._templates_cache

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

    @staticmethod
    def _selected_vector_score(
        vec_entries: dict[str, tuple[int, float]], best_id: str
    ) -> float:
        """所选模板自身的向量相似度（key = vector_id，不再用数字索引）。

        融合冠军在向量路结果内 → 取自身距离换算的相似度；不在向量路 top-k →
        无相似度证据，返回 0.0（不虚报高置信）。

        :param vec_entries: {vector_id: (rank, distance)}
        :param best_id: RRF 融合冠军的 vector_id
        :return: 余弦相似度 [0, 1]
        """
        if best_id in vec_entries:
            return 1.0 - vec_entries[best_id][1]
        return 0.0

    @staticmethod
    def _rrf_select(
        tpl_by_vid: dict[str, dict[str, Any]],
        vec_ranks: dict[str, int],
        bm25_ranks: dict[str, int],
    ) -> tuple[str | None, dict[str, Any] | None, float]:
        """RRF 融合选冠军（纯函数，便于单测）。

        竞争池 = **全量模板**（含后台新增，不再限于种子）——只要在向量路
        或 BM25 路任一榜单内，就有资格参与融合。

        :param tpl_by_vid: {vector_id: 模板记录}
        :param vec_ranks: {vector_id: 向量排名}（1-based）
        :param bm25_ranks: {vector_id: BM25 排名}（1-based）
        :return: (冠军 vector_id, 冠军模板记录, rrf 得分)；空池返回 (None, None, 0.0)
        """
        rrf_scores: dict[str, float] = {}
        for vid in tpl_by_vid:
            score = 0.0
            if vid in vec_ranks:
                score += 1.0 / (HybridRetriever.RRF_K + vec_ranks[vid])  # 向量路贡献
            if vid in bm25_ranks:
                score += 1.0 / (HybridRetriever.RRF_K + bm25_ranks[vid])  # BM25 路贡献
            rrf_scores[vid] = score
        if not rrf_scores:
            return None, None, 0.0
        best_vid = max(rrf_scores, key=rrf_scores.get)
        return best_vid, tpl_by_vid[best_vid], rrf_scores[best_vid]

    def search(self, prompt: str, top_k: int = 5) -> dict[str, Any]:
        """执行混合检索，返回最佳模板及置信度。

        :param prompt: 用户自然语言需求（如"我要严谨的论文格式"）
        :param top_k: 各路召回数量（向量和 BM25 各取 top_k）
        :return: {"template_id", "template_name", "template_index", "config",
                  "vector_score", "bm25_rank", "rrf_score", "confidence",
                  "confidence_level"}
        """
        templates = self._load_templates()  # 全量模板（真源 MySQL / 兜底种子）
        # vector_id 缺失（无向量的历史模板）→ 仍可被 BM25 路召回，但无向量证据
        tpl_by_vid = {t["vector_id"]: t for t in templates if t.get("vector_id")}

        # ----- 第一路：向量语义检索 -----
        query_vec = self.embedding.encode(
            prompt, normalize_embeddings=True
        ).tolist()  # BGE-M3 向量化（归一化，配合 cosine 空间）
        vec_result = self.collection.query(
            query_embeddings=[query_vec],
            n_results=min(top_k, self.collection.count()),  # 不超过总量
            include=["documents", "distances", "metadatas"],
        )
        # 向量排名（按距离升序，距离小 = 相似度高）；key = vector_id（不再解析数字）
        vec_entries: dict[str, tuple[int, float]] = {}
        for rank, (doc_id, distance) in enumerate(
            zip(vec_result["ids"][0], vec_result["distances"][0]), start=1
        ):
            vec_entries[doc_id] = (rank, distance)
        vec_ranks = {vid: r for vid, (r, _) in vec_entries.items()}

        # ----- 第二路：BM25 关键词检索（语料 = 全量模板 description）-----
        tokens = self._tokenize(prompt)  # 分词（jieba 或字符级降级）
        corpus = [t["description"] or "" for t in templates]  # 全量语料（含新增）
        bm25 = BM25Okapi([self._tokenize(d) for d in corpus])  # 全量重建（模板量小）
        bm25_scores = bm25.get_scores(tokens)  # 每个模板的 BM25 得分
        # BM25 排名（按得分降序，key = vector_id）
        bm25_ranked = sorted(
            range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True
        )[:top_k]
        bm25_ranks: dict[str, int] = {
            templates[i]["vector_id"]: rank
            for rank, i in enumerate(bm25_ranked, start=1)
            if templates[i].get("vector_id")
        }

        # ----- RRF 融合排序（竞争池 = 全量模板，含后台新增）-----
        best_vid, best_tpl, best_score = self._rrf_select(
            tpl_by_vid, vec_ranks, bm25_ranks
        )

        # RRF 得分最高的模板（空集合防御：模板表为空 → 无冠军）
        if best_tpl is None:
            return {
                "template_id": None,
                "template_name": "",
                "template_index": None,
                "config": {},
                "vector_score": 0.0,
                "bm25_rank": None,
                "vec_rank": None,
                "rrf_score": 0.0,
                "confidence": 0.0,
                "confidence_level": "low",
            }

        # 置信度对齐**所选模板**：取融合冠军自身的向量相似度
        vector_score = self._selected_vector_score(vec_entries, best_vid)

        # ----- 置信度判定（蓝图三档） -----
        if vector_score >= 0.7:
            confidence_level = "high"
        elif vector_score >= 0.5:
            confidence_level = "medium"
        else:
            confidence_level = "low"

        return {
            "template_id": best_tpl.get("id"),  # MySQL 主键（种子兜底时为 None）
            "template_name": best_tpl["name"],
            "template_index": templates.index(best_tpl),  # 兼容字段（列表索引）
            "config": best_tpl.get("config") or {},  # 冠军自己的配置（MySQL 真源）
            "vector_score": round(vector_score, 4),
            "bm25_rank": bm25_ranks.get(best_vid),
            "vec_rank": vec_ranks.get(best_vid),
            "rrf_score": round(best_score, 6),
            "confidence": round(vector_score, 4),
            "confidence_level": confidence_level,
        }
