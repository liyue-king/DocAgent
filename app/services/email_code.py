"""
====================================================================
文件用途：QQ 邮箱验证码服务（SMTP 发送 + Redis 时效与校验）
====================================================================
作用：
    1. 生成 6 位数字验证码，通过 QQ 邮箱 SMTP（SSL 465）发送。
    2. 验证码存入 Redis（db=2，TTL 默认 5 分钟），支持时效校验；
       同时用冷却 Key 限制 60 秒内重复发送，用尝试次数 Key 限制
       连续输错（超 5 次强制重发，防爆破）。
Key 设计（对齐 task_cache 的 docagent: 前缀规范）：
    docagent:email_code:{email}          验证码本身（SET NX EX TTL）
    docagent:email_code_cooldown:{email} 发送冷却标记（EX 60s）
    docagent:email_code_attempts:{email} 错误尝试计数（INCR，随验证码过期）
依赖：
    - 标准库 smtplib / email / secrets
    - app.services.task_cache.get_client（复用 db=2 Redis 连接）
    - app.config.settings（SMTP 与 TTL 配置）
调用方：
    - app/api/auth.py（POST /auth/code 发送、注册时校验）
说明：
    - Redis 不可用时发送接口返回 1107（失败），避免无痕降级导致用户收不到码。
    - SMTP 账号需在 QQ 邮箱“设置→账户→开启 SMTP 服务”获取授权码。
====================================================================
"""

from __future__ import annotations

import logging  # 标准库日志
import secrets  # 安全随机数（生成验证码）
import smtplib  # SMTP 客户端
from email.header import Header  # 邮件头编码（中文主题）
from email.mime.text import MIMEText  # 纯文本邮件

from app.config import settings  # SMTP / TTL 配置
from app.services import task_cache  # 复用 Redis 客户端（db=2）

logger = logging.getLogger(__name__)  # 模块级日志器

# Redis Key 模板
_CODE_KEY = "docagent:email_code:{email}"  # 验证码
_COOLDOWN_KEY = "docagent:email_code_cooldown:{email}"  # 发送冷却
_ATTEMPTS_KEY = "docagent:email_code_attempts:{email}"  # 错误尝试计数


class EmailCodeError(Exception):
    """验证码业务异常（发送失败/过于频繁/无效）。"""

    def __init__(self, msg: str, code: int) -> None:
        super().__init__(msg)
        self.msg = msg
        self.code = code


def _send_mail(to_addr: str, code: str) -> None:
    """通过 SMTP_SSL 发送验证码邮件（QQ 邮箱 465 端口）。

    :param to_addr: 收件人邮箱
    :param code: 6 位验证码
    :raises EmailCodeError: 配置缺失或 SMTP 发送失败
    """
    if not settings.smtp_user or not settings.smtp_password:
        raise EmailCodeError("SMTP 未配置，请检查 .env", 4001)
    from_addr = settings.smtp_from or settings.smtp_user  # 发件人默认账号
    subject = "【DocAgent】邮箱验证码"
    body = (
        f"你好：\n\n"
        f"你的 DocAgent 验证码是：{code}\n"
        f"验证码 {settings.email_code_ttl_seconds // 60} 分钟内有效，"
        f"请勿泄露给他人。\n\n"
        f"如非本人操作，请忽略本邮件。"
    )
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")  # 中文主题
    msg["From"] = from_addr
    msg["To"] = to_addr
    try:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10) as s:
            s.login(settings.smtp_user, settings.smtp_password)  # 授权码登录
            s.sendmail(from_addr, [to_addr], msg.as_string())
    except Exception as exc:  # 网络/认证/超时等
        logger.warning("[email_code] 邮件发送失败: %s", exc)
        raise EmailCodeError("验证码发送失败，请稍后再试", 1107) from exc


def send_code(email: str) -> None:
    """生成验证码并发送，同时写入 Redis（TTL + 冷却）。

    :param email: 收件人邮箱（调用方已做格式校验）
    :raises EmailCodeError: 冷却期内 / 发送失败
    """
    client = task_cache.get_client()
    if client is None:
        raise EmailCodeError("验证码服务暂不可用，请稍后再试", 1107)
    cooldown_key = _COOLDOWN_KEY.format(email=email)
    try:
        if client.exists(cooldown_key):  # 60 秒内已发过
            raise EmailCodeError(
                f"发送过于频繁，请 {settings.email_code_cooldown_seconds} 秒后再试",
                1102,
            )
        code = f"{secrets.randbelow(1_000_000):06d}"  # 6 位随机码
        _send_mail(email, code)
        pipe = client.pipeline(transaction=False)
        pipe.set(_CODE_KEY.format(email=email), code, ex=settings.email_code_ttl_seconds)
        pipe.set(cooldown_key, "1", ex=settings.email_code_cooldown_seconds)
        pipe.execute()
    except EmailCodeError:
        raise
    except Exception as exc:  # Redis 写入失败
        logger.warning("[email_code] Redis 写入失败: %s", exc)
        raise EmailCodeError("验证码服务暂不可用，请稍后再试", 1107) from exc


def verify_code(email: str, code: str) -> bool:
    """校验验证码（时效 + 次数限制 + 匹配后一次性消费）。

    :param email: 用户邮箱
    :param code: 用户输入的验证码
    :return: True=校验通过；False=错误/过期/超次数
    """
    client = task_cache.get_client()
    if client is None:
        return False  # Redis 不可用一律视为校验失败
    try:
        code_key = _CODE_KEY.format(email=email)
        attempts_key = _ATTEMPTS_KEY.format(email=email)
        stored = client.get(code_key)
        if not stored:  # 验证码不存在（未发送或已过期/已消费）
            return False
        attempts = client.get(attempts_key)
        if attempts is not None and int(attempts) >= settings.email_code_max_attempts:
            client.delete(code_key, attempts_key)  # 超次数：作废验证码
            return False
        if secrets.compare_digest(stored, code.strip()):  # 匹配 → 一次性消费
            client.delete(code_key, attempts_key)
            return True
        client.incr(attempts_key)  # 记一次错误
        if client.ttl(attempts_key) < 0:  # 首次错误时对齐验证码 TTL
            client.expire(attempts_key, settings.email_code_ttl_seconds)
        return False
    except Exception as exc:
        logger.warning("[email_code] 校验异常: %s", exc)
        return False
