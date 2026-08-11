"""
====================================================================
文件用途：管理员 API 路由（用户管理 / 订单补登）
====================================================================
接口（统一前缀 /api/v1/admin）：
    1. GET  /users                   —— 用户列表（支持按邮箱/ID 搜索）
    2. PATCH /users/{user_id}        —— 修改用户（额度 / 启用状态 / 管理员标记）
    3. GET  /users/{user_id}/orders  —— 查看指定用户的订单
    4. POST /orders/{order_id}/mark-paid —— 补登支付成功（手动到账）
说明：
    - 全部接口仅管理员可访问（get_current_admin）。
    - 防止管理员降级/禁用自己，避免锁死后台。
====================================================================
"""

from __future__ import annotations

import logging  # 标准库日志
from typing import Annotated, Any  # 依赖注入标注

from fastapi import APIRouter, Depends  # 路由与依赖
from pydantic import BaseModel, Field  # 请求体模型
from sqlalchemy.orm import Session  # 数据库会话类型

from app.api.auth import get_current_admin  # 管理员依赖
from app.api.pay import serialize_order  # 订单序列化（复用）
from app.crud import payments as payment_crud  # 订单 CRUD
from app.crud import users as user_crud  # 用户 CRUD
from app.db import get_db  # 会话注入
from app.models import User  # 用户模型

logger = logging.getLogger(__name__)  # 模块级日志器

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])  # 管理员路由


def _ok(**data: Any) -> dict[str, Any]:
    """成功响应：{"code":0, **data}。"""
    return {"code": 0, **data}


def _err(code: int, msg: str) -> dict[str, Any]:
    """业务错误响应：{"code":N, "msg":...}（HTTP 200）。"""
    return {"code": code, "msg": msg}


def serialize_user(user: User) -> dict[str, Any]:
    """用户信息序列化（不含密码哈希）。"""
    return {
        "id": user.id,
        "email": user.email,
        "credits_balance": user.credits_balance,
        "is_active": bool(user.is_active),
        "is_admin": bool(user.is_admin),
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }


@router.get("/users")
def list_users(
    _admin: Annotated[Any, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)] = None,
    search: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """用户列表：支持按邮箱或用户 ID 搜索，分页返回。"""
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    users, total = user_crud.list_users(
        db, search=search.strip(), limit=limit, offset=offset
    )
    return _ok(
        users=[serialize_user(u) for u in users],
        total=total,
        limit=limit,
        offset=offset,
    )


class UpdateUserBody(BaseModel):
    """修改用户请求体（至少传一个字段）。"""

    credits_balance: int | None = Field(None, ge=0, le=1000000, description="调整后余额")
    is_active: bool | None = Field(None, description="是否启用")
    is_admin: bool | None = Field(None, description="是否管理员")


@router.patch("/users/{user_id}")
def update_user(
    user_id: int,
    body: UpdateUserBody,
    admin: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)] = None,
) -> dict[str, Any]:
    """修改用户：余额 / 启用状态 / 管理员标记（管理员不能禁用/降级自己）。"""
    if body.credits_balance is None and body.is_active is None and body.is_admin is None:
        return _err(1001, "参数错误：至少提供一个要修改的字段")
    if user_id == admin.id:
        if body.is_admin is False:
            return _err(1001, "不能取消自己的管理员权限")
        if body.is_active is False:
            return _err(1001, "不能禁用自己的账号")

    user = user_crud.update_user_profile(
        db,
        user_id,
        credits_balance=body.credits_balance,
        is_active=body.is_active,
        is_admin=body.is_admin,
    )
    if user is None:
        return _err(2001, "用户不存在")
    return _ok(user=serialize_user(user), msg="用户信息已更新")


@router.get("/users/{user_id}/orders")
def user_orders(
    user_id: int,
    _admin: Annotated[Any, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)] = None,
) -> dict[str, Any]:
    """查看指定用户的订单列表（新 → 旧）。"""
    if user_crud.get_user(db, user_id) is None:
        return _err(2001, "用户不存在")
    orders = payment_crud.list_orders(db, user_id, limit=100)
    return _ok(orders=[serialize_order(o) for o in orders])


@router.post("/orders/{order_id}/mark-paid")
def mark_order_paid(
    order_id: str,
    _admin: Annotated[Any, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)] = None,
) -> dict[str, Any]:
    """补登支付成功：将 pending 订单置为 paid 并向用户发放积分（幂等）。"""
    order = payment_crud.get_order(db, order_id)
    if order is None:
        return _err(1201, "订单不存在")
    if order.status != "pending":
        return _err(2002, f"订单当前状态为「{order.status}」，无需补登")
    paid = payment_crud.mark_paid(
        db,
        order_id,
        alipay_trade_no=f"manual-{order_id}",
        buyer_id=None,
    )
    if paid is None:
        return _err(2002, "订单状态已变化，请刷新后重试")
    user_crud.add_credits(db, paid.user_id, paid.credits, action="recharge")
    logger.info(
        "[admin] 补登支付成功: order=%s user=%s credits=%s",
        order_id,
        paid.user_id,
        paid.credits,
    )
    return _ok(order=serialize_order(paid), msg=f"已补登到账 {paid.credits} 次额度")
