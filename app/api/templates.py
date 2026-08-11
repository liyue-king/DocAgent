"""
====================================================================
文件用途：模板 API 路由（列表 + RAG 智能推荐）
====================================================================
接口（统一前缀 /api/v1/templates）：
    1. GET  /                  —— 模板列表（MySQL 主数据）
    2. POST /recommend         —— 用户输入行业/文档描述，RAG 匹配推送模板
    3. POST /                  —— 新增模板（仅管理员，同步向量化入库）
    4. PUT  /{template_id}     —— 编辑模板（仅管理员，覆盖更新向量）
    5. DELETE /{template_id}   —— 删除模板（仅管理员，系统内置不可删）
错误码（本模块复用既有区间）：
    1001 参数错误（描述为空 / 系统模板不可删）
    1108 无管理员权限（AuthError 转 403）
    1401 知识库不可用（Chroma/模型异常）
    2001 模板不存在
说明：
    - 推荐走 BGE-M3 向量检索：模板集合（doc_templates）为主，
      行业知识库（docagent_knowledge）为辅助来源，两者都返回给前端。
    - 相似度 0~1，前端按百分比展示；命中模板按相似度降序返回 Top-K。
====================================================================
"""

from __future__ import annotations

from typing import Annotated, Any  # 依赖注入标注

from fastapi import APIRouter, Depends  # 路由与依赖
from pydantic import BaseModel, Field  # 请求体模型
from sqlalchemy.orm import Session  # 数据库会话类型

from app.api.auth import get_current_admin  # 管理员依赖
from app.db import get_db  # 会话注入
from app.services import knowledge, template_seed  # 检索 / 向量化灌入服务
from app.services.knowledge import KnowledgeUnavailable  # 检索异常

router = APIRouter(prefix="/api/v1/templates", tags=["templates"])  # 模板路由


def _ok(**data: Any) -> dict[str, Any]:
    """成功响应：{"code":0, **data}。"""
    return {"code": 0, **data}


def _err(code: int, msg: str) -> dict[str, Any]:
    """业务错误响应：{"code":N, "msg":...}（HTTP 200）。"""
    return {"code": code, "msg": msg}


class RecommendBody(BaseModel):
    """模板推荐请求体。"""

    query: str = Field(..., min_length=1, max_length=500, description="行业/文档类型描述")
    top_k: int = Field(3, ge=1, le=10, description="返回推荐数")


class UpsertTemplateBody(BaseModel):
    """新增/编辑模板请求体（管理员）。"""

    name: str = Field(..., min_length=1, max_length=50, description="模板名称")
    description: str = Field(..., min_length=1, max_length=2000, description="语义描述（RAG 检索用）")
    config: dict[str, Any] = Field(default_factory=dict, description="样式配置 JSON")


@router.get("")
def list_templates(db: Annotated[Session, Depends(get_db)] = None) -> dict[str, Any]:
    """模板列表（按 id 升序，MySQL 主数据）。"""
    from app.crud.templates import list_templates

    rows = list_templates(db)
    return _ok(
        templates=[
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "vector_id": t.vector_id,
                "usage_count": t.usage_count,
            }
            for t in rows
        ]
    )


@router.post("/recommend")
def recommend(body: RecommendBody) -> dict[str, Any]:
    """RAG 智能推荐：用户输入 → 向量检索模板/知识库 → 推送 Top-K。"""
    query = body.query.strip()
    if not query:
        return _err(1001, "参数错误：请描述你的行业或文档类型")
    try:
        # 主路：模板集合检索；辅路：行业知识库检索
        template_hits = knowledge.search_templates(query, top_k=max(body.top_k, 8))
        knowledge_hits = knowledge.search(query, top_k=5)
    except KnowledgeUnavailable as exc:
        return _err(1401, f"模板推荐暂不可用：{exc}")

    if not template_hits:
        return _ok(recommendations=[], sources=[], msg="知识库暂无模板数据，请先完成模板灌库")

    # 关联 MySQL 模板 ID（用于前端“使用此模板”跳转）
    db = next(get_db())
    try:
        from app.crud.templates import get_by_name

        for hit in template_hits:
            tpl = get_by_name(db, hit.get("template_name") or hit.get("title") or "")
            hit["template_id"] = tpl.id if tpl else None
    finally:
        db.close()

    recommendations = [
        {
            "template_id": h.get("template_id"),
            "template_name": h.get("template_name") or h.get("title") or "",
            "category": h.get("category") or "",
            "description": h.get("content") or "",
            "score": h.get("score", 0),
        }
        for h in template_hits[: body.top_k]
    ]
    return _ok(recommendations=recommendations, sources=knowledge_hits)


