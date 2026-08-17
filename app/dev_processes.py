"""
====================================================================
文件用途：开发态随 API 网关自动拉起/回收 Celery Worker 与 Beat
====================================================================
作用：
    在 IDEA 里直接运行 uvicorn（app.main:app）时，若 .env 开启
    AUTO_START_WORKER / AUTO_START_BEAT，则由 FastAPI lifespan 自动
    拉起 celery worker/beat 子进程，网关停止时一并回收——省去每次
    手动开终端敲命令（dev_up.ps1 打印的 3 条）。
依赖：
    - app.config.settings（开关配置）
    - sys.executable（复用当前解释器：python -m celery ...）
说明：
    - 仅限开发态；Docker/生产（worker/beat 独立容器）默认关闭。
    - 子进程日志落 logs/celery_worker.log、logs/celery_beat.log
      （logs/ 已 gitignore；daily 轮转日志另有 docagent_*.log）。
    - PID 文件防重复拉起：启动前清理上次异常退出遗留的进程，
      仅杀镜像名含 python/celery 的进程，防 PID 复用误杀无辜进程。
    - Windows 注意：os.kill(pid, 0) 在 Windows 会真的 TerminateProcess，
      存活检测改用 OpenProcess/GetExitCodeProcess（STILL_ACTIVE）。
====================================================================
"""

from __future__ import annotations

import ctypes  # Windows 进程 API（存活/镜像名检测）
import logging  # 标准库日志（loguru 已拦截）
import os  # os.kill 终止子进程
import signal  # SIGTERM
import subprocess  # Popen 拉起 celery
import sys  # sys.executable（复用当前解释器）
import time  # 启动窗口轮询
from ctypes import wintypes  # ctypes 类型
from pathlib import Path  # 日志/PID 文件路径

from app.config import settings  # 自动拉起开关

logger = logging.getLogger(__name__)  # 模块级日志器

_PROJECT_ROOT = Path(__file__).resolve().parent.parent  # 项目根目录
_LOG_DIR = _PROJECT_ROOT / "logs"  # 子进程日志目录（已 gitignore）

_STILL_ACTIVE = 259  # Windows 进程仍在运行的状态码
_QUERY_LIMITED_INFO = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION 权限位


def _pid_alive(pid: int) -> bool:
    """Windows 安全检测进程存活（os.kill(pid, 0) 会真的杀进程，禁用）。"""
    handle = ctypes.windll.kernel32.OpenProcess(_QUERY_LIMITED_INFO, False, pid)
    if not handle:
        return False  # 进程不存在或权限不足 → 视为已退出
    try:
        code = wintypes.DWORD()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return code.value == _STILL_ACTIVE
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _pid_is_python(pid: int) -> bool:
    """进程镜像名是否含 python/celery（防 PID 复用误杀无辜进程）。"""
    handle = ctypes.windll.kernel32.OpenProcess(_QUERY_LIMITED_INFO, False, pid)
    if not handle:
        return False
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(
            handle, 0, buf, ctypes.byref(size)
        )
        if not ok:
            return False
        image = buf.value.lower()
        return "python" in image or "celery" in image
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _cleanup_leftover(pid_file: Path) -> None:
    """清理上次异常退出遗留的进程与 PID 文件（异常仅告警，不影响启动）。"""
    if not pid_file.exists():
        return
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pid_file.unlink(missing_ok=True)
        return
    pid_file.unlink(missing_ok=True)  # 无论是否存活，先清除失效 PID 文件
    if pid > 0 and _pid_alive(pid) and _pid_is_python(pid):
        try:
            os.kill(pid, signal.SIGTERM)  # Windows 下等价 TerminateProcess
            logger.warning("[dev] 清理遗留进程 pid=%s (%s)", pid, pid_file.stem)
        except OSError as exc:
            logger.warning("[dev] 清理遗留进程失败: %s", exc)


def _spawn(role: str, extra_args: list[str]) -> subprocess.Popen | None:
    """拉起 celery 子进程（worker/beat 共用），日志落 logs/<role>.log。

    :param role: celery_worker / celery_beat（PID 与日志文件名前缀）
    :param extra_args: celery 子命令参数（如 ["worker", "-P", "solo", ...]）
    """
    _LOG_DIR.mkdir(exist_ok=True)
    pid_file = _LOG_DIR / f"{role}.pid"
    log_file = _LOG_DIR / f"{role}.log"
    _cleanup_leftover(pid_file)  # 防重复拉起
    cmd = [sys.executable, "-m", "celery", "-A", "app.celery_app", *extra_args]
    child_env = dict(os.environ)  # 子进程环境
    child_env.setdefault("PYTHONUTF8", "1")  # 强制 UTF-8，避免中文 Windows 日志写 GBK
    child_env.setdefault("PYTHONIOENCODING", "utf-8")
    log_handle = open(log_file, "a", encoding="utf-8")  # noqa: SIM115  # 句柄交子进程 stdout，生命周期超出本函数，不能用 with
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(_PROJECT_ROOT),  # celery -A 按项目根解析模块
            env=child_env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,  # stdout/stderr 合并入日志文件
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    except Exception as exc:
        log_handle.close()
        logger.error("[dev] %s 启动失败: %s", role, exc)
        return None
    pid_file.write_text(str(proc.pid), encoding="utf-8")
    time.sleep(2)  # 给足启动窗口，即刻崩溃时留下明确告警
    if proc.poll() is not None:
        logger.error(
            "[dev] %s 启动后即退出（exit=%s），请查看 %s",
            role, proc.returncode, log_file,
        )
        return None
    logger.info("[dev] %s 已随网关启动 pid=%s 日志=%s", role, proc.pid, log_file)
    return proc


def start_dev_worker() -> subprocess.Popen | None:
    """开发态拉起 Celery Worker（受 AUTO_START_WORKER 开关控制）。"""
    if not settings.auto_start_worker:
        return None
    return _spawn("celery_worker", ["worker", "-P", "solo", "--loglevel=info"])


def start_dev_beat() -> subprocess.Popen | None:
    """开发态拉起 Celery Beat 周期清扫（受 AUTO_START_BEAT 开关控制）。"""
    if not settings.auto_start_beat:
        return None
    return _spawn("celery_beat", ["beat", "--loglevel=info"])


def stop_dev_process(proc: subprocess.Popen | None, role: str) -> None:
    """网关停止时回收子进程（先 SIGTERM 优雅退出，超时强杀）。"""
    if proc is None or proc.poll() is not None:
        return  # 未启动或已自行退出
    try:
        os.kill(proc.pid, signal.SIGTERM)
        proc.wait(timeout=5)
        logger.info("[dev] %s 已随网关停止 pid=%s", role, proc.pid)
    except (OSError, subprocess.TimeoutExpired):
        proc.kill()
        logger.warning("[dev] %s 优雅退出超时，已强杀 pid=%s", role, proc.pid)
    finally:
        (_LOG_DIR / f"{role}.pid").unlink(missing_ok=True)  # 清除 PID 文件
