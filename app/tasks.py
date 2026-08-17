"""
====================================================================
文件用途：Celery 任务定义（Worker 侧执行 LangGraph 编排）
====================================================================
作用：
    1. process_document_task：文档处理主任务 —— 从 MinIO 下载输入文件
       到本地临时目录 → 调用 run_agent 执行 LangGraph 状态机（节点内部
       已负责 MySQL 状态推进 / 输出上传 MinIO / 终态收尾）→ 清理临时文件。
    2. sweep_expired_tasks：周期清扫超过 24h 生命周期的任务（beat 进程）。
依赖：
    - app.celery_app.celery_app（任务注册）
    - app.agents.run_agent（LangGraph 编排入口）
    - app.services.storage（MinIO 下载）
    - app.crud.tasks / agent_logs（DB 状态与日志）
说明：
    - 终态防覆盖：catch-all 重读任务，已 SUCCESS/FAILED/EXPIRED 则跳过
      （success_node / error_node 已完成终态收尾，Worker 不重复写）。
    - SoftTimeLimitExceeded 继承 BaseException，须在 except Exception 之前捕获。
====================================================================
"""

from __future__ import annotations

import logging  # 标准库日志
import os  # 路径拼接
import shutil  # 临时目录清理
import tempfile  # 临时工作目录
from typing import Any  # 泛型类型

from celery.exceptions import SoftTimeLimitExceeded  # 软超时异常（BaseException）

from app.celery_app import celery_app  # Celery 应用（注册任务）
from app.config import settings  # MinIO 桶配置
from app.models import LogLevel, TaskStatus  # 枚举
from app.services.storage import StorageUnavailable, storage  # MinIO 客户端

logger = logging.getLogger(__name__)  # 模块级日志器


def _delete_task_objects(task: Any) -> None:
    """删除过期任务的 MinIO 输入/输出对象与本地兜底文件（单个失败仅告警）。

    :param task: tasks 表记录（需含 input_file_path / output_file_path）
    """
    for key, bucket in (
        (task.input_file_path, settings.minio_input_bucket),
        (task.output_file_path, settings.minio_output_bucket),
    ):
        if not key:
            continue
        try:
            storage.delete_object(key, bucket=bucket)
        except Exception as exc:  # MinIO 宕机 → 对象保留，下次清扫重试
            logger.warning("[worker] 过期对象删除失败: %s", exc)
    # 本地兜底文件（仅限稳定输出目录内，防误删）
    local_path = task.output_file_path or ""
    if local_path and os.path.exists(local_path) and os.path.abspath(
        local_path
    ).startswith(os.path.abspath(settings.local_output_dir_abs)):
        try:
            os.remove(local_path)
            logger.info("[worker] 过期本地兜底文件已删除: %s", local_path)
        except Exception as exc:
            logger.warning("[worker] 过期本地兜底文件删除失败: %s", exc)


def _fail_task(task_id: str, message: str) -> None:
    """终态守卫式失败收尾：仅当任务未达终态时才置 FAILED。

    :param task_id: 任务 UUID
    :param message: 失败原因（写入 ERROR 日志）
    """
    try:
        from app.crud.agent_logs import add_log
        from app.crud.tasks import get_task, mark_failed
        from app.db import SessionLocal

        db = SessionLocal()
        try:
            task = get_task(db, task_id)
            if task is None or task.status in (
                TaskStatus.SUCCESS,
                TaskStatus.FAILED,
                TaskStatus.EXPIRED,
                TaskStatus.CANCELLED,
            ):
                return  # 节点已收尾/已取消或任务不存在，不覆盖终态
            mark_failed(db, task_id)
            add_log(
                db,
                task_id=task_id,
                agent_node="celery_worker",
                message=message,
                level=LogLevel.ERROR,
            )
        finally:
            db.close()
    except Exception as exc:  # DB 不可用 → 仅日志
        logger.warning("[worker] 失败收尾失败: %s", exc)


