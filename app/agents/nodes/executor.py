"""
====================================================================
文件用途：executor —— 文档执行节点（原子指令逐条落地）
====================================================================
作用：
    1. 打开本地工作副本，**修改前自动备份**至 MinIO（backup_object_key，
       失败降级为内存备份，原文件绝不丢失 —— v5.2 强制双层备份）；
    2. 重建含 para_obj 引用的完整 DOM（doc_dom）与可序列化 DOM（doc_dom_serial）；
    3. 逐条执行 task_queue，逐条记录 execution_errors（空段落无run / para_id
       越界 / 执行异常）；单条失败**不中断流程**、**不触发整轮重试**；
    4. 保存修改后的文档到 output_file_path，供 Validator 二次扫描。
依赖：
    - app.services.docx_editor（backup_doc / apply_operations / build_dom）
    - app.services.docx_parser（build_dom / build_dom_serial）
    - app.services.storage（MinIO 备份，尽力而为）
    - app.agents.nodes._common（notify / build_object_key）
====================================================================
"""

from __future__ import annotations

import logging  # 标准库日志
import os  # 文件路径处理
from datetime import datetime  # 备份 Key 时间戳
from pathlib import Path  # 默认输出路径
from typing import Any  # 泛型类型

from app.agents.nodes._common import is_cancelled, notify  # 取消判定 / 日志 + Key 生成
from app.models import LogLevel, TaskStatus  # 枚举
from app.services.docx_editor import apply_operations, backup_doc  # 文档操作
from app.services.docx_parser import build_dom, build_dom_serial  # DOM 重建

logger = logging.getLogger(__name__)  # 模块级日志器
NODE_NAME = "executor"  # 节点名


def _default_output_path(working_file: str) -> str:
    """未提供输出路径时，在工作文件旁生成 modified_ 前缀副本。"""
    src = Path(working_file)
    return str(src.with_name(f"modified_{src.name}"))


