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
import json  # SSE 事件序列化
import logging  # 标准库日志
import os  # 本地输出路径判断
import time  # SSE 心跳计时
import uuid  # 任务 UUID 生成
from typing import Annotated, Any  # 泛型类型 / FastAPI 依赖注入标注
from urllib.parse import quote  # 下载文件名 URL 编码

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    Response,
    StreamingResponse,  # SSE 实时推送
)
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

# 终态集合（惰性过期判定 / 下载准入 / 取消准入共用）
_TERMINAL_STATUS = {
    TaskStatus.SUCCESS,
    TaskStatus.FAILED,
    TaskStatus.EXPIRED,
    TaskStatus.CANCELLED,
}


def _ok(**data: Any) -> dict[str, Any]:
    """成功响应：{"code":0, **data}（蓝图 7.1 契约）。"""
    return {"code": 0, **data}


def _err(code: int, msg: str) -> dict[str, Any]:
    """业务错误响应：{"code":N, "msg":...}（HTTP 200，蓝图 7.2 错误码）。"""
    return {"code": code, "msg": msg}


# SSE 终态：命中即关闭流（含 U2 新增的 cancelled）
_SSE_TERMINAL = {"success", "failed", "expired", "cancelled"}


def _build_download_url(task: Any) -> str | None:
    """构造下载地址：统一走 /api/v1/download/{task_id}（后端代理，浏览器同源直取）。"""
    if not (task.output_file_path and task.status in (TaskStatus.SUCCESS, TaskStatus.FAILED)):
        return None
    return f"/api/v1/download/{task.id}"


