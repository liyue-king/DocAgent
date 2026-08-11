"""
====================================================================
文件用途：Celery 应用实例（异步任务调度）
====================================================================
作用：
    定义全局唯一的 Celery 应用，Broker / Result Backend 对齐蓝图 5.2：
        - Broker：Redis db=0（任务队列）
        - Result Backend：Redis db=1（结果存储，配置了但任务忽略结果，
          避免 celery-task-meta-* Key 堆积）
    任务定义见 app/tasks.py（include 自动发现注册）。
依赖：
    - celery（已加入 pyproject.toml）
    - app.config.settings（broker / backend 地址）
调用方：
    - app/api/routes.py（apply_async 投递任务）
    - 命令行：celery -A app.celery_app worker -P solo --loglevel=info
    - 可选 beat：celery -A app.celery_app beat（周期清扫过期任务）
说明：
    - task_soft_time_limit=240 对齐容错矩阵"Worker 宕机/超时保护"；
      注意 Windows -P solo 下信号软限不生效（billiard SIGUSR1 仅 Unix），
      兜底靠读取时惰性过期 + beat 周期清扫。
====================================================================
"""

from __future__ import annotations

from celery import Celery  # Celery 任务框架

from app.config import settings  # Broker / Backend 配置
from app.logging_setup import setup_logging  # loguru 统一日志（worker 侧同样接管）

setup_logging()  # worker/beat 进程日志格式与 API 网关一致

# 全局唯一 Celery 应用（include 声明任务模块，随应用启动自动注册）
celery_app = Celery(
    "docagent",  # 应用名（消息路由前缀）
    broker=settings.celery_broker_url,  # redis://localhost:6379/0
    backend=settings.celery_result_backend,  # redis://localhost:6379/1
    include=["app.tasks"],  # 任务定义模块（自动导入注册）
)

# ---- 任务执行配置（对齐蓝图 9 容错矩阵）----
celery_app.conf.update(
    task_soft_time_limit=settings.celery_soft_time_limit_seconds,  # 软超时
    task_time_limit=settings.celery_time_limit_seconds,  # 硬超时
    task_ignore_result=True,  # 忽略任务结果（状态存 MySQL，不写 backend）
    broker_connection_retry_on_startup=True,  # 启动时 Broker 连接自动重试
    # 周期清扫过期任务（可选：单独启动 beat 进程；不启动则靠惰性过期兜底）
    beat_schedule={
        "sweep-expired-tasks": {
            "task": "docagent.sweep_expired",  # 任务名（app/tasks.py）
            "schedule": float(settings.celery_beat_sweep_interval_seconds),
        },
    },
    timezone="Asia/Shanghai",  # 定时任务时区
)
