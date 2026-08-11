"""
====================================================================
文件用途：Redis 任务状态缓存服务（蓝图 5.2 应用级缓存 db=2）
====================================================================
作用：
    1. 写穿缓存：编排层节点每次状态推进时同步写入 Redis，保证前端
       轮询优先读 Redis 也能拿到最新进度（Key 设计对齐蓝图 5.2）：
           docagent:task:{id}:status / :progress / :step（TTL 3600s）
           docagent:task:{id}:logs（List，最近 20 条，TTL 3600s）
    2. 读侧兜底：GET /task 优先读 Redis 快照，未命中降级 MySQL 并回填。
    3. IP 限流：docagent:ratelimit:{ip}（INCR + 60s TTL），仅 POST /process
       使用（轮询每 2s 一次 = 30 次/分，若限流会误伤前端）。
依赖：
    - redis-py（已加入 pyproject.toml）
    - app.config.settings.redis_cache_url（db=2）
调用方：
    - app/agents/nodes/_common.py（写穿，编排层内延迟导入）
    - app/api/routes.py（读快照 / 回填 / 限流）
说明：
    - 全部方法尽力而为：Redis 不可用时静默降级（返回 None/False），
      绝不中断主流程 —— 与 storage.py 的降级哲学一致。
    - 客户端懒加载 + 失败不缓存：连接故障后下次调用自动重试。
====================================================================
"""

from __future__ import annotations

import logging  # 标准库日志
from typing import Any  # 泛型类型

from app.config import settings  # Redis 配置（db=2 缓存库）

logger = logging.getLogger(__name__)  # 模块级日志器

# 缓存 Key 模板（对齐蓝图 5.2 命名规范）
_STATUS_KEY = "docagent:task:{tid}:status"  # 任务状态
_PROGRESS_KEY = "docagent:task:{tid}:progress"  # 进度（0-100）
_STEP_KEY = "docagent:task:{tid}:step"  # 当前步骤描述
_LOGS_KEY = "docagent:task:{tid}:logs"  # 最近日志（List）
_RATELIMIT_KEY = "docagent:ratelimit:{ip}"  # IP 限流计数
_CANCEL_KEY = "docagent:task:{tid}:cancelled"  # 取消标志位（Worker 协作退出）

_SNAPSHOT_TTL = settings.redis_snapshot_ttl_seconds  # 快照 Key 生存时间（秒）
_LOGS_MAX = settings.redis_logs_max  # 缓存日志条数上限（与轮询响应一致）
_RATELIMIT_TTL = settings.redis_ratelimit_ttl_seconds  # 限流窗口（秒）

_client: Any | None = None  # redis 客户端懒加载单例（None=未连接/连接失败）


def get_client() -> Any | None:
    """获取 Redis 客户端（懒加载，失败返回 None 且不缓存）。

    :return: redis.Redis 实例；连接失败返回 None（调用方降级）
    """
    global _client
    if _client is not None:
        return _client  # 已连接，直接复用
    try:
        import redis  # 延迟导入，依赖缺失不崩溃

        _client = redis.Redis.from_url(
            settings.redis_cache_url,  # redis://localhost:6379/2
            decode_responses=True,  # 自动解码字节为字符串
            socket_connect_timeout=settings.redis_connect_timeout_seconds,  # 连接超时（秒）
            socket_timeout=settings.redis_socket_timeout_seconds,  # 读写超时（秒）
        )
        _client.ping()  # 连通性探测，失败抛异常
        return _client
    except Exception as exc:  # 连接失败 / 依赖缺失
        _client = None  # 不缓存失败状态，下次调用重试
        logger.warning("[task_cache] Redis 连接失败，缓存降级: %s", exc)
        return None


def _keys(task_id: str) -> tuple[str, str, str, str]:
    """按任务 ID 生成四类缓存 Key。"""
    return (
        _STATUS_KEY.format(tid=task_id),
        _PROGRESS_KEY.format(tid=task_id),
        _STEP_KEY.format(tid=task_id),
        _LOGS_KEY.format(tid=task_id),
    )


def set_snapshot(
    task_id: str,
    *,
    status: str | None = None,
    progress: int | None = None,
    step: str | None = None,
) -> None:
    """写穿快照：覆盖 status/progress/step 中非空字段的 Key（TTL 3600s）。

    :param task_id: 任务 UUID
    :param status: 任务状态（pending/retrieving/.../success/failed，可空）
    :param progress: 进度百分比（0-100，可空）
    :param step: 当前步骤描述（可空）
    """
    client = get_client()
    if client is None:
        return  # Redis 不可用 → 静默降级
    try:
        sk, pk, step_k, _ = _keys(task_id)
        pipe = client.pipeline(transaction=False)
        if status is not None:
            pipe.set(sk, status, ex=_SNAPSHOT_TTL)
        if progress is not None:
            pipe.set(pk, str(progress), ex=_SNAPSHOT_TTL)
        if step is not None:
            pipe.set(step_k, step, ex=_SNAPSHOT_TTL)
        pipe.execute()
    except Exception as exc:  # 写穿失败仅告警
        logger.warning("[task_cache] 快照写穿失败: %s", exc)


