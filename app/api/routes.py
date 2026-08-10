"""
====================================================================
文件用途：API 网关路由（蓝图 7 API 接口契约）
====================================================================
作用：
    实现四个接口（统一前缀 /api/v1）：
        1. POST   /process            —— 上传 .docx + prompt → 存 MinIO →
                                          写 MySQL(pending) → 投递 Celery
        2. GET    /task/{task_id}     —— 轮询状态/进度/步骤/日志（Redis 优先）
        3. GET    /download/{task_id} —— 302 重定向 MinIO 预签名 URL（5 分钟）
        4. GET    /health             —— 四服务健康探测
    统一错误码（蓝图 7.2）：0/1001/1002/1003/2001/2002/3001/4001/4002/4003/429。
依赖：
    - app.services.storage（MinIO 上传/预签名）
    - app.services.task_cache（Redis db=2 快照 + IP 限流）
    - app.crud.tasks / agent_logs / users（数据层）
    - app.tasks.process_document_task（Celery 任务投递）
说明：
    - 业务错误返回 HTTP 200 + {"code":N,"msg":...}；限流返回 HTTP 429。
    - 限流仅作用于 POST /process（前端轮询 2s/次 = 30 次/分 > 限流上限，
      若全局限流会误伤轮询）。
    - 全部使用同步 def 路由（FastAPI 线程池执行），DB/MinIO/Redis 均为同步 IO。
====================================================================
"""

from __future__ import annotations

import hashlib  # 文件内容哈希（input_file_hash）
import logging  # 标准库日志
import os  # 本地输出路径判断
import uuid  # 任务 UUID 生成
from typing import Annotated, Any  # 泛型类型 / FastAPI 依赖注入标注

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy import text  # 健康检查 SELECT 1
from sqlalchemy.orm import Session  # 数据库会话类型

from app.agents.nodes._common import build_object_key  # 对象 Key 生成（蓝图 5.3）
from app.api.auth import (  # 登录依赖
    get_current_user,
    get_current_user_optional,
)
from app.config import settings  # 桶名 / 大小限制 / 限流上限
from app.db import get_db  # FastAPI 会话注入
from app.models import LogLevel, TaskStatus, User  # 枚举与用户模型
from app.services import task_cache  # Redis 快照 / 限流
from app.services.storage import StorageUnavailable, storage  # MinIO 客户端

logger = logging.getLogger(__name__)  # 模块级日志器
router = APIRouter(prefix="/api/v1")  # 统一接口前缀

# 终态集合（惰性过期判定 / 下载准入共用）
_TERMINAL_STATUS = {TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.EXPIRED}


def _ok(**data: Any) -> dict[str, Any]:
    """成功响应：{"code":0, **data}（蓝图 7.1 契约）。"""
    return {"code": 0, **data}


def _err(code: int, msg: str) -> dict[str, Any]:
    """业务错误响应：{"code":N, "msg":...}（HTTP 200，蓝图 7.2 错误码）。"""
    return {"code": code, "msg": msg}


def _ensure_not_expired(db: Any, task: Any) -> bool:
    """惰性过期判定：非终态且超过 24h 生命周期 → 置 EXPIRED。

    :param db: 数据库会话
    :param task: tasks 表记录
    :return: True=已过期（调用方应返回 3001），False=未过期
    """
    if task.status == TaskStatus.EXPIRED:
        return True  # 已置过期 → 恒判过期（3001，而非落到 2002）
    if task.status in _TERMINAL_STATUS:
        return False  # SUCCESS/FAILED 终态不再过期
    from datetime import datetime  # 本地时间（与 MySQL CURRENT_TIMESTAMP 对齐）

    if task.expires_at and task.expires_at < datetime.now():
        from app.crud.tasks import mark_expired

        mark_expired(db, task.id)  # 状态置 expired（前端停止轮询）
        return True
    return False


