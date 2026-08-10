"""
====================================================================
文件用途：认证 API 路由（注册 / 登录 / 验证码 / 当前用户）
====================================================================
接口（统一前缀 /api/v1/auth）：
    1. POST /code     —— 发送 QQ 邮箱验证码（Redis 时效存储）
    2. POST /register —— 邮箱 + 密码 + 验证码注册，签发 token
    3. POST /login    —— 邮箱 + 密码登录，签发 token
    4. GET  /me       —— 当前登录用户信息（含积分余额）
    5. POST /logout   —— 无状态登出（前端清除 token，返回成功）
错误码（本模块新增区间 11xx）：
    1101 验证码错误或已过期     1102 发送过于频繁
    1103 邮箱已被注册           1104 邮箱或密码错误
    1105 未登录/token 无效      1106 账号不可用
    1107 验证码服务/邮件发送失败
说明：
    - get_current_user / get_current_user_optional 供 pay / process 复用。
    - 认证失败抛 AuthError（main.py 全局处理器转 401 + {"code","msg"}）。
====================================================================
"""

from __future__ import annotations

import re  # 邮箱格式校验
from typing import Annotated, Any  # 依赖注入标注

from fastapi import APIRouter, Depends, Request  # 路由与依赖
from pydantic import BaseModel, Field  # 请求体模型
from sqlalchemy.exc import IntegrityError  # 邮箱唯一冲突
from sqlalchemy.orm import Session  # 数据库会话类型

from app.config import settings  # 管理员邮箱配置
from app.crud import users as user_crud  # 用户 CRUD
from app.db import get_db  # 会话注入
from app.models import User  # 用户模型
from app.services import email_code  # 邮箱验证码服务
from app.services.email_code import EmailCodeError  # 验证码业务异常
from app.services.security import (  # 安全工具
    AuthError,
    create_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])  # 认证路由

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")  # 简单邮箱格式


def _ok(**data: Any) -> dict[str, Any]:
    """成功响应：{"code":0, **data}（对齐蓝图 7.1 契约）。"""
    return {"code": 0, **data}


def _err(code: int, msg: str) -> dict[str, Any]:
    """业务错误响应：{"code":N, "msg":...}（HTTP 200）。"""
    return {"code": code, "msg": msg}


