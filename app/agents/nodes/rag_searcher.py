"""
====================================================================
文件用途：rag_searcher —— RAG Agent 混合检索节点
====================================================================
作用：
    调用 HybridRetriever（向量 + BM25 + RRF）检索最佳模板，按三档置信度
    决策（蓝图 3.2 相似度档位）：
        ≥0.7  高置信 → 直接采用 Top-1
        0.5~0.7 中置信 → 采用 Top-1 + WARNING 日志
        <0.5  低置信 → 降级"通用标准模板"，INFO 日志，不报错
    RAG 服务整体不可用（Chroma 宕机 / embedding 下载失败）时同样降级通用模板，
    保证编排流程不中断。
依赖：
    - app.services.rag.HybridRetriever（延迟单例，避免模块导入即下载模型）
    - app.crud.templates（按名称解析 MySQL 模板 ID，兜底 seed index+1）
    - app.agents.nodes._common（notify / 日志）
====================================================================
"""

from __future__ import annotations

import json  # 读取种子模板 JSON
import logging  # 标准库日志
from pathlib import Path  # 跨平台路径
from typing import Any  # 泛型类型

from app.agents.nodes._common import notify  # 日志 + 持久化
from app.models import LogLevel, TaskStatus  # 枚举

logger = logging.getLogger(__name__)  # 模块级日志器
NODE_NAME = "rag_searcher"  # 节点名

_SEED_PATH = str(
    Path(__file__).parents[3] / "scripts" / "seed_templates.json"
)  # 种子模板 JSON
_retriever: Any | None = None  # HybridRetriever 延迟单例（首次使用才加载模型）
_seeds_cache: list[dict[str, Any]] | None = None  # 种子模板缓存


def _load_seeds() -> list[dict[str, Any]]:
    """加载种子模板列表（进程内缓存一次）。"""
    global _seeds_cache
    if _seeds_cache is None:
        with open(_SEED_PATH, encoding="utf-8") as f:
            _seeds_cache = json.load(f)
    return _seeds_cache


def _get_retriever() -> Any:
    """获取（并按需创建）混合检索器单例。

    :raises Exception: Chroma 连接失败 / embedding 模型加载失败等
    """
    global _retriever
    if _retriever is None:
        from app.services.rag import HybridRetriever  # 延迟导入（模型加载较重）

        _retriever = HybridRetriever()
    return _retriever


def _resolve_template(
    template_name: str, seed_index: int | None
) -> tuple[int | None, dict[str, Any]]:
    """解析模板主键与配置：优先按名称查 MySQL，兜底按种子索引映射。

    :param template_name: 模板名称（如"学术论文"）
    :param seed_index: 种子列表索引（0-based，对应 tmpl_001 起点）
    :return: (template_id, config)；都不可得时返回 (None, {})
    """
    try:  # 优先 MySQL（业务主数据源）
        from app.crud.templates import get_by_name  # 延迟导入
        from app.db import SessionLocal

        db = SessionLocal()
        try:
            tpl = get_by_name(db, template_name)
            if tpl is not None:
                return tpl.id, tpl.config
        finally:
            db.close()
    except Exception as exc:  # DB 未就绪 → 走种子兜底
        logger.warning("[rag_searcher] 模板查库失败，改用种子配置: %s", exc)

    # 种子兜底：仅回退 config；template_id 返回 None（DB 无对应记录时
    # 回填不存在的 id 会触发外键违约，宁缺毋假）。
    seeds = _load_seeds()
    if seed_index is not None and 0 <= seed_index < len(seeds):
        return None, seeds[seed_index]["config"]
    return None, {}


def _default_template() -> tuple[int | None, dict[str, Any], str]:
    """获取"通用标准模板"（降级兜底）：返回 (template_id, config, name)。"""
    seeds = _load_seeds()
    for idx, seed in enumerate(seeds):
        if seed.get("category") == "default":
            tpl_id, config = _resolve_template(seed["name"], idx)
            return tpl_id, config, seed["name"]
    return None, {}, "通用标准模板"


def rag_searcher_node(state: dict[str, Any]) -> dict[str, Any]:
    """RAG 检索节点：混合召回 → 三档置信度决策 → 选定模板配置。

    :param state: 当前状态（需含 user_prompt / task_id）
    :return: 状态更新（selected_template_id/config、检索记录、agent_logs、status）
    """
    prompt = state.get("user_prompt", "")
    updates: dict[str, Any] = {}
    result: dict[str, Any] | None = None  # 检索结果（供 retrieved_templates 记录）

    try:
        retriever = _get_retriever()
        result = retriever.search(prompt)  # 混合检索
        template_name = result["template_name"]
        confidence_level = result["confidence_level"]
        vector_score = result["vector_score"]

        if confidence_level == "high":
            tpl_id, config = _resolve_template(template_name, result["template_index"])
            logs = notify(
                state,
                f"模板检索命中：『{template_name}』（相似度 {vector_score:.2f}）",
                NODE_NAME,
                level=LogLevel.INFO,
                status=TaskStatus.PLANNING,
                progress=20,
                step="模板检索命中",
                template_id=tpl_id,  # 回填任务命中模板
            )
        elif confidence_level == "medium":
            tpl_id, config = _resolve_template(template_name, result["template_index"])
            logs = notify(
                state,
                f"模板检索命中：『{template_name}』（相似度 {vector_score:.2f}，匹配度一般）",
                NODE_NAME,
                level=LogLevel.WARNING,
                status=TaskStatus.PLANNING,
                progress=20,
                step="模板检索命中(匹配度一般)",
                template_id=tpl_id,
            )
        else:  # low → 降级通用模板
            tpl_id, config, default_name = _default_template()
            logs = notify(
                state,
                f"未找到高度匹配模板（相似度 {vector_score:.2f}），已应用通用标准方案『{default_name}』",
                NODE_NAME,
                level=LogLevel.INFO,
                status=TaskStatus.PLANNING,
                progress=20,
                step="应用通用标准模板",
                template_id=tpl_id,
            )
    except Exception as exc:  # RAG 整体不可用 → 降级通用模板，不报错
        logger.warning("[rag_searcher] RAG 检索不可用，降级通用模板: %s", exc)
        tpl_id, config, default_name = _default_template()
        logs = notify(
            state,
            f"RAG 检索服务不可用，已降级通用标准模板『{default_name}』",
            NODE_NAME,
            level=LogLevel.INFO,
            status=TaskStatus.PLANNING,
            progress=20,
            step="RAG 降级，应用通用模板",
            template_id=tpl_id,
        )

    # 命中计数（尽力而为，失败不影响流程）
    if tpl_id is not None:
        try:
            from app.crud.templates import increment_usage_count
            from app.db import SessionLocal

            db = SessionLocal()
            try:
                increment_usage_count(db, tpl_id)
            finally:
                db.close()
        except Exception as exc:  # 计数失败仅告警，不影响主流程
            logger.warning("[rag_searcher] 模板命中计数失败: %s", exc)

    updates["retrieved_templates"] = [result] if result is not None else []
    updates["selected_template_id"] = tpl_id
    updates["selected_template_config"] = config
    updates["agent_logs"] = logs
    updates["status"] = "planning"
    return updates
