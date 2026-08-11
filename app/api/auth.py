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


def serialize_credit_log(log: object) -> dict[str, Any]:
    """积分流水脱敏序列化（个人中心「积分明细」展示）。"""
    return {
        "id": log.id,
        "amount": log.amount,
        "balance_after": log.balance_after,
        "action": log.action,
        "created_at": log.created_at.isoformat() if log.created_at else None,
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
    # tv 版本号校验：改密/改邮箱后旧 token 立即失效
    if int(payload.get("tv", 0)) != (user.token_version or 0):
        raise AuthError("登录状态已失效，请重新登录", code=1105)
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
    """按配置的管理员邮箱自动授予管理员标记（幂等）。

    只自动提升、不自动撤销：管理员在后台手动授权的账号不会被
    下一次登录时收回，避免「用户管理」中设置的权限失效。
    """
    admins = {
        email.strip().lower()
        for email in settings.admin_emails.split(",")
        if email.strip()
    }
    if user.email and user.email.lower() in admins and not user.is_admin:
        user.is_admin = True
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
    token = create_token(user.id, user.email, token_version=user.token_version)  # 注册即登录
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
    token = create_token(user.id, user.email, token_version=user.token_version)
    return _ok(token=token, user=serialize_user(user), msg="登录成功")


@router.get("/me")
def me(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)] = None,
) -> dict[str, Any]:
    """当前登录用户信息（含积分余额 + 最近 10 条积分明细）。"""
    logs = user_crud.list_credit_logs(db, user.id, limit=10)  # 最近明细
    return _ok(
        user=serialize_user(user),
        credit_logs=[serialize_credit_log(log) for log in logs],
    )


class ChangePasswordBody(BaseModel):
    """修改密码请求体（旧密码 + 新密码）。"""

    old_password: str = Field(..., description="当前密码")
    new_password: str = Field(..., min_length=6, max_length=64, description="新密码（6-64位）")


class ChangeEmailBody(BaseModel):
    """修改邮箱请求体（新邮箱 + 验证码）。"""

    email: str = Field(..., description="新邮箱")
    code: str = Field(..., min_length=6, max_length=6, description="邮箱验证码")


class ResetPasswordBody(BaseModel):
    """忘记密码重置请求体（邮箱 + 验证码 + 新密码）。"""

    email: str = Field(..., description="注册邮箱")
    code: str = Field(..., min_length=6, max_length=6, description="邮箱验证码")
    password: str = Field(..., min_length=6, max_length=64, description="新密码（6-64位）")


@router.post("/change-password")
def change_password(
    body: ChangePasswordBody,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)] = None,
) -> dict[str, Any]:
    """修改密码：校验旧密码 → 更新哈希 + token_version+1 → 签发新 token。"""
    if not verify_password(body.old_password, user.password_hash):
        return _err(1104, "原密码不正确")
    user.password_hash = hash_password(body.new_password)
    user.token_version = (user.token_version or 0) + 1  # 旧 token 全部失效
    db.commit()
    db.refresh(user)
    token = create_token(user.id, user.email, token_version=user.token_version)
    return _ok(token=token, msg="密码修改成功")


@router.post("/change-email")
def change_email(
    body: ChangeEmailBody,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)] = None,
) -> dict[str, Any]:
    """修改邮箱：验证码校验 → 新邮箱唯一 → 更新 + token_version+1 → 签发新 token。"""
    if not _valid_email(body.email):
        return _err(1001, "参数错误：邮箱格式不正确")
    new_email = body.email.lower()
    # ---- 1. 验证码校验（发给新邮箱）----
    if not email_code.verify_code(new_email, body.code):
        return _err(1101, "验证码错误或已过期，请重新获取")
    # ---- 2. 新邮箱唯一性（排除自己）----
    existed = user_crud.get_by_email(db, new_email)
    if existed is not None and existed.id != user.id:
        return _err(1103, "该邮箱已被注册")
    # ---- 3. 更新邮箱 + 版本号 + 管理员标记 ----
    user.email = new_email
    user.token_version = (user.token_version or 0) + 1  # 旧 token 全部失效
    db.commit()
    db.refresh(user)
    _sync_admin_flag(db, user)  # 新邮箱可能命中管理员配置
    token = create_token(user.id, user.email, token_version=user.token_version)
    return _ok(token=token, user=serialize_user(user), msg="邮箱修改成功")


@router.post("/logout")
def logout() -> dict[str, Any]:
    """无状态登出：JWT 无服务端状态，前端清除本地 token 即可。"""
    return _ok(msg="已退出登录")


@router.post("/reset")
def reset_password(
    body: ResetPasswordBody, db: Annotated[Session, Depends(get_db)] = None
) -> dict[str, Any]:
    """忘记密码重置：验证码校验 → 更新密码 + token_version+1（旧 token 全部失效）。"""
    if not _valid_email(body.email):
        return _err(1001, "参数错误：邮箱格式不正确")
    email = body.email.lower()
    # ---- 1. 验证码校验 ----
    if not email_code.verify_code(email, body.code):
        return _err(1101, "验证码错误或已过期，请重新获取")
    # ---- 2. 用户存在性 ----
    user = user_crud.get_by_email(db, email)
    if user is None:
        return _err(1104, "该邮箱未注册")  # 不泄露信息，但需明确提示
    # ---- 3. 更新密码 + 版本号 ----
    user.password_hash = hash_password(body.password)
    user.token_version = (user.token_version or 0) + 1  # 重置后所有旧 token 失效
    db.commit()
    return _ok(msg="密码重置成功，请使用新密码登录")
