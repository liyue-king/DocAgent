"""
====================================================================
文件用途：success_node —— 成功收尾节点
====================================================================
作用：
    1. 将修改后的本地输出文件上传至 MinIO 输出桶（对象 Key 对齐蓝图 5.3）；
    2. 计算处理耗时与 LLM 费用，更新 MySQL tasks 状态为 success；
    3. 返回状态 done，供前端展示下载入口。
依赖：
    - app.services.storage（MinIO 上传，尽力而为）
    - app.crud.tasks.mark_success（成功收尾）
    - app.agents.nodes._common（notify / build_object_key / estimate_cost_usd）
====================================================================
"""

from __future__ import annotations

import logging  # 标准库日志
import os  # 文件名提取
import time  # 耗时统计
from decimal import Decimal  # 高精度费用
from typing import Any  # 泛型类型

from app.agents.nodes._common import build_object_key, estimate_cost_usd, notify  # 工具
from app.config import settings  # MinIO 桶配置
from app.models import LogLevel, TaskStatus  # 枚举
from app.services.storage import storage  # MinIO 客户端

logger = logging.getLogger(__name__)  # 模块级日志器
NODE_NAME = "success_node"  # 节点名


def success_node(state: dict[str, Any]) -> dict[str, Any]:
    """成功收尾：上传输出 + 更新 MySQL + 统计指标。

    :param state: 当前状态（含 output_file_path / working_file_path / 指标）
    :return: 状态更新（status="done" / 输出信息 / agent_logs）
    """
    output_file = state.get("output_file_path", "")
    task_id = state.get("task_id", "")
    base_name = os.path.basename(state.get("working_file_path", "")) or "output.docx"
    started_at = state.get("started_at_ts") or time.time()
    llm_tokens = state.get("llm_total_tokens", 0)

    # ---- 1. 上传输出到 MinIO（尽力而为，失败保留本地路径供兜底下载）----
    minio_output_key = ""
    if output_file and os.path.exists(output_file):
        try:
            key = build_object_key(
                task_id, base_name, modified=True
            )  # modified_xxx.docx
            storage.upload_file(
                output_file, bucket=settings.minio_output_bucket, key=key
            )
            minio_output_key = key  # 仅上传成功才回填 Key，失败保留本地路径
            logger.info("[success_node] 输出已上传: %s", minio_output_key)
        except Exception as exc:
            logger.warning("[success_node] 输出上传 MinIO 失败，保留本地路径: %s", exc)

    # ---- 2. 指标计算 + MySQL 成功收尾 ----
    processing_ms = int((time.time() - started_at) * 1000)
    cost_usd = Decimal(str(estimate_cost_usd(llm_tokens)))
    try:
        from app.crud.tasks import mark_success  # 延迟导入
        from app.db import SessionLocal

        db = SessionLocal()
        try:
            mark_success(
                db,
                task_id,
                output_file_path=minio_output_key
                or output_file,  # 优先 MinIO Key，失败降级本地路径
                processing_time_ms=processing_ms,
                llm_total_tokens=llm_tokens,
                cost_usd=cost_usd,
            )
        finally:
            db.close()
    except Exception as exc:  # DB 未就绪 → 仅日志
        logger.warning("[success_node] MySQL 成功收尾失败: %s", exc)

    logs = notify(
        state,
        f"处理成功：耗时 {processing_ms / 1000:.1f}s，LLM token {llm_tokens}，费用 ${cost_usd}",
        NODE_NAME,
        level=LogLevel.INFO,
        status=TaskStatus.SUCCESS,
        progress=100,
        step="处理完成",
    )
    return {
        "agent_logs": logs,
        "status": "done",
        "error_message": "",
        "output_file_path": minio_output_key or output_file,  # 回写为可下载路径
    }