def executor_node(state: dict[str, Any]) -> dict[str, Any]:
    """执行节点：备份 + 逐条执行原子指令 + 保存输出。

    :param state: 当前状态（含 task_queue / working_file_path / output_file_path）
    :return: 状态更新（doc_dom / doc_dom_serial / 执行统计 / agent_logs / status）
    """
    task_queue = state.get("task_queue") or []
    working_file = state.get("working_file_path", "")
    output_file = state.get("output_file_path") or _default_output_path(working_file)
    task_id = state.get("task_id", "")

    # 取消检查：文档操作可能耗时，取消后提前退出（error_node 收尾）
    if is_cancelled(task_id):
        return {"status": "cancelled", "error_message": "任务已取消"}

    updates: dict[str, Any] = {}
    source = (
        output_file if os.path.exists(output_file) else working_file
    )  # 重试时基于上次输出继续

    # ---- 1. 打开工作副本 + 内存备份 ----
    try:
        doc, backup_bytes = backup_doc(source)  # 打开 + 序列化内存备份
    except Exception as exc:  # 防御：backup_doc 内部已兜底，此处仅记录
        logger.error("[executor] backup_doc 异常: %s", exc)
        doc, backup_bytes = None, None
    if doc is None or backup_bytes is None:  # 文档损坏/不可读 → 失败（error_node 兜底）
        msg = f"打开工作文档失败：文档不可读或已损坏（{os.path.basename(source)}）"
        logs = notify(
            state,
            msg,
            NODE_NAME,
            level=LogLevel.ERROR,
            status=TaskStatus.FAILED,
            progress=100,
            step="文档打开失败",
        )
        return {
            "agent_logs": logs,
            "status": "failed",
            "error_message": msg,
            "output_file_path": output_file,
        }

    # ---- 2. 首轮备份至 MinIO（v5.2 双层备份：MinIO + 内存）----
    backup_key = state.get("backup_object_key", "")
    if not backup_key:
        try:
            from app.config import settings  # MinIO 桶配置
            from app.services.storage import storage  # MinIO 客户端

            base_name = os.path.basename(source) or "input.docx"
            d = datetime.now()
            key = f"backup/{d:%Y/%m/%d}/{task_id}/{base_name}"
            storage.upload_bytes(
                backup_bytes, bucket=settings.minio_input_bucket, key=key
            )
            backup_key = key
            logger.info("[executor] 已备份原文件至 MinIO: %s", key)
        except Exception as exc:  # MinIO 不可用 → 仅保留内存备份
            logger.warning("[executor] MinIO 备份失败，仅保留内存备份: %s", exc)

    # ---- 3. 重建 DOM（para_obj 引用本进程 doc，修改即时生效）----
    dom = build_dom(doc)
    execution_errors: list[dict[str, Any]] = []
    executed_count = 0

    # ---- 4. 逐条执行，逐条记录错误（空段落跳过 / 越界 / 异常）----
    for idx, op in enumerate(task_queue):
        action = op.get("action", "")
        para_ids = op.get("para_ids", [])
        valid_pids: list[int] = []
        for pid in para_ids:
            if not isinstance(pid, int) or pid < 0 or pid >= dom["paragraph_count"]:
                execution_errors.append(
                    {
                        "index": idx,
                        "action": action,
                        "para_id": pid,
                        "reason": "para_id 越界",
                    }
                )
                continue
            para = dom["paragraphs"][pid]["para_obj"]
            # 空段落仅放行段落级格式（行距/段间距，无需 run），run 级操作（字体/字号/加粗）跳过
            if not para.runs and action not in (
                "set_paragraph_space",
                "set_line_spacing",
            ):
                execution_errors.append(
                    {
                        "index": idx,
                        "action": action,
                        "para_id": pid,
                        "reason": "空段落无run",
                    }
                )
                continue
            valid_pids.append(pid)
        if not valid_pids:
            continue  # 该指令无有效目标段落
        try:
            apply_operations(dom, [{**op, "para_ids": valid_pids}])  # 仅作用合法段落
            executed_count += 1
        except Exception as exc:
            for pid in valid_pids:
                execution_errors.append(
                    {
                        "index": idx,
                        "action": action,
                        "para_id": pid,
                        "reason": f"执行异常:{exc}",
                    }
                )

    # ---- 5. 保存输出（Validator 与 success/error 均依赖该文件）----
    try:
        os.makedirs(os.path.dirname(output_file), exist_ok=True) if os.path.dirname(
            output_file
        ) else None
        doc.save(output_file)
    except Exception as exc:
        msg = f"保存输出文档失败：{exc}"
        logs = notify(
            state,
            msg,
            NODE_NAME,
            level=LogLevel.ERROR,
            status=TaskStatus.FAILED,
            progress=100,
            step="保存失败",
        )
        return {
            "agent_logs": logs,
            "status": "failed",
            "error_message": msg,
            "output_file_path": output_file,
        }

    # ---- 6. 汇总日志 + 状态推进 ----
    skipped = len(execution_errors)
    summary = f"执行完成：成功应用 {executed_count} 条指令" + (
        f"，跳过 {skipped} 处异常段落" if skipped else ""
    )
    logs = notify(
        state,
        summary,
        NODE_NAME,
        level=LogLevel.INFO,
        status=TaskStatus.EXECUTING,
        progress=80,
        step="样式修改执行中",
    )

    updates.update(
        {
            "doc_dom_serial": build_dom_serial(dom),  # 纯数据 DOM（全字段可序列化，入 Checkpointer）
            "backup_object_key": backup_key,
            "output_file_path": output_file,
            "executed_count": state.get("executed_count", 0) + executed_count,
            "execution_errors": list(state.get("execution_errors") or [])
            + execution_errors,
            "current_task_index": len(task_queue),
            "agent_logs": logs,
            "status": "validating",  # 执行完毕 → 交 Validator 校验
        }
    )
    return updates


def route_after_executor(state: dict[str, Any]) -> str:
    """Executor 条件路由：执行成功→validator；执行失败（文档损坏等）→error_node。"""
    return "validator" if state.get("status") == "validating" else "error_node"
