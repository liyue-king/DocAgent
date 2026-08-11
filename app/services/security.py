"""
====================================================================
文件用途：安全工具模块（密码哈希 + JWT 签发/校验）
====================================================================
作用：
    1. 密码哈希：PBKDF2-HMAC-SHA256 + 随机盐，格式
       "pbkdf2_sha256$iterations$salt_b64$hash_b64"，不依赖第三方库。
    2. JWT：标准 HS256 实现（Header.Payload.Signature），纯标准库
       hmac/base64 完成，避免为单点功能引入 PyJWT 依赖。
依赖：
    - 标准库 hashlib / hmac / base64 / json / secrets
    - app.config.settings（jwt_secret / jwt_algorithm / jwt_expire_hours）
调用方：
    - app/crud/users.py（注册时哈希密码、登录时校验）
    - app/api/auth.py（签发 token、解析当前用户）
说明：
    - JWT 密钥从 .env 读取；生产环境务必替换 jwt_secret。
    - 校验失败统一抛 AuthError（由 main.py 全局异常处理器转 401）。
====================================================================
"""

from __future__ import annotations

import base64  # Base64 编解码（盐/哈希/JWT 段）
import hashlib  # PBKDF2 / SHA256
import hmac  # 签名与常量时间比较
import json  # JWT Payload 序列化
import secrets  # 随机盐
import time  # 时间戳（iat/exp）
from typing import Any  # 泛型类型

from app.config import settings  # JWT 配置

_PBKDF2_ITERATIONS = 100_000  # PBKDF2 迭代次数（OWASP 推荐下限）
_SALT_BYTES = 16  # 盐长度（字节）


class AuthError(Exception):
    """认证异常：token 缺失/无效/过期或账号不可用。

    :param msg: 用户可读的错误信息
    :param code: 业务错误码（默认 1105 未登录）
    """

    def __init__(self, msg: str, code: int = 1105) -> None:
        super().__init__(msg)
        self.msg = msg
        self.code = code


def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 密码哈希（随机盐，不可逆）。

    :param password: 明文密码
    :return: "pbkdf2_sha256$100000$salt_b64$hash_b64"
    """
    salt = secrets.token_bytes(_SALT_BYTES)  # 每次注册随机盐
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return "$".join(
        [
            "pbkdf2_sha256",
            str(_PBKDF2_ITERATIONS),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(dk).decode("ascii"),
        ]
    )


def verify_password(password: str, stored: str) -> bool:
    """校验明文密码与存储哈希是否匹配（常量时间比较防时序攻击）。

    :param password: 待校验明文
    :param stored: 存储的哈希串
    :return: True=匹配；格式非法返回 False（不抛异常）
    """
    try:
        _algo, iters, salt_b64, hash_b64 = stored.split("$", 3)
        dk = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            base64.b64decode(salt_b64),
            int(iters),
        )
        return hmac.compare_digest(
            base64.b64encode(dk).decode("ascii"), hash_b64
        )
    except (ValueError, TypeError):  # 哈希格式损坏
        return False


def _b64url_encode(data: bytes) -> str:
    """Base64URL 编码（去填充，JWT 规范）。"""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    """Base64URL 解码（补齐填充，JWT 规范）。"""
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_token(
    user_id: int, email: str, token_version: int = 0, expire_hours: int | None = None
) -> str:
    """签发 HS256 JWT。

    :param user_id: 用户主键（sub 声明）
    :param email: 用户邮箱
    :param token_version: token 版本号（tv 声明），改密/改邮箱后 +1 使旧 token 失效
    :param expire_hours: 有效期（小时），默认取配置 jwt_expire_hours
    :return: "header.payload.signature" 三段式 token
    """
    now = int(time.time())
    expire_hours = expire_hours or settings.jwt_expire_hours  # 默认 72h
    header = {"alg": settings.jwt_algorithm, "typ": "JWT"}
    payload: dict[str, Any] = {
        "sub": str(user_id),  # 主题：用户 ID
        "email": email,
        "tv": token_version,  # token 版本号：改密/改邮箱后旧 token 立即失效
        "iat": now,  # 签发时间
        "exp": now + expire_hours * 3600,  # 过期时间
    }
    head = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{head}.{body}"
    signature = hmac.new(
        settings.jwt_secret.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def decode_token(token: str) -> dict[str, Any]:
    """校验并解析 JWT。

    :param token: 完整 token 字符串
    :return: payload 字典（含 sub/email/exp）
    :raises AuthError: 签名无效 / 格式非法 / 已过期
    """
    try:
        head_b64, body_b64, sig_b64 = token.split(".")
        signing_input = f"{head_b64}.{body_b64}"
        signature = _b64url_decode(sig_b64)
        expected = hmac.new(
            settings.jwt_secret.encode("utf-8"),
            signing_input.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(signature, expected):
            raise AuthError("登录状态无效，请重新登录")
        payload = json.loads(_b64url_decode(body_b64))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise AuthError("登录状态无效，请重新登录") from exc
    if int(payload.get("exp", 0)) < int(time.time()):  # 已过期
        raise AuthError("登录已过期，请重新登录", code=1105)
    return payload
