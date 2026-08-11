"""
====================================================================
文件用途：loguru 统一日志配置（API 网关 + Celery Worker 共用）
====================================================================
作用：
    1. 控制台 handler（人类可读彩色格式）+ 文件 handler（logs/ 按天
       轮转，20MB 滚动，保留 30 天，UTF-8）。
    2. 标准库 logging 拦截（InterceptHandler 转发 loguru），19 个
       既有模块用 logging.getLogger 打的日志零改动统一格式。
    3. uvicorn access/error 日志一并接管。
依赖：
    - loguru（pyproject 已加）
调用方：
    - app/main.py（uvicorn 入口）
    - app/celery_app.py（worker/beat 入口）
说明：
    - 进程内幂等：多次调用先 logger.remove() 清默认 handler 再重建。
    - enqueue=True 使文件写入走独立线程，避免多线程日志撕裂。
====================================================================
"""

from __future__ import annotations

import logging  # 标准库日志（被拦截转发）
import sys  # stderr 控制台输出
from pathlib import Path  # 日志目录路径

from loguru import logger  # 统一日志引擎

_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"  # 项目根 logs/

_CONSOLE_FORMAT = (
    "<green>{time:HH:mm:ss.SSS}</green> | "
    "<level>{level: <7}</level> | "
    "<cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)
_FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <7} | {name}:{line} - {message}"


class InterceptHandler(logging.Handler):
    """标准库 logging Handler → 转发 loguru（保留调用栈深度与异常信息）。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:  # 未知级别名（如 levelno 自定义）
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame is not None and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back  # 跳过 logging 内部帧
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_logging() -> None:
    """幂等配置根日志：控制台 + 文件轮转 + 标准库拦截。"""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.remove()  # 清默认 stderr handler，重建两处输出
    logger.add(
        sys.stderr,
        format=_CONSOLE_FORMAT,
        level="INFO",
        colorize=True,
        backtrace=False,  # 生产不打印全栈，避免噪音
        diagnose=False,
    )
    logger.add(
        _LOG_DIR / "docagent_{time:YYYY-MM-DD}.log",
        format=_FILE_FORMAT,
        level="DEBUG",
        rotation="20 MB",
        retention="30 days",
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )
    # 标准库 logging → loguru（force=True 覆盖根 logger 既有 handler）
    logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO, force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        std_logger = logging.getLogger(name)
        std_logger.handlers = [InterceptHandler()]
        std_logger.propagate = False
    logger.info("[logging] loguru 日志系统就绪（控制台 + logs/ 轮转文件）")