def _serialize(t: Any) -> dict[str, Any]:
    """模板脱敏序列化。"""
    return {
        "id": t.id,
        "name": t.name,
        "description": t.description,
        "config": t.config,
        "vector_id": t.vector_id,
        "is_system": bool(t.is_system),
        "usage_count": t.usage_count,
    }


@router.post("")
def create_template(
    body: UpsertTemplateBody,
    _admin: Annotated[Any, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)] = None,
) -> dict[str, Any]:
    """新增模板：flush 拿 id → 向量化 upsert → 提交（向量化失败整体回滚）。"""
    from app.models import Template

    tpl = Template(
        name=body.name.strip(),
        description=body.description.strip(),
        config=body.config,
        is_system=False,
    )
    db.add(tpl)
    db.flush()  # 拿到自增 id（未提交，可回滚）
    vector_id = f"tmpl_{tpl.id:03d}"  # 向量 ID 对齐 MySQL 主键
    try:
        template_seed.upsert_vector(tpl.name, tpl.description, vector_id)
    except KnowledgeUnavailable as exc:
        db.rollback()  # 向量化失败 → 回滚 MySQL 创建，保证两侧一致
        return _err(1401, f"模板保存失败（向量库不可用）：{exc}")
    tpl.vector_id = vector_id
    db.commit()
    db.refresh(tpl)
    return _ok(template=_serialize(tpl), msg="模板创建成功")


@router.put("/{template_id}")
def update_template(
    template_id: int,
    body: UpsertTemplateBody,
    _admin: Annotated[Any, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)] = None,
) -> dict[str, Any]:
    """编辑模板：先向量化新内容（upsert 覆盖），成功后再提交 MySQL。"""
    from app.crud.templates import get_template
    from app.crud.templates import update_template as tpl_update

    tpl = get_template(db, template_id)
    if tpl is None:
        return _err(2001, "模板不存在")
    vector_id = tpl.vector_id or f"tmpl_{tpl.id:03d}"  # 存量模板补齐向量 ID
    try:
        template_seed.upsert_vector(body.name.strip(), body.description.strip(), vector_id)
    except KnowledgeUnavailable as exc:
        return _err(1401, f"模板保存失败（向量库不可用）：{exc}")
    tpl = tpl_update(
        db,
        template_id,
        name=body.name.strip(),
        description=body.description.strip(),
        config=body.config,
    )
    if tpl is not None and not tpl.vector_id:  # 回填补齐的向量 ID
        tpl.vector_id = vector_id
        db.commit()
        db.refresh(tpl)
    return _ok(template=_serialize(tpl), msg="模板更新成功")


@router.delete("/{template_id}")
def delete_template(
    template_id: int,
    _admin: Annotated[Any, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)] = None,
) -> dict[str, Any]:
    """删除模板：系统内置拒绝；删除 MySQL 行 + 尽力清理向量。"""
    from app.crud.templates import delete_template as tpl_delete
    from app.crud.templates import get_template

    tpl = get_template(db, template_id)
    if tpl is None:
        return _err(2001, "模板不存在")
    if tpl.is_system:
        return _err(1001, "系统内置模板不可删除")
    if tpl.vector_id:
        template_seed.delete_vector(tpl.vector_id)  # 失败仅告警，不影响主数据
    tpl_delete(db, template_id)
    return _ok(msg="模板已删除")
