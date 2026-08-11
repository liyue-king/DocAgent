"""
====================================================================
文件用途：validator —— 校验节点（覆盖率闭环核心，v5.2 五项维度）
====================================================================
作用：
    对修改后的文档二次扫描，按五项维度（字体/字号/加粗/行距/段间距）
    计算覆盖率。三档口径（蓝图 1.2）：
        - 覆盖率 == 100%  → 直接成功；
        - 覆盖率 < 100% 且 retry_count < 上限 → 生成 missed 明细并触发重试，
          MySQL 状态置 retrying（前端黄色闪烁），进度回退 30；
        - 重试耗尽（>=3 次）后：覆盖率 ≥98% 判成功，<98% 判失败。
    重试时 missed（para_id/style/expected/actual/reason）完整喂回 Planner 做增量修补。
依赖：
    - app.services.docx_editor.compute_coverage（五项扫描）
    - app.config.settings.max_retry_count（重试上限）
====================================================================
"""

from __future__ import annotations

import logging  # 标准库日志
from typing import Any  # 泛型类型

from docx import Document  # 重新打开输出文档

from app.agents.nodes._common import notify  # 日志 + 持久化
from app.config import settings  # 重试上限
from app.models import LogLevel, TaskStatus  # 枚举
from app.services.docx_editor import compute_coverage  # 五项覆盖率

logger = logging.getLogger(__name__)  # 模块级日志器
NODE_NAME = "validator"  # 节点名


def validator_node(state: dict[str, Any]) -> dict[str, Any]:
    """校验节点：计算覆盖率并按三档口径决策（成功/重试/失败）。

    :param state: 当前状态（含 output_file_path / selected_template_config）
    :return: 状态更新（validation_report / retry_count / status / agent_logs）
    """
    template_config = state.get("selected_template_config") or {}
    output_file = state.get("output_file_path") or state.get("working_file_path", "")
    retry_count = state.get("retry_count", 0)
    max_retry = settings.max_retry_count
    updates: dict[str, Any] = {}

    try:
        doc = Document(output_file)  # 重新打开修改后的文档
        report = compute_coverage(doc, template_config)  # 五项扫描
    except Exception as exc:
        msg = f"校验阶段读取文档失败：{exc}"
        report = {"passed": False, "coverage": 0.0, "total": 0, "matched": 0, "missed": []}
        logs = notify(
            state,
            msg,
            NODE_NAME,
            level=LogLevel.ERROR,
            status=TaskStatus.FAILED,
            progress=100,
            step="校验读取失败",
            agent_state_snapshot=report,  # 落库供前端结果预览
        )
        updates.update(
            {
                "agent_logs": logs,
                "status": "failed",
                "error_message": msg,
                "validation_report": report,
            }
        )
        return updates

    coverage = report["coverage"]
    total = report["total"]

    # ---- 档位 1：覆盖率 100% → 直接成功 ----
    if coverage >= 1.0:
        report["passed"] = True
        logs = notify(
            state,
            f"校验通过：样式覆盖率 100%（{report['matched']}/{total}）",
            NODE_NAME,
            level=LogLevel.INFO,
            status=TaskStatus.VALIDATING,
            progress=95,
            step="校验通过",
            agent_state_snapshot=report,  # 落库供前端结果预览
        )
        updates.update(
            {"validation_report": report, "agent_logs": logs, "status": "done"}
        )
        return updates

    # ---- 档位 2：未达 100% 且重试未耗尽 → 触发重试（增量修补）----
    if retry_count < max_retry:
        report["passed"] = False
        new_retry = retry_count + 1
        logs = notify(
            state,
            f"校验未通过：覆盖率 {coverage * 100:.1f}%（{report['matched']}/{total}），"
            f"AI 重规划中(第 {new_retry} 次)，待修补段落 {len(report.get('missed', []))} 个",
            NODE_NAME,
            level=LogLevel.WARNING,
            status=TaskStatus.RETRYING,  # 前端黄色闪烁
            progress=30,  # 进度回退至 30 重新推进
            step=f"校验未通过，AI重规划(第{new_retry}次)",
            agent_state_snapshot=report,  # 落库供前端结果预览
        )
        updates.update(
            {
                "validation_report": report,
                "retry_count": new_retry,
                "agent_logs": logs,
                "status": "planning",  # 回跳 planner
            }
        )
        return updates

    # ---- 档位 3：重试耗尽，按 98% 验收线终判 ----
    passed = coverage >= 0.98
    report["passed"] = passed
    if passed:
        logs = notify(
            state,
            f"重试耗尽，覆盖率 {coverage * 100:.1f}%（≥98%），判定成功",
            NODE_NAME,
            level=LogLevel.WARNING,
            status=TaskStatus.VALIDATING,
            progress=95,
            step="重试耗尽，判定成功",
            agent_state_snapshot=report,  # 落库供前端结果预览
        )
        updates.update(
            {"validation_report": report, "agent_logs": logs, "status": "done"}
        )
    else:
        msg = f"重试 3 次后覆盖率仍为 {coverage * 100:.1f}%（<98%），判定失败"
        logs = notify(
            state,
            msg,
            NODE_NAME,
            level=LogLevel.ERROR,
            status=TaskStatus.VALIDATING,
            progress=100,
            step="校验未通过",
            agent_state_snapshot=report,  # 落库供前端结果预览
        )
        updates.update(
            {
                "validation_report": report,
                "agent_logs": logs,
                "status": "failed",
                "error_message": msg,
            }
        )
    return updates


def route_after_validator(state: dict[str, Any]) -> str:
    """Validator 条件路由：
    passed=True          → success_node
    passed=False 且未耗尽 → planner（增量修补）
    passed=False 且已耗尽 → error_node（强制失败）
    """
    report = state.get("validation_report") or {}
    if report.get("passed"):
        return "success_node"
    if state.get("retry_count", 0) < settings.max_retry_count:
        return "planner"
    return "error_node"