@celery_app.task(name="docagent.process_document")
def process_document_task(task_id: str) -> dict[str, Any]:
    """文档处理主任务：下载 → 编排 → 清理。

    :param task_id: 任务 UUID（与 MySQL tasks.id / 蓝图约定一致）
    :return: 终态状态字典（供调试；前端状态以 MySQL/Redis 为准）
    """
    # ---- 0. 加载任务 + 记录开始时间 ----
    try:
        from app.agents.nodes._common import is_cancelled  # 延迟导入（取消标志判定）
        from app.crud.tasks import get_task, mark_started
        from app.db import SessionLocal

        db = SessionLocal()
        try:
            task = get_task(db, task_id)
            if task is None:  # 任务已被删除（如过期清理）
                logger.warning("[worker] 任务不存在，跳过: %s", task_id)
                return {}
            # cancel 竞态守卫：任务在队列期间可能已被用户取消/清扫收尾，
            # 此处先读终态 + 取消标志，已终态/已取消则直接跳过，
            # 禁止 mark_started 覆盖 CANCELLED（Redis 标志先于 DB 提交，
            # 两者都查，覆盖在途取消窗口）。
            if task.status in (
                TaskStatus.SUCCESS,
                TaskStatus.FAILED,
                TaskStatus.EXPIRED,
                TaskStatus.CANCELLED,
            ) or is_cancelled(task_id):
                logger.info(
                    "[worker] 任务已取消/终态(%s)，跳过处理: %s",
                    task.status.value,
                    task_id,
                )
                return {}
            mark_started(db, task_id)  # 记录 started_at
        finally:
            db.close()
    except Exception as exc:
        _fail_task(task_id, f"加载任务失败：{exc}")
        return {}

    tmp_dir = tempfile.mkdtemp(prefix="docagent_")  # 本地临时工作目录
    local_in = os.path.join(tmp_dir, task.input_file_name)
    try:
        # ---- 1. 从 MinIO 下载输入文件到本地工作副本 ----
        try:
            storage.download_file(
                task.input_file_path,
                bucket=settings.minio_input_bucket,
                local_path=local_in,
            )
        except StorageUnavailable as exc:  # MinIO 宕机 → 任务失败
            _fail_task(task_id, f"输入文件下载失败：{exc}")
            return {}

        # ---- 2. 执行 LangGraph 编排（节点内部推进 MySQL 状态/日志）----
        from app.agents import run_agent  # 延迟导入（编排层较重）

        initial_state = {
            "task_id": task_id,  # 任务 UUID
            "user_prompt": task.prompt_text,  # 用户需求
            "working_file_path": local_in,  # 本地工作副本
            "input_file_path": task.input_file_path,  # MinIO 输入 Key
        }
        final_state = run_agent(initial_state)
        logger.info(
            "[worker] 任务处理完成: %s status=%s", task_id, final_state.get("status")
        )

        # ---- 3. 本地兜底输出转存稳定目录，临时目录一律清理 ----
        final_output = final_state.get("output_file_path", "")
        if final_output and os.path.exists(final_output) and not os.path.abspath(
            final_output
        ).startswith(os.path.abspath(settings.local_output_dir_abs)):
            try:
                from app.crud.tasks import update_task  # 延迟导入
                from app.db import SessionLocal

                stable_dir = os.path.join(settings.local_output_dir_abs, task_id)
                os.makedirs(stable_dir, exist_ok=True)
                stable_path = os.path.join(stable_dir, os.path.basename(final_output))
                shutil.copy2(final_output, stable_path)
                db = SessionLocal()
                try:
                    update_task(db, task_id, output_file_path=stable_path)
                finally:
                    db.close()
                logger.warning(
                    "[worker] 输出仅存本地，已转存稳定目录: %s", stable_path
                )
            except Exception as exc:
                logger.warning("[worker] 本地输出转存稳定目录失败: %s", exc)
        shutil.rmtree(tmp_dir, ignore_errors=True)  # 临时目录全量清理
        return final_state
    except SoftTimeLimitExceeded:  # 软超时 240s（须在 Exception 前捕获）
        _fail_task(task_id, "任务超时，请稍后重试")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return {"status": "failed", "error_message": "任务超时，请稍后重试"}
    except Exception as exc:  # 兜底：任何未捕获异常 → 任务失败
        _fail_task(task_id, f"文档处理失败：{str(exc)[:500]}")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        logger.exception("[worker] 任务异常: %s", task_id)
        return {"status": "failed", "error_message": str(exc)[:500]}


@celery_app.task(name="docagent.sweep_expired")
def sweep_expired_tasks() -> int:
    """周期清扫：将超过 expires_at 的非终态任务置为 EXPIRED 并删除 MinIO 对象。

    :return: 本次清扫的任务数（0 表示无过期任务）
    """
    try:
        from app.crud.tasks import list_expired_tasks, mark_expired
        from app.db import SessionLocal

        db = SessionLocal()
        try:
            expired = list_expired_tasks(db)  # expires_at < now 且非终态
            for task in expired:
                mark_expired(db, task.id)
                _delete_task_objects(task)  # 输入/输出对象清理（独立降级）
            return len(expired)
        finally:
            db.close()
    except Exception as exc:  # DB 不可用 → 仅告警
        logger.warning("[worker] 过期任务清扫失败: %s", exc)
        return 0