def serialize_user(user: User) -> dict[str, Any]:
    """用户信息脱敏序列化（不含 password_hash）。"""
    return {
        "id": user.id,
        "email": user.email,
        "credits_balance": user.credits_balance,
        "is_active": user.is_active,
        "is_admin": bool(user.is_admin),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _get_token(request: Request) -> str | None:
    """从 Authorization: Bearer xxx 头提取 token。"""
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()
    return None


def get_current_user(
    request: Request, db: Annotated[Session, Depends(get_db)] = None
) -> User:
    """FastAPI 依赖：解析 token 并加载当前用户（必需登录）。

    :raises AuthError: 无 token / 无效 / 过期 / 用户不存在或禁用
    """
    from app.services.security import decode_token  # 延迟导入避免循环

    token = _get_token(request)
    if not token:
        raise AuthError("未登录或登录已过期", code=1105)
    payload = decode_token(token)  # 无效/过期抛 AuthError
    user = user_crud.get_user(db, int(payload["sub"]))  # 主键查询
    if user is None:
        raise AuthError("用户不存在，请重新登录", code=1105)
    if not user.is_active:
        raise AuthError("账号已被禁用，请联系管理员", code=1106)
    return user


def get_current_user_optional(
    request: Request, db: Annotated[Session, Depends(get_db)] = None
) -> User | None:
    """FastAPI 依赖：可选登录（有有效 token 则返回用户，否则 None）。

    用于 /process：登录用户任务挂其账号，游客仍走匿名账户。
    """
    try:
        return get_current_user(request, db)
    except AuthError:
        return None  # 无 token / 过期一律视为游客


def get_current_admin(
    request: Request, db: Annotated[Session, Depends(get_db)] = None
) -> User:
    """FastAPI 依赖：仅管理员可访问（平台知识库维护接口）。

    :raises AuthError: 未登录(code=1105) / 非管理员(code=1108)
    """
    user = get_current_user(request, db)
    if not user.is_admin:
        raise AuthError("无权限：仅管理员可执行该操作", code=1108)
    return user


def _sync_admin_flag(db: Session, user: User) -> None:
    """按配置的管理员邮箱自动授予/收回管理员标记（幂等）。"""
    admins = {
        email.strip().lower()
        for email in settings.admin_emails.split(",")
        if email.strip()
    }
    is_admin = bool(user.email and user.email.lower() in admins)
    if bool(user.is_admin) != is_admin:
        user.is_admin = is_admin
        db.commit()
        db.refresh(user)


class SendCodeBody(BaseModel):
    """发送验证码请求体。"""

    email: str = Field(..., description="收件人邮箱")


class RegisterBody(BaseModel):
    """注册请求体（邮箱 + 密码 + 验证码）。"""

    email: str = Field(..., description="邮箱（同时作为登录名）")
    password: str = Field(..., min_length=6, max_length=64, description="密码（6-64位）")
    code: str = Field(..., min_length=6, max_length=6, description="邮箱验证码")


class LoginBody(BaseModel):
    """登录请求体。"""

    email: str = Field(..., description="邮箱")
    password: str = Field(..., description="密码")


def _valid_email(email: str) -> bool:
    """邮箱格式校验（简单正则，避免引入 email-validator 依赖）。"""
    return bool(_EMAIL_RE.match(email.strip()))


@router.post("/code")
def send_email_code(body: SendCodeBody) -> dict[str, Any]:
    """发送邮箱验证码：SMTP 发送 + Redis 存储（TTL + 冷却）。"""
    if not _valid_email(body.email):
        return _err(1001, "参数错误：邮箱格式不正确")
    try:
        email_code.send_code(body.email.lower())
    except EmailCodeError as exc:
        return _err(exc.code, exc.msg)
    return _ok(msg="验证码已发送，请查收邮件")


@router.post("/register")
def register(
    body: RegisterBody, db: Annotated[Session, Depends(get_db)] = None
) -> dict[str, Any]:
    """注册：校验验证码 → 邮箱唯一 → 建号 → 签发 token。"""
    if not _valid_email(body.email):
        return _err(1001, "参数错误：邮箱格式不正确")
    email = body.email.lower()
    # ---- 1. 验证码校验（时效 + 次数限制）----
    if not email_code.verify_code(email, body.code):
        return _err(1101, "验证码错误或已过期，请重新获取")
    # ---- 2. 邮箱唯一性 ----
    if user_crud.get_by_email(db, email) is not None:
        return _err(1103, "该邮箱已被注册，请直接登录")
    # ---- 3. 建号（并发冲突兜底）----
    try:
        user = user_crud.create_user(
            db, email=email, password_hash=hash_password(body.password)
        )
    except IntegrityError:
        db.rollback()
        return _err(1103, "该邮箱已被注册，请直接登录")
    _sync_admin_flag(db, user)  # 管理员邮箱注册时直接授予权限
    token = create_token(user.id, user.email)  # 注册即登录
    return _ok(token=token, user=serialize_user(user), msg="注册成功")


@router.post("/login")
def login(
    body: LoginBody, db: Annotated[Session, Depends(get_db)] = None
) -> dict[str, Any]:
    """登录：邮箱 + 密码校验，签发 token。"""
    if not _valid_email(body.email):
        return _err(1104, "邮箱或密码错误")
    email = body.email.lower()
    user = user_crud.get_by_email(db, email)
    # 统一错误文案（不泄露邮箱是否存在）
    if user is None or not verify_password(body.password, user.password_hash):
        return _err(1104, "邮箱或密码错误")
    if not user.is_active:
        return _err(1106, "账号已被禁用，请联系管理员")
    _sync_admin_flag(db, user)  # 管理员邮箱登录时同步权限
    token = create_token(user.id, user.email)
    return _ok(token=token, user=serialize_user(user), msg="登录成功")


@router.get("/me")
def me(user: Annotated[User, Depends(get_current_user)]) -> dict[str, Any]:
    """当前登录用户信息（含积分余额，前端导航展示）。"""
    return _ok(user=serialize_user(user))


@router.post("/logout")
def logout() -> dict[str, Any]:
    """无状态登出：JWT 无服务端状态，前端清除本地 token 即可。"""
    return _ok(msg="已退出登录")
