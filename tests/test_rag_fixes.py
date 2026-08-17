"""RAG 修复回归：三源合一（语料/竞争池/config 以 MySQL 为真源）+ 置信度对齐。"""

from __future__ import annotations

from app.agents.nodes.rag_searcher import _extract_prompt_template_name
from app.services.rag import HybridRetriever

# ==================== 置信度对齐所选模板 ====================


def test_selected_vector_score_uses_selected_template() -> None:
    """bug 6：置信度取融合冠军自身距离（向量路 top-1 与冠军不一致时不错位）。"""
    # 向量路 top-1 是 tmpl_001（距离 0.1），但 RRF 冠军是 tmpl_002（距离 0.35）
    vec_entries = {"tmpl_001": (1, 0.10), "tmpl_002": (2, 0.35)}
    assert HybridRetriever._selected_vector_score(vec_entries, "tmpl_002") == 0.65
    # 冠军 = 向量 top-1 时正常
    assert HybridRetriever._selected_vector_score(vec_entries, "tmpl_001") == 0.90


def test_selected_vector_score_no_evidence_is_zero() -> None:
    """bug 6：融合冠军不在向量路 top-k → 无证据记 0.0（不虚报高置信）。"""
    vec_entries = {"tmpl_001": (1, 0.10)}
    assert HybridRetriever._selected_vector_score(vec_entries, "tmpl_009") == 0.0


# ==================== 三源合一：竞争池含新增模板 ====================


def _tpl(vid: str, name: str, config: dict | None = None) -> dict:
    return {"id": 1, "vector_id": vid, "name": name, "description": "", "config": config or {}}


def test_rrf_new_template_has_qualification() -> None:
    """漏洞②：新增模板（tmpl_011）进入竞争池，向量+BM25 综合证据足够时夺冠。"""
    tpls = {
        "tmpl_001": _tpl("tmpl_001", "种子模板A"),
        "tmpl_011": _tpl("tmpl_011", "后台新增模板"),
    }
    # 新增模板：向量 rank1 + BM25 rank2；种子：向量 rank2 + BM25 rank3
    vec_ranks = {"tmpl_011": 1, "tmpl_001": 2}
    bm25_ranks = {"tmpl_011": 2, "tmpl_001": 3}
    best_vid, best_tpl, _score = HybridRetriever._rrf_select(tpls, vec_ranks, bm25_ranks)
    assert best_vid == "tmpl_011"
    assert best_tpl["name"] == "后台新增模板"
    # 修正前：循环 range(len(种子))，tmpl_011 根本不在池子里 → 种子赢


def test_rrf_winner_carries_own_config() -> None:
    """漏洞③：冠军 config 取自其自身记录（不再回退种子/按名回查错位）。"""
    new_config = {"paragraph_styles": {"normal": {"font_name": "新模板字体"}}}
    tpls = {
        "tmpl_001": _tpl("tmpl_001", "种子模板", {"paragraph_styles": {"a": 1}}),
        "tmpl_011": _tpl("tmpl_011", "新增模板", new_config),
    }
    vec_ranks = {"tmpl_011": 1}
    bm25_ranks = {"tmpl_011": 1}
    _, best_tpl, _ = HybridRetriever._rrf_select(tpls, vec_ranks, bm25_ranks)
    assert best_tpl["config"] == new_config  # 冠军自己的配置


def test_rrf_vector_only_new_template_beats_weak_seed() -> None:
    """漏洞②补充：新增模板仅向量路 top1，也赢过"向量不在榜"的种子。"""
    tpls = {
        "tmpl_001": _tpl("tmpl_001", "种子模板A"),
        "tmpl_011": _tpl("tmpl_011", "后台新增模板"),
    }
    vec_ranks = {"tmpl_011": 1}  # 只有新增模板进向量榜
    bm25_ranks = {"tmpl_001": 1}  # 种子 BM25 第 1
    _best_vid, _best_tpl, _ = HybridRetriever._rrf_select(tpls, vec_ranks, bm25_ranks)
    # 新增：1/61 ≈ 0.0164；种子：1/61 ≈ 0.0164（并列时 max 取先插入者——种子先入 dict）
    # 构造差异：让种子 BM25 rank2，新增向量 rank1 → 新增 1/61=0.01639 vs 种子 1/62=0.01613
    vec_ranks2 = {"tmpl_011": 1}
    bm25_ranks2 = {"tmpl_001": 2}
    best_vid2, _, _ = HybridRetriever._rrf_select(tpls, vec_ranks2, bm25_ranks2)
    assert best_vid2 == "tmpl_011"


def test_rrf_empty_pool_is_safe() -> None:
    """空模板池 → 返回 (None, None, 0)，search 走 low 降级路径不崩溃。"""
    best_vid, best_tpl, score = HybridRetriever._rrf_select({}, {}, {})
    assert (best_vid, best_tpl, score) == (None, None, 0.0)


# ==================== 种子兜底结构 ====================


def test_seed_fallback_keeps_vector_id_alignment() -> None:
    """MySQL 不可用时：种子兜底结构含 vector_id（tmpl_00X 对齐灌库 ID）。"""
    retriever = object.__new__(HybridRetriever)  # 跳过 __init__（不连 Chroma）
    retriever._seed_path = "scripts/seed_templates.json"
    templates = retriever._load_seed_fallback()
    assert len(templates) >= 1
    assert templates[0]["vector_id"] == "tmpl_001"  # 与 init_chroma 灌库 ID 一致
    assert templates[0]["id"] is None  # 种子无 MySQL 主键
    assert templates[0]["config"]  # 配置可用


# ==================== 提示词模板名提取 ====================


def test_extract_prompt_template_name_with_format_kw() -> None:
    """bug 12：按 XXX 格式排版也能点名模板（不再强制要求"模板"二字）。"""
    assert _extract_prompt_template_name("请按学术论文格式排版") == "学术论文"
    assert _extract_prompt_template_name("按「毕业论文」模板排版") == "毕业论文"
    assert _extract_prompt_template_name("用「商业计划书」的格式做") == "商业计划书"


def test_extract_prompt_template_name_no_match() -> None:
    """无点名模板 → 空串（走 RAG 混合检索）。"""
    assert _extract_prompt_template_name("请帮我排版一下这份文档") == ""
    assert _extract_prompt_template_name("") == ""