def _sse_event(event: str, data: Any) -> str:
    """格式化一个 SSE 事件帧（event + data 双行 + 空行结尾）。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


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
        from app.crud.users import get_or_create_anonymous

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

    # ---- 3. 结果预览：校验报告（validator 节点写入，复用 agent_state_snapshot 列）----
    validation_report = task.agent_state_snapshot or None

    # ---- 4. 成功/失败时附下载地址（5 分钟预签名 URL）----
    download_url = _build_download_url(task)

    return _ok(
        status=status,
        progress=progress,
        step=step,
        logs=logs,
        download_url=download_url,
        validation_report=validation_report,
        retry_count=task.retry_count,
    )


@router.get("/task/{task_id}/stream")
def stream_task_status(
    task_id: str, db: Annotated[Session, Depends(get_db)] = None
) -> StreamingResponse:
    """SSE 实时推送：状态/进度/步骤/日志变更即推，15s 心跳，终态关闭。

    数据源：Redis 快照优先（与轮询协议一致），不可用降级 1s 间隔读 MySQL。
    客户端断开自动终止；重连延迟 retry: 3000 已内嵌。
    """
    from app.crud.agent_logs import list_logs  # 延迟导入避免循环
    from app.crud.tasks import get_task

    def generate():
        last_status = last_progress = last_step = None
        sent_logs = 0
        last_heartbeat = time.monotonic()
        yield "retry: 3000\n\n"
        while True:
            try:
                # 关键：每轮迭代先结束当前事务。请求级会话在 MySQL REPEATABLE
                # READ 下首轮 SELECT 即建立快照，且 SQLAlchemy identity map 复用
                # 同一对象 —— 不重置事务的话，task 的 output_file_path/retry_count/
                # agent_state_snapshot 永远停在首轮状态，终态帧 download_url 恒为
                # None（前端必须刷新页面重新请求才能下载）。rollback 后下一轮
                # SELECT 开启新事务、拿到新快照，行为等同每次新查询。
                db.rollback()
                task = get_task(db, task_id)
                if task is None:  # 任务不存在/已过期 → 错误帧后关闭
                    yield _sse_event("error", {"code": 2001, "msg": "任务不存在或已过期"})
                    return
                if _ensure_not_expired(db, task):
                    yield _sse_event(
                        "status",
                        {
                            "status": "expired",
                            "progress": task.progress,
                            "step": task.current_step,
                            "logs": [l.log_message for l in list_logs(db, task_id)],
                            "download_url": None,
                            "retry_count": task.retry_count,
                            "validation_report": task.agent_state_snapshot,
                        },
                    )
                    return
                # 快照优先，miss 降级 MySQL（与 GET /task 读侧一致）
                snapshot = task_cache.get_snapshot(task_id)
                if snapshot is not None:
                    status, progress, step = (
                        snapshot["status"],
                        snapshot["progress"],
                        snapshot["step"],
                    )
                    logs = snapshot["logs"] or []
                else:
                    status, progress, step = (
                        task.status.value,
                        task.progress,
                        task.current_step,
                    )
                    logs = [l.log_message for l in list_logs(db, task_id)]

                # ---- log 增量推送（逐条 event: log）----
                for line in logs[sent_logs:]:
                    yield _sse_event("log", line)
                sent_logs = len(logs)

                # ---- status 变更推送（含终态下载地址）----
                changed = (
                    status != last_status
                    or progress != last_progress
                    or step != last_step
                )
                if changed:
                    last_status, last_progress, last_step = status, progress, step
                    yield _sse_event(
                        "status",
                        {
                            "status": status,
                            "progress": progress,
                            "step": step,
                            "logs": logs,
                            "download_url": _build_download_url(task),
                            "retry_count": task.retry_count,
                            "validation_report": task.agent_state_snapshot,
                        },
                    )
                if status in _SSE_TERMINAL:  # 终态 → 关闭流
                    return

                # ---- 15s 心跳（注释帧，保持连接/穿透代理超时）----
                now = time.monotonic()
                if now - last_heartbeat >= 15:
                    last_heartbeat = now
                    yield ": ping\n\n"
                time.sleep(1)
            except GeneratorExit:  # 客户端断开 → 静默终止
                return
            except Exception:  # 单次迭代异常 → 错误帧后关闭，避免死循环
                logger.exception("[stream] SSE 推送异常，关闭流")
                yield _sse_event("error", {"code": 4001, "msg": "流式推送中断"})
                return

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 双保险：nginx 层 proxy_buffering off 已配
        },
    )


@router.post("/task/{task_id}/cancel")
def cancel_task(
    task_id: str, db: Annotated[Session, Depends(get_db)] = None
) -> Any:
    """取消任务：revoke Celery + 写取消标志（Redis + MySQL status=cancelled）。

    Windows solo worker 无 terminate 能力，靠标志位协作退出：节点入口
    （supervisor/planner/executor）轮询 is_cancelled 提前结束，error_node
    终态守卫保证不覆盖 cancelled。
    :param task_id: 任务 UUID
    :return: {"code":0,"msg":"任务已取消"} 或错误码
    """
    from app.crud.agent_logs import add_log
    from app.crud.tasks import get_task, mark_cancelled

    task = get_task(db, task_id)
    if task is None:
        return _err(2001, "任务不存在或已过期")
    if _ensure_not_expired(db, task):
        return _err(3001, "任务已过期（超过 24 小时生命周期）")
    if task.status in _TERMINAL_STATUS:
        return _err(2002, "任务已结束，无法取消")

    # ---- 1. 取消标志（Redis 供节点轮询，MySQL 供降级判定与前端展示）----
    # 先写标志再 revoke：取消响应不被 broker 广播阻塞（solo worker 下
    # revoke 广播要等当前任务跑完才能被消费，放前面会让 DB 的 cancelled
    # 延迟数秒提交，扩大 error_node 读到"运行中"的竞态窗口）
    task_cache.set_cancelled_flag(task_id)
    mark_cancelled(db, task_id)
    add_log(
        db,
        task_id=task_id,
        agent_node="api",
        message="用户请求取消任务",
        level=LogLevel.INFO,
    )

    # ---- 2. Celery revoke（未投递任务直接移除；运行中任务靠标志位）----
    try:
        from app.celery_app import celery_app  # 延迟导入避免循环

        celery_app.control.revoke(task_id, terminate=False, reply=False)
    except Exception as exc:  # broker 不可用 → 标志位兜底，不阻塞取消
        logger.warning("[cancel] revoke 失败(不影响取消): %s", exc)

    return _ok(msg="任务已取消")


@router.get("/download/{task_id}")
def download_result(
    task_id: str, db: Annotated[Session, Depends(get_db)] = None
) -> Any:
    """下载处理结果：本地文件流优先，MinIO 对象由后端代理返回。

    :param task_id: 任务 UUID
    :return: FileResponse / Response / 错误码
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
        # 顺带把本地兜底文件补传 MinIO，避免重启/清理后丢失（失败不影响本次下载）
        try:
            from datetime import datetime

            from app.crud.tasks import update_task  # 延迟导入

            key = (
                f"{datetime.now():%Y/%m/%d}/{task.id}/"
                f"{os.path.basename(task.output_file_path)}"
            )
            storage.upload_file(
                task.output_file_path,
                bucket=settings.minio_output_bucket,
                key=key,
            )
            update_task(db, task.id, output_file_path=key)
            logger.info("[download] 本地兜底文件已补传 MinIO: %s", key)
        except Exception as exc:
            logger.warning("[download] 本地兜底文件补传失败: %s", exc)
        return FileResponse(
            task.output_file_path,
            filename=os.path.basename(task.output_file_path),  # modified_xxx.docx
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    # ---- 正常路径：后端代理 MinIO 对象（避免浏览器直连的跨域/主机名问题）----
    try:
        data = storage.read_object(
            task.output_file_path, bucket=settings.minio_output_bucket
        )
    except Exception as exc:  # 读取失败（含 MinIO 不可用）→ 4001
        logger.error("[download] MinIO 读取失败: %s", exc)
        return _err(4001, f"内部错误：文件存储不可用（{exc}）")
    filename = os.path.basename(task.output_file_path)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


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
