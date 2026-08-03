"""
====================================================================
文件用途：error_node —— 失败收尾节点（强制失败 + 保留结果）
====================================================================
作用：
    1. 尽力将最后一次修改结果上传至 MinIO（即使不达标仍供用户下载，
       蓝图 6.2 error_node 职责）；
    2. 更新 MySQL tasks 状态为 failed（含错误原因日志）；
    3. 返回状态 failed，供前端渲染失败视图。
依赖：
    - app.services.storage（MinIO 上传，尽力而为）
    - app.crud.tasks（mark_failed / update_task）
    - app.agents.nodes._common（notify / build_object_key）
====================================================================
"""

from __future__ import annotations

import logging  # 标准库日志
import os  # 文件名提取
from typing import Any  # 泛型类型

from app.agents.nodes._common import build_object_key, notify  # 工具
from app.config import settings  # MinIO 桶配置
from app.models import LogLevel, TaskStatus  # 枚举
from app.services.storage import storage  # MinIO 客户端

logger = logging.getLogger(__name__)  # 模块级日志器
NODE_NAME = "error_node"  # 节点名


def error_node(state: dict[str, Any]) -> dict[str, Any]:
    """失败收尾：保留可下载结果 + 置 MySQL failed。

    :param state: 当前状态（含 output_file_path / error_message / task_id）
    :return: 状态更新（status="failed" / agent_logs）
    """
    output_file = state.get("output_file_path", "")
    task_id = state.get("task_id", "")
    error_msg = state.get("error_message") or "文档处理失败"
    base_name = os.path.basename(state.get("working_file_path", "")) or "output.docx"

    # ---- 1. 尽力保留最后一次修改结果至 MinIO ----
    minio_key = ""
    if output_file and os.path.exists(output_file):
        try:
            key = build_object_key(task_id, base_name, modified=True)
            storage.upload_file(
                output_file, bucket=settings.minio_output_bucket, key=key
            )
            minio_key = key  # 仅上传成功才回填 Key，失败保留本地路径
            logger.info("[error_node] 失败结果已保留至 MinIO: %s", minio_key)
        except Exception as exc:
            logger.warning("[error_node] 失败结果上传 MinIO 失败: %s", exc)

    # ---- 2. 更新 MySQL failed（回填输出路径便于兜底下载）----
    try:
        from app.crud.tasks import mark_failed, update_task  # 延迟导入
        from app.db import SessionLocal

        db = SessionLocal()
        try:
            mark_failed(db, task_id)
            if minio_key or output_file:
                update_task(db, task_id, output_file_path=minio_key or output_file)
        finally:
            db.close()
    except Exception as exc:  # DB 未就绪 → 仅日志
        logger.warning("[error_node] MySQL 失败收尾失败: %s", exc)

    logs = notify(
        state,
        f"处理失败：{error_msg}",
        NODE_NAME,
        level=LogLevel.ERROR,
        status=TaskStatus.FAILED,
        progress=100,
        step="处理失败",
    )
    return {
        "agent_logs": logs,
        "status": "failed",
        "error_message": error_msg,
        "output_file_path": minio_key or output_file,
    }