@router.post("/process")
def process_upload(
    file: Annotated[UploadFile, File()],  # 上传的 .docx 文件
    prompt: Annotated[str, Form()] = "",  # 用户自然语言需求
    request: Request = None,  # 客户端 IP（限流）
    db: Annotated[Session, Depends(get_db)] = None,
    user: Annotated[User | None, Depends(get_current_user_optional)] = None,
) -> Any:
    """上传处理：校验 → 存 MinIO → 写 MySQL → 投递 Celery。

    :param file: .docx 文件（multipart/form-data）
    :param prompt: 用户需求文本
    :return: {"code":0,"task_id":"uuid","msg":"任务已提交"} 或错误码
    """
    # ---- 1. IP 限流（10 次/分，Redis INCR 计数，失败放行）----
    if request is not None and task_cache.is_rate_limited(request.client.host):
        return JSONResponse(
            status_code=429, content=_err(429, "请求过于频繁，请稍后再试")
        )

    # ---- 2. 参数校验（蓝图 7.2 错误码）----
    if file is None or not prompt.strip():  # 未传文件 / prompt 为空
        return _err(1001, "参数错误：请上传文件并提供处理需求")
    if not (file.filename or "").lower().endswith(".docx"):  # 非 .docx
        return _err(1003, "文件格式不支持：仅支持 .docx")
    # 文件名消毒：防路径穿越（Worker 用 os.path.join 拼接本地路径，
    # 含 ../ 或 ..\ 的文件名会写出临时目录到任意可写路径）
    safe_name = os.path.basename((file.filename or "").replace("\\", "/")).strip()
    if not safe_name:
        return _err(1003, "文件格式不支持：文件名为空")
    data = file.file.read()  # 同步读取上传字节（线程池内执行）
    if len(data) > settings.max_file_size_mb * 1024 * 1024:  # 超 20MB
        return _err(1002, f"文件大小超限：最大 {settings.max_file_size_mb}MB")

    # ---- 3. 构建任务元数据 + 存 MinIO ----
    task_id = str(uuid.uuid4())  # 任务 UUID（与 Celery task_id 一致）
    file_hash = hashlib.sha256(data).hexdigest()  # 内容哈希（去重/校验）
    key = build_object_key(task_id, safe_name)  # {y}/{m}/{d}/{task_id}/{文件名}
    try:
        storage.upload_bytes(
            data, bucket=settings.minio_input_bucket, key=key
        )  # 输入入库
    except StorageUnavailable as exc:  # MinIO 宕机 → 4001
        logger.error("[process] MinIO 上传失败: %s", exc)
        return _err(4001, f"内部错误：文件存储不可用（{exc}）")

    # ---- 4. 写 MySQL（pending）----
    try:
        from app.crud.tasks import create_task
        from app.crud.users import deduct_credit, get_or_create_anonymous

        owner = user or get_or_create_anonymous(db)  # 登录用户优先，游客走匿名
        # 登录用户提交任务前校验额度（游客 999 次不受影响）
        if owner.id != 1 and owner.credits_balance < 1:
            return _err(1005, "积分不足，请前往定价页购买套餐")
        create_task(
            db,
            task_id=task_id,
            prompt_text=prompt.strip(),
            input_file_name=safe_name,
            input_file_hash=file_hash,
            input_file_path=key,
            user_id=owner.id,
        )
        # 登录用户提交任务扣 1 次额度（游客 999 次不受影响）
        if owner.id != 1:
            deduct_credit(db, owner.id, 1)
    except Exception as exc:  # DB 异常 → 4001（文件已入库，任务不可见）
        logger.error("[process] 任务创建失败: %s", exc)
        return _err(4001, f"内部错误：任务创建失败（{exc}）")

    # ---- 5. 投递 Celery（失败 → 置 failed，不留幻影 PENDING）----
    try:
        from app.tasks import process_document_task  # 延迟导入（避免网关启动耦合）

        process_document_task.apply_async(
            args=[task_id], task_id=task_id
        )  # 任务 ID 对齐
    except Exception as exc:  # Broker 宕机 → 标记失败
        logger.error("[process] Celery 投递失败: %s", exc)
        try:
            from app.crud.agent_logs import add_log
            from app.crud.tasks import mark_failed

            mark_failed(db, task_id)
            add_log(
                db,
                task_id=task_id,
                agent_node="api_gateway",
                message=f"任务投递失败：{exc}",
                level=LogLevel.ERROR,
            )
        except Exception as exc2:  # 二次失败仅告警
            logger.warning("[process] 失败标记写入异常: %s", exc2)
        return _err(4001, "内部错误：任务调度不可用，请稍后再试")

    return _ok(task_id=task_id, msg="任务已提交")


@router.get("/tasks")
def list_my_tasks(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)] = None,
    limit: int = 50,
    offset: int = 0,
) -> Any:
    """我的任务列表（新→旧，供前端 HistoryView 使用）。"""
    from app.crud.tasks import list_tasks_by_user

    tasks = list_tasks_by_user(db, user.id, limit=limit, offset=offset)
    return _ok(
        tasks=[
            {
                "id": t.id,
                "prompt_text": t.prompt_text,
                "input_file_name": t.input_file_name,
                "status": t.status.value,
                "progress": t.progress,
                "current_step": t.current_step,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "expires_at": t.expires_at.isoformat() if t.expires_at else None,
            }
            for t in tasks
        ]
    )


