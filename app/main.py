"""
====================================================================
文件用途：DocAgent API 网关入口（FastAPI 应用）
====================================================================
作用：
    组装 FastAPI 应用：CORS 中间件（Vue3 前端跨域调试）+ API 路由注册。
    启动命令：uv run uvicorn app.main:app --port 8000
依赖：
    - fastapi / uvicorn
    - app.api.routes（/api/v1 四接口）
说明：
    - CORS 全放开仅限开发调试（蓝图 10.1 Chroma 亦如此）；生产需收敛为白名单。
    - 业务错误返回 HTTP 200 + {"code":N}，限流返回 429（详见 routes.py）。
====================================================================
"""

from __future__ import annotations

from fastapi import FastAPI, Request  # Web 框架
from fastapi.middleware.cors import CORSMiddleware  # 跨域中间件
from fastapi.responses import JSONResponse  # 认证异常响应

from app.api.auth import router as auth_router  # 认证路由（/api/v1/auth/*）
from app.api.chat import (  # 聊天/知识库路由（/api/v1/chat、/api/v1/rag/*）
    router as chat_router,
)
from app.api.knowledge import (
    router as knowledge_router,  # 我的知识库（/api/v1/knowledge）
)
from app.api.pay import router as pay_router  # 支付路由（/api/v1/pay/*）
from app.api.routes import router  # API 路由（/api/v1/*）
from app.api.templates import (  # 模板路由（/api/v1/templates/*）
    router as templates_router,
)
from app.config import settings  # 应用配置（CORS 等）
from app.services.security import AuthError  # 认证异常

# FastAPI 应用实例（uvicorn 入口：app.main:app）
app = FastAPI(
    title="DocAgent API", version="0.1.0", description="DocAgent 文档智能排版平台"
)

cors_allow_origins = [
    origin.strip() for origin in settings.cors_allow_origins.split(",") if origin.strip()
]

# CORS：前端 Vue3 开发服务器跨域访问（生产环境应收敛为白名单）
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins,  # 开发期默认 *，生产通过 .env 白名单化
    allow_credentials=False,  # 全放开时不能携带凭据（与 allow_origins=["*"] 兼容）
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)  # 注册 /api/v1/auth/*
app.include_router(chat_router)  # 注册 /api/v1/chat + /api/v1/rag/*
app.include_router(knowledge_router)  # 注册 /api/v1/knowledge/*
app.include_router(pay_router)  # 注册 /api/v1/pay/*
app.include_router(templates_router)  # 注册 /api/v1/templates/*
app.include_router(router)  # 注册 /api/v1 业务接口

from fastapi_mcp import FastApiMCP  # MCP 工具暴露（需在路由注册后构造）

# 文件上传/下载接口无法经 MCP JSON 传输调用（multipart 上传 / 二进制下载），排除，前端仍走 HTTP
_MCP_EXCLUDE_OPERATIONS = [
    "process_upload_api_v1_process_post",
    "upload_my_doc_api_v1_knowledge_post",
    "upload_knowledge_api_v1_rag_upload_post",
    "download_result_api_v1_download__task_id__get",
]

mcp = FastApiMCP(
    app,
    name="DocAgent API MCP",
    description="DocAgent 文档智能排版平台 API 工具集（任务/模板/知识库/支付/认证）",
    exclude_operations=_MCP_EXCLUDE_OPERATIONS,
)
mcp.mount_http()  # 挂载到自身 app，路径 /mcp（Streamable HTTP transport）


@app.exception_handler(AuthError)
async def auth_error_handler(_request: Request, exc: AuthError) -> JSONResponse:
    """认证异常全局处理器：未登录返回 401，无权限（1108）返回 403。"""
    status_code = 403 if exc.code == 1108 else 401
    return JSONResponse(status_code=status_code, content={"code": exc.code, "msg": exc.msg})
