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

from app.agents.nodes._common import (  # 工具
    build_object_key,
    estimate_cost_usd,
    is_cancelled,
    notify,
)
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
        for attempt in range(2):  # 失败重试一次，提升可靠性
            try:
                key = build_object_key(
                    task_id, base_name, modified=True
                )  # modified_xxx.docx
                storage.upload_file(
                    output_file, bucket=settings.minio_output_bucket, key=key
                )
                minio_output_key = key  # 仅上传成功才回填 Key，失败保留本地路径
                logger.info("[success_node] 输出已上传: %s", minio_output_key)
                break
            except Exception as exc:
                logger.warning(
                    "[success_node] 输出上传 MinIO 失败（第 %d 次），保留本地路径: %s",
                    attempt + 1,
                    exc,
                )
                minio_output_key = ""

    # ---- 2. 指标计算 + MySQL 成功收尾（含取消终态守卫）----
    processing_ms = int((time.time() - started_at) * 1000)
    cost_usd = Decimal(str(estimate_cost_usd(llm_tokens)))
    # 取消守卫（与 error_node 对齐）：Redis 取消标志 或 DB status=cancelled 均视为
    # 已取消 → 不 mark_success、不扣积分，仅保留输出路径，终态保持 CANCELLED。
    # 标志在 API 侧先于 DB 提交落 Redis，故感知标志时主动补写 cancelled（幂等）。
    cancelled = is_cancelled(task_id)
    try:
        from app.crud.tasks import (  # 延迟导入
            get_task,
            mark_cancelled,
            mark_success,
            update_task,
        )
        from app.db import SessionLocal

        db = SessionLocal()
        try:
            current = get_task(db, task_id)
            if (
                not cancelled
                and current is not None
                and current.status == TaskStatus.CANCELLED
            ):
                cancelled = True
            if cancelled:
                # 主动落 cancelled：防 API 的 mark_cancelled 提交在途导致 DB 未及更新
                if current is None or current.status != TaskStatus.CANCELLED:
                    mark_cancelled(db, task_id)
                if minio_output_key or output_file:
                    update_task(
                        db, task_id, output_file_path=minio_output_key or output_file
                    )
            else:
                task = mark_success(
                    db,
                    task_id,
                    output_file_path=minio_output_key
                    or output_file,  # 优先 MinIO Key，失败降级本地路径
                    processing_time_ms=processing_ms,
                    llm_total_tokens=llm_tokens,
                    cost_usd=cost_usd,
                )
                # 成功后才扣积分（提交时不扣；失败/取消不产生扣费）
                if task is not None and task.user_id != 1:
                    from app.crud import users as user_crud  # 延迟导入

                    if not user_crud.deduct_credit(
                        db, task.user_id, 1, action="task_consume"
                    ):
                        logger.warning(
                            "[success_node] 积分扣减失败（余额不足）: user=%s",
                            task.user_id,
                        )
        finally:
            db.close()
    except Exception as exc:  # DB 未就绪 → 仅日志
        logger.warning("[success_node] MySQL 成功收尾失败: %s", exc)

    if cancelled:
        logs = notify(
            state,
            f"任务已取消，保留已生成结果：耗时 {processing_ms / 1000:.1f}s",
            NODE_NAME,
            level=LogLevel.WARNING,
            status=None,  # 取消场景：status 传 None → DB 保持 CANCELLED
            progress=None,
            step="已取消",
        )
    else:
        # 个性化需求未实现的提示（v6.2）：LLM 降级或部分指令被丢弃时告知用户
        unmet = state.get("unmet_requirements") or []
        degraded = state.get("llm_degraded")
        extra_hint = ""
        if degraded:
            extra_hint = "（个性化需求未生效，已按模板处理）"
        elif unmet:
            extra_hint = f"（{len(unmet)} 条个性化需求未实现，详见校验报告）"
        logs = notify(
            state,
            f"处理成功：耗时 {processing_ms / 1000:.1f}s，LLM token {llm_tokens}，费用 ${cost_usd}{extra_hint}",
            NODE_NAME,
            level=LogLevel.WARNING if (degraded or unmet) else LogLevel.INFO,
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