@router.get("/task/{task_id}")
def get_task_status(
    task_id: str, db: Annotated[Session, Depends(get_db)] = None
) -> Any:
    """轮询任务状态：Redis 快照优先，miss 降级 MySQL 并回填。

    :param task_id: 任务 UUID
    :return: {"code":0,"status","progress","step","logs","download_url"} 或错误码
    """
    # ---- 1. 任务存在性 + 惰性过期 ----
    from app.crud.tasks import get_task

    task = get_task(db, task_id)
    if task is None:
        return _err(2001, "任务不存在或已过期")
    if _ensure_not_expired(db, task):
        return _err(3001, "任务已过期（超过 24 小时生命周期）")
    from app.crud.agent_logs import list_logs

    # ---- 2. 优先读 Redis 快照（蓝图 7.3 轮询协议）----
    snapshot = task_cache.get_snapshot(task_id)
    if snapshot is not None:
        status = snapshot["status"]
        progress = snapshot["progress"]
        step = snapshot["step"]
        logs = snapshot["logs"] or [  # 日志缺失 → MySQL 补（ORM → 纯文本）
            log.log_message for log in list_logs(db, task_id)
        ]
    else:  # Redis 未命中 → 降级 MySQL 并回填
        status = task.status.value
        progress = task.progress
        step = task.current_step
        logs = [log.log_message for log in list_logs(db, task_id)]  # 与缓存格式一致
        task_cache.backfill(
            task_id, status=status, progress=progress, step=step, logs=logs
        )

    # ---- 3. 成功时附下载地址（5 分钟预签名 URL）----
    download_url: str | None = None
    if status == TaskStatus.SUCCESS.value and task.output_file_path:
        if os.path.exists(task.output_file_path):  # MinIO 上传失败 → 本地文件兜底
            download_url = f"/api/v1/download/{task_id}"  # 走本地文件流
        else:  # 正常路径：预签名 URL
            try:
                download_url = storage.presign_url(
                    task.output_file_path, bucket=settings.minio_output_bucket
                )
            except Exception as exc:  # MinIO 不可用 → 降级本地下载
                logger.warning("[task] 预签名生成失败，降级本地下载: %s", exc)
                download_url = f"/api/v1/download/{task_id}"

    return _ok(
        status=status,
        progress=progress,
        step=step,
        logs=logs,
        download_url=download_url,
    )


@router.get("/download/{task_id}")
def download_result(
    task_id: str, db: Annotated[Session, Depends(get_db)] = None
) -> Any:
    """下载处理结果：302 重定向 MinIO 预签名 URL（或本地文件流）。

    :param task_id: 任务 UUID
    :return: 302 重定向 / FileResponse / 错误码
    """
    from app.crud.tasks import get_task

    task = get_task(db, task_id)
    if task is None:
        return _err(2001, "任务不存在或已过期")
    if _ensure_not_expired(db, task):
        return _err(3001, "任务已过期（超过 24 小时生命周期）")
    # 仅 SUCCESS/FAILED 且留有结果才可下载（蓝图 §9：失败也保留结果供下载）
    if not task.output_file_path or task.status not in (
        TaskStatus.SUCCESS,
        TaskStatus.FAILED,
    ):
        return _err(2002, "状态不允许该操作：任务尚未完成")

    # ---- 本地路径（MinIO 上传失败兜底）→ 直接返回文件流 ----
    if os.path.exists(task.output_file_path):
        return FileResponse(
            task.output_file_path,
            filename=os.path.basename(task.output_file_path),  # modified_xxx.docx
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    # ---- 正常路径：302 → MinIO 预签名 URL（5 分钟有效）----
    try:
        url = storage.presign_url(
            task.output_file_path, bucket=settings.minio_output_bucket
        )
        return RedirectResponse(url, status_code=302)
    except Exception as exc:  # 预签名失败（含 MinIO 不可用）→ 4001
        logger.error("[download] MinIO 预签名失败: %s", exc)
        return _err(4001, f"内部错误：文件存储不可用（{exc}）")


@router.get("/health")
def health_check(db: Annotated[Session, Depends(get_db)] = None) -> dict[str, Any]:
    """四服务健康探测：mysql/redis/minio/chroma 各自独立判定。

    :return: {"status":"ok"|"degraded","services":{...}}
    """
    services: dict[str, bool] = {}
    # ---- MySQL：SELECT 1 ----
    try:
        db.execute(text("SELECT 1"))
        services["mysql"] = True
    except Exception:
        services["mysql"] = False
    # ---- Redis：ping（task_cache.get_client 内部已探测）----
    services["redis"] = task_cache.get_client() is not None
    # ---- MinIO：连通性探测 ----
    services["minio"] = storage.ping()
    # ---- ChromaDB：心跳接口 ----
    try:
        import httpx  # 延迟导入（健康检查才用到）

        resp = httpx.get(
            f"http://{settings.chroma_host}:{settings.chroma_port}/api/v2/heartbeat",
            timeout=settings.chroma_health_timeout_seconds,
        )
        services["chroma"] = resp.status_code == 200
    except Exception:
        services["chroma"] = False

    return {
        "status": "ok" if all(services.values()) else "degraded",
        "services": services,
    }



