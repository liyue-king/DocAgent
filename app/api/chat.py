"""
====================================================================
文件用途：AI 助手聊天 + 知识库上传 API 路由
====================================================================
接口（统一前缀 /api/v1）：
    1. POST /chat        —— 聊天机器人：RAG 检索行业→模板知识 + qwen 生成回答
    2. POST /rag/upload  —— 【仅管理员】上传平台知识文档 → 切块向量化入库
    3. GET  /rag/stats   —— 【仅管理员】平台知识库统计（总片段数 + 分类分布）
错误码（本模块新增区间 14xx）：
    1401 知识库不可用（Chroma/模型异常）  1402 LLM 不可用
说明：
    - 聊天开放访问（游客可体验）；登录用户会额外检索自己的知识库。
    - 用户自定义知识库（/api/v1/knowledge）与平台知识库相互独立。
    - 聊天回答附带 sources（检索到的知识片段），前端可展示引用。
====================================================================
"""

from __future__ import annotations

import logging  # 标准库日志
from typing import Annotated, Any  # 依赖注入标注

from fastapi import APIRouter, Depends, File, Form, UploadFile  # 路由与依赖
from pydantic import BaseModel, Field  # 请求体模型

from app.api.auth import get_current_admin, get_current_user_optional  # 认证依赖
from app.services import knowledge  # 知识库服务
from app.services.knowledge import KnowledgeUnavailable  # 知识库异常
from app.services.llm import LlmUnavailable, chat_text  # LLM 服务

logger = logging.getLogger(__name__)  # 模块级日志器

router = APIRouter(prefix="/api/v1", tags=["chat"])  # 聊天路由


def _ok(**data: Any) -> dict[str, Any]:
    """成功响应：{"code":0, **data}。"""
    return {"code": 0, **data}


def _err(code: int, msg: str) -> dict[str, Any]:
    """业务错误响应：{"code":N, "msg":...}（HTTP 200）。"""
    return {"code": code, "msg": msg}


class ChatBody(BaseModel):
    """聊天请求体。"""

    message: str = Field(..., min_length=1, max_length=2000, description="用户问题")


@router.post("/chat")
def chat(
    body: ChatBody,
    user: Annotated[Any | None, Depends(get_current_user_optional)] = None,
) -> dict[str, Any]:
    """聊天机器人：个人知识库 + 平台知识库检索 → 拼装上下文 → qwen 生成回答。"""
    message = body.message.strip()
    if not message:
        return _err(1001, "参数错误：消息不能为空")

    # ---- 1. RAG 检索（个人知识库 + 平台知识库 + 模板集合三路召回）----
    try:
        hits = knowledge.search(message, top_k=4)
        template_hits = knowledge.search_templates(message, top_k=3)
        user_hits = (
            knowledge.search_user(message, user_id=user.id, top_k=4)
            if user is not None
            else []
        )
    except KnowledgeUnavailable as exc:
        return _err(1401, f"知识库检索失败：{exc.msg if hasattr(exc, 'msg') else exc}")

    if not user_hits and not hits and not template_hits:
        return _ok(
            answer="还没有可参考的知识。你可以在「我的知识库」上传自己的文档，"
            "或等待管理员维护平台知识库，我才能结合文档准确回答。",
            sources=[],
        )

    # ---- 2. 拼装参考上下文 ----
    context_parts: list[str] = []
    for h in user_hits:
        context_parts.append(
            f"[我的知识库·{h['title']}（分类：{h['category'] or '未分类'}）] {h['content']}"
        )
    for h in hits:
        context_parts.append(
            f"[平台知识库·{h['title']}（分类：{h['category'] or '未分类'}）] {h['content']}"
        )
    for t in template_hits:
        context_parts.append(
            f"[模板·{t['template_name'] or t['title']}（分类：{t['category'] or '未分类'}）] {t['content']}"
        )

    system_prompt = (
        "你是 DocAgent 的模板推荐助手，负责根据用户描述的行业/文档类型，"
        "推荐最合适的排版模板，并简要说明模板的格式要点。\n"
        "回答规范：\n"
        "1. 只依据下方“参考资料”中的内容回答，不要编造参考资料里没有的模板。\n"
        "2. 先直接给出推荐模板名称，再列出 2-4 条格式要点。\n"
        "3. 用户自己的知识库（我的知识库）优先于平台知识库，回答时可优先采用。\n"
        "4. 若参考资料不足以回答，如实说明，并建议用户补充自己的文档。\n"
        "5. 用简洁、友好的中文回答，必要时使用短列表。"
    )
    user_prompt = f"用户问题：{message}\n\n参考资料：\n" + "\n".join(context_parts)

    # ---- 3. LLM 生成回答 ----
    try:
        resp = chat_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.3,
            max_retries=1,
            timeout=60.0,
        )
    except LlmUnavailable as exc:
        logger.warning("[chat] LLM 不可用: %s", exc)
        return _err(1402, "AI 服务暂不可用，请稍后再试")

    return _ok(answer=resp["content"], sources=user_hits + hits + template_hits)


@router.post("/rag/upload")
async def upload_knowledge(
    title: Annotated[str, Form()],
    file: Annotated[UploadFile | None, File()] = None,
    content: Annotated[str, Form()] = "",
    category: Annotated[str, Form()] = "其他",
    template_name: Annotated[str, Form()] = "",
    _admin: Annotated[Any, Depends(get_current_admin)] = None,
) -> dict[str, Any]:
    """【仅管理员】上传平台知识文档：文本抽取 → 切块 → 向量化入库。

    multipart/form-data：
        title          必填，文档标题
        file           可选，.docx/.txt/.md 文件
        content        可选，直接粘贴文本（file 为空时使用）
        category       可选，行业/分类（如"教育"、"商务"）
        template_name  可选，关联模板名
    """
    title = title.strip()
    if not title:
        return _err(1001, "参数错误：请填写文档标题")

    # ---- 1. 文本来源：文件优先，其次粘贴文本 ----
    data: bytes | None = None
    if file is not None and file.filename:
        data = await file.read()
        if len(data) > 5 * 1024 * 1024:  # 5MB 上限
            return _err(1002, "文件过大：知识文档最大 5MB")
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

    # ---- 2. 切块向量化 ----
    try:
        ids, chunk_count = knowledge.add_document(
            title=title,
            category=category.strip() or "其他",
            text=text,
            template_name=template_name.strip() or None,
            source="admin",
        )
    except KnowledgeUnavailable as exc:
        return _err(1401, str(exc))
    if chunk_count == 0:
        return _err(1401, "文档未能切分出有效片段，请检查内容")

    # ---- 3. 原文备份 MinIO（失败不阻断）----
    minio_key = None
    if data is not None and raw_name:
        minio_key = knowledge.store_original(raw_name, data)

    return _ok(
        doc_id=ids[0],
        title=title,
        category=category.strip() or "其他",
        chunks=chunk_count,
        minio_key=minio_key,
        msg=f"文档已向量化入库（{chunk_count} 个片段）",
    )


@router.get("/rag/stats")
def knowledge_stats(
    _admin: Annotated[Any, Depends(get_current_admin)] = None,
) -> dict[str, Any]:
    """【仅管理员】平台知识库统计：总片段数 + 分类分布。"""
    try:
        return _ok(**knowledge.stats())
    except KnowledgeUnavailable as exc:
        return _err(1401, str(exc))