def push_log(task_id: str, message: str) -> None:
    """写穿日志：RPUSH 到 logs List，裁剪至最近 20 条。

    :param task_id: 任务 UUID
    :param message: 带时间戳的日志行（"[HH:MM:SS] xxx"）
    """
    client = get_client()
    if client is None:
        return
    try:
        *_, lk = _keys(task_id)
        pipe = client.pipeline(transaction=False)
        pipe.rpush(lk, message)
        pipe.ltrim(lk, -_LOGS_MAX, -1)  # 仅保留最近 20 条
        pipe.expire(lk, _SNAPSHOT_TTL)
        pipe.execute()
    except Exception as exc:
        logger.warning("[task_cache] 日志写穿失败: %s", exc)


def get_snapshot(task_id: str) -> dict[str, Any] | None:
    """读快照：MGET 三键 + LRANGE 日志。

    :param task_id: 任务 UUID
    :return: {"status","progress","step","logs"}；快照不完整或 Redis
             不可用时返回 None（调用方降级 MySQL）
    """
    client = get_client()
    if client is None:
        return None
    try:
        sk, pk, step_k, lk = _keys(task_id)
        status, progress, step = client.mget(sk, pk, step_k)
        if status is None:  # 快照不存在（含三键均无值）
            return None
        logs = client.lrange(lk, 0, -1) or []  # 日志缺失视为空，调用方回填
        return {
            "status": status,
            "progress": int(progress or 0),
            "step": step,
            "logs": logs,
        }
    except Exception as exc:
        logger.warning("[task_cache] 快照读取失败: %s", exc)
        return None


def backfill(
    task_id: str, *, status: str, progress: int, step: str | None, logs: list[str]
) -> None:
    """回填快照：Redis 未命中时从 MySQL 数据整体写入（读侧兜底）。

    :param task_id: 任务 UUID
    :param status/progress/step/logs: MySQL 读取的任务三字段与日志列表
    """
    client = get_client()
    if client is None:
        return
    try:
        sk, pk, step_k, lk = _keys(task_id)
        pipe = client.pipeline(transaction=False)
        pipe.set(sk, status, ex=_SNAPSHOT_TTL)
        pipe.set(pk, str(progress), ex=_SNAPSHOT_TTL)
        if step:
            pipe.set(step_k, step, ex=_SNAPSHOT_TTL)
        if logs:
            pipe.rpush(lk, *logs[-_LOGS_MAX:])
            pipe.expire(lk, _SNAPSHOT_TTL)
        pipe.execute()
    except Exception as exc:
        logger.warning("[task_cache] 快照回填失败: %s", exc)


def set_cancelled_flag(task_id: str) -> None:
    """写取消标志位（TTL 3600s），Worker 节点入口轮询感知。

    :param task_id: 任务 UUID
    """
    client = get_client()
    if client is None:
        return  # Redis 不可用 → 依赖 MySQL 状态判定
    try:
        client.set(_CANCEL_KEY.format(tid=task_id), "1", ex=_SNAPSHOT_TTL)
    except Exception as exc:
        logger.warning("[task_cache] 取消标志写失败: %s", exc)


def get_cancelled_flag(task_id: str) -> bool | None:
    """读取消标志位。

    :param task_id: 任务 UUID
    :return: True=已取消；False=未取消；None=Redis 不可用（调用方降级 MySQL）
    """
    client = get_client()
    if client is None:
        return None
    try:
        return client.get(_CANCEL_KEY.format(tid=task_id)) == "1"
    except Exception as exc:
        logger.warning("[task_cache] 取消标志读失败: %s", exc)
        return None


def is_rate_limited(ip: str) -> bool:
    """IP 限流判定：窗口内（60s）请求数超过上限返回 True。

    :param ip: 客户端 IP（request.client.host）
    :return: True=触发限流（429）；Redis 不可用返回 False（fail-open）
    """
    client = get_client()
    if client is None:
        return False  # Redis 宕机不拦请求
    try:
        key = _RATELIMIT_KEY.format(ip=ip)
        count = client.incr(key)
        if count == 1:  # 首次请求：设置窗口 TTL
            client.expire(key, _RATELIMIT_TTL)
        return count > settings.api_rate_limit
    except Exception as exc:
        logger.warning("[task_cache] 限流判定失败，放行: %s", exc)
        return False
