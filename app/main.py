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

from contextlib import asynccontextmanager  # FastAPI lifespan（进程生命周期钩子）
from typing import Annotated  # 依赖注入标注

from fastapi import Depends, FastAPI, Request  # Web 框架
from fastapi.middleware.cors import CORSMiddleware  # 跨域中间件
from fastapi.responses import JSONResponse, PlainTextResponse  # 异常/指标响应
from sqlalchemy.orm import Session  # 指标端点会话类型

from app.api.admin import router as admin_router  # 管理员路由（/api/v1/admin/*）
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
from app.db import get_db  # 指标聚合会话
from app.dev_processes import (  # 开发态随网关自动拉起 Celery
    start_dev_beat,
    start_dev_worker,
    stop_dev_process,
)
from app.logging_setup import setup_logging  # loguru 统一日志
from app.services import metrics  # Prometheus 指标
from app.services.security import AuthError  # 认证异常

setup_logging()  # 日志先行：后续 import 的模块日志统一走 loguru


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """进程生命周期钩子：开发态随网关拉起/回收 Celery（.env 开关控制）。"""
    worker = start_dev_worker()  # AUTO_START_WORKER=true 时自动拉起
    beat = start_dev_beat()  # AUTO_START_BEAT=true 时自动拉起
    yield
    stop_dev_process(beat, "celery_beat")
    stop_dev_process(worker, "celery_worker")


# FastAPI 应用实例（uvicorn 入口：app.main:app）
app = FastAPI(
    title="DocAgent API", version="0.1.0", description="DocAgent 文档智能排版平台",
    lifespan=lifespan,
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
app.include_router(admin_router)  # 注册 /api/v1/admin/*
app.include_router(chat_router)  # 注册 /api/v1/chat + /api/v1/rag/*
app.include_router(knowledge_router)  # 注册 /api/v1/knowledge/*
app.include_router(pay_router)  # 注册 /api/v1/pay/*
app.include_router(templates_router)  # 注册 /api/v1/templates/*
app.include_router(router)  # 注册 /api/v1 业务接口


@app.get("/metrics", include_in_schema=False)
def metrics_endpoint(
    db: Annotated[Session, Depends(get_db)] = None,
) -> PlainTextResponse:
    """Prometheus 指标（无认证，供抓取器轮询）。"""
    try:
        text = metrics.metrics_text(db)
    except Exception:  # 数据库短暂不可用 → 503（Prometheus 标记抓取失败）
        db.rollback()
        return PlainTextResponse(
            "# docagent_metrics unavailable: database down\n", status_code=503
        )
    return PlainTextResponse(text, media_type="text/plain; version=0.0.4")


@app.exception_handler(AuthError)
async def auth_error_handler(_request: Request, exc: AuthError) -> JSONResponse:
    """认证异常全局处理器：未登录返回 401，无权限（1108）返回 403。"""
    status_code = 403 if exc.code == 1108 else 401
    return JSONResponse(status_code=status_code, content={"code": exc.code, "msg": exc.msg})
