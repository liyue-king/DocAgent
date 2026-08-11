"""
====================================================================
文件用途：Prometheus 指标（/metrics 纯文本输出）
====================================================================
作用：
    无埋点、直接从 MySQL/Redis 聚合生成 Prometheus exposition 格式：
    1. docagent_tasks_total{status}      —— 任务完成数（按状态分组）
    2. docagent_task_duration_seconds    —— 任务处理时长直方图（ms→s）
    3. docagent_llm_tokens_total         —— LLM 累计消耗 token 数
    4. docagent_queue_pending            —— Celery 队列积压（redis LLEN）
依赖：
    - app.db / app.config.settings（聚合数据源）
    - redis（队列积压，Broker db 独立连接）
调用方：
    - app/main.py（GET /metrics 挂载）
说明：
    - 与进程无关：API/Worker 任一进程抓取结果一致（读 MySQL 主数据）。
    - Redis 不可用时 queue 指标省略（不报错），其余指标照常输出。
====================================================================
"""

from __future__ import annotations

from typing import Any  # 泛型类型

from sqlalchemy import func  # SQL 聚合函数
from sqlalchemy.orm import Session  # 数据库会话类型

from app.config import settings  # Broker 地址解析
from app.models import Task  # 任务模型

# 处理时长直方图桶（秒）：覆盖 0.1s~5min 量级
_DURATION_BUCKETS = [0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300]

# Celery 默认队列 Key（对齐 celery_app.py broker redis://.../0）
_BROKER_QUEUE_KEY = "celery"


def _fmt_metric(
    name: str, value: Any, labels: dict[str, str] | None = None
) -> str:
    """渲染单行指标（无 label 的 float 保持科学计数兼容）。"""
    if labels:
        label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
        return f'{name}{{{label_str}}} {value}'
    return f"{name} {value}"


def _tasks_by_status(db: Session) -> dict[str, int]:
    """按状态统计任务数（GROUP BY，含所有状态）。"""
    rows = (
        db.query(Task.status, func.count(Task.id))
        .group_by(Task.status)
        .all()
    )
    # MySQL 方言存小写枚举值；SQLite 测试库存枚举名，统一转 value
    return {
        (status.value if hasattr(status, "value") else str(status)): count
        for status, count in rows
    }


def _duration_histogram(db: Session) -> tuple[list[int], float, int]:
    """已完成任务处理时长直方图（桶计数 + sum + count，毫秒转秒）。"""
    rows = (
        db.query(Task.processing_time_ms)
        .filter(Task.processing_time_ms.isnot(None))
        .all()
    )
    buckets = [0] * len(_DURATION_BUCKETS)
    total_seconds = 0.0
    for (ms,) in rows:
        sec = ms / 1000.0
        total_seconds += sec
        for i, b in enumerate(_DURATION_BUCKETS):
            if sec <= b:
                buckets[i] += 1
    return buckets, total_seconds, len(rows)


def _queue_pending() -> int:
    """Celery 队列积压（redis LLEN broker key）；Redis 不可用返回 0。"""
    try:
        import redis

        # 解析 broker URL（redis://host:port/db），对齐 celery_app.py 配置
        client = redis.Redis.from_url(
            settings.celery_broker_url,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        return int(client.llen(_BROKER_QUEUE_KEY) or 0)
    except Exception:  # 连接失败/无 redis 依赖
        return 0


def metrics_text(db: Session) -> str:
    """生成 Prometheus exposition 文本（GET /metrics 响应体）。"""
    lines: list[str] = [
        "# HELP docagent_tasks_total 任务总数（按状态）",
        "# TYPE docagent_tasks_total counter",
    ]
    for status, count in sorted(_tasks_by_status(db).items()):
        lines.append(_fmt_metric("docagent_tasks_total", count, {"status": status}))

    lines += [
        "# HELP docagent_task_duration_seconds 任务处理时长（直方图，秒）",
        "# TYPE docagent_task_duration_seconds histogram",
    ]
    buckets, total_seconds, count = _duration_histogram(db)
    for le, cum in zip(_DURATION_BUCKETS, buckets):
        lines.append(
            _fmt_metric(
                "docagent_task_duration_seconds_bucket", cum, {"le": str(le)}
            )
        )
    lines.append(_fmt_metric("docagent_task_duration_seconds_bucket", count, {"le": "+Inf"}))
    lines.append(_fmt_metric("docagent_task_duration_seconds_sum", round(total_seconds, 6)))
    lines.append(_fmt_metric("docagent_task_duration_seconds_count", count))

    llm_tokens = (
        db.query(func.coalesce(func.sum(Task.llm_total_tokens), 0)).scalar() or 0
    )
    lines += [
        "# HELP docagent_llm_tokens_total LLM 累计消耗 token 数",
        "# TYPE docagent_llm_tokens_total counter",
        _fmt_metric("docagent_llm_tokens_total", int(llm_tokens)),
    ]

    pending = _queue_pending()
    lines += [
        "# HELP docagent_queue_pending Celery 队列积压任务数",
        "# TYPE docagent_queue_pending gauge",
        _fmt_metric("docagent_queue_pending", pending),
    ]
    return "\n".join(lines) + "\n"
