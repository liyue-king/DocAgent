"""
====================================================================
文件用途：支付宝支付 API 路由（下单 / 异步通知 / 主动查单）
====================================================================
接口（统一前缀 /api/v1/pay）：
    1. POST /create        —— 登录用户下单（pro ¥29 / team ¥99），
                               返回支付宝沙箱收银台跳转 URL
    2. POST /notify        —— 支付宝异步通知（验签 → 落库 → 加积分）
    3. GET  /query/{order} —— 主动查询订单状态（前端跳回后轮询）
    4. GET  /orders        —— 当前用户的订单列表
错误码（本模块新增区间 12xx）：
    1201 订单不存在          1202 无权限访问该订单
    1203 支付宝回调验签失败  1204 支付宝下单/查询失败
说明：
    - notify 为纯文本协议：成功返回 "success"，失败返回 "failure"。
    - 加积分由 mark_paid 原子状态守卫保证幂等（回调与查单双通道安全）。
====================================================================
"""

from __future__ import annotations

import logging  # 标准库日志
import secrets  # 随机订单号
from datetime import datetime  # 订单号时间戳
from decimal import Decimal  # 金额
from typing import Annotated, Any  # 依赖注入标注

from fastapi import APIRouter, Depends, Request  # 路由与依赖
from fastapi.responses import PlainTextResponse  # 支付宝回调响应
from pydantic import BaseModel, Field  # 请求体模型
from sqlalchemy.orm import Session  # 数据库会话类型

from app.api.auth import get_current_user  # 登录依赖
from app.crud import payments as payment_crud  # 订单 CRUD
from app.crud import users as user_crud  # 用户 CRUD
from app.db import get_db  # 会话注入
from app.models import Payment, User  # 模型
from app.services.alipay import (  # 支付宝服务
    PLAN_CATALOG,
    AlipayError,
    build_page_pay_url,
    is_trade_success,
    query_order,
    verify_notify,
)

logger = logging.getLogger(__name__)  # 模块级日志器

router = APIRouter(prefix="/api/v1/pay", tags=["pay"])  # 支付路由


def _ok(**data: Any) -> dict[str, Any]:
    """成功响应：{"code":0, **data}。"""
    return {"code": 0, **data}


def _err(code: int, msg: str) -> dict[str, Any]:
    """业务错误响应：{"code":N, "msg":...}（HTTP 200）。"""
    return {"code": code, "msg": msg}


def _gen_order_id() -> str:
    """生成商户订单号：时间戳 + 8 位随机（全局唯一）。"""
    return datetime.now().strftime("%Y%m%d%H%M%S") + secrets.token_hex(4).upper()


def serialize_order(order: Payment) -> dict[str, Any]:
    """订单信息序列化（供前端展示/轮询）。"""
    return {
        "order_id": order.order_id,
        "plan_id": order.plan_id,
        "plan_name": order.plan_name,
        "amount": str(order.amount),
        "credits": order.credits,
        "status": order.status,
        "alipay_trade_no": order.alipay_trade_no,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
    }


class CreateOrderBody(BaseModel):
    """下单请求体。"""

    plan_id: str = Field(..., description="套餐标识：pro / team")


@router.post("/create")
def create_payment(
    body: CreateOrderBody,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)] = None,
) -> dict[str, Any]:
    """创建支付宝订单并返回收银台跳转 URL。"""
    plan = PLAN_CATALOG.get(body.plan_id)
    if plan is None:  # 未知套餐
        return _err(1001, "参数错误：未知的套餐")
    order_id = _gen_order_id()  # 商户订单号
    try:
        # 先构建支付 URL（密钥/APP_ID 缺失时直接报错，不落脏订单）
        pay_url = build_page_pay_url(
            order_id=order_id,
            amount=plan["price"],
            subject=f"DocAgent {plan['name']}",
            plan_name=plan["desc"],
        )
    except AlipayError as exc:  # 密钥/APP_ID 未配置
        logger.error("[pay] 下单失败: %s", exc.msg)
        return _err(exc.code, exc.msg)
    order = payment_crud.create_order(
        db,
        order_id=order_id,
        user_id=user.id,
        plan_id=body.plan_id,
        plan_name=plan["name"],
        amount=Decimal(plan["price"]),
        credits=plan["credits"],
    )
    return _ok(order=serialize_order(order), pay_url=pay_url, msg="订单已创建")


@router.post("/notify")
async def alipay_notify(request: Request) -> PlainTextResponse:
    """支付宝异步通知：验签 → 更新订单 → 发放积分。

    返回纯文本 "success"/"failure"（支付宝会重试 failure 通知）。
    """
    form = await request.form()  # 表单参数
    params = {k: v for k, v in form.items()}
    if not verify_notify(params):  # 签名校验失败
        logger.warning("[pay] 通知验签失败: %s", params.get("out_trade_no"))
        return PlainTextResponse("failure")
    out_trade_no = params.get("out_trade_no", "")
    trade_status = params.get("trade_status", "")
    if not is_trade_success(trade_status):  # 非终态（如 WAIT_BUYER_PAY）不处理
        return PlainTextResponse("success")
    db = next(get_db())  # 手动会话（通知路径无 FastAPI 依赖）
    try:
        order = payment_crud.get_order(db, out_trade_no)
        if order is None:
            logger.warning("[pay] 通知订单不存在: %s", out_trade_no)
            return PlainTextResponse("failure")
        # 原子状态守卫：仅 pending → paid 且发放积分（幂等）
        paid = payment_crud.mark_paid(
            db,
            out_trade_no,
            alipay_trade_no=params.get("trade_no", ""),
            buyer_id=params.get("buyer_id"),
        )
        if paid is not None:
            user_crud.add_credits(db, order.user_id, order.credits)
            logger.info(
                "[pay] 支付成功到账: order=%s user=%s credits=%s",
                out_trade_no,
                order.user_id,
                order.credits,
            )
        return PlainTextResponse("success")
    except Exception as exc:  # 落库失败：返回 failure 让支付宝重试
        db.rollback()
        logger.error("[pay] 通知处理异常: %s", exc)
        return PlainTextResponse("failure")
    finally:
        db.close()


@router.get("/query/{order_id}")
def query_payment(
    order_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)] = None,
) -> dict[str, Any]:
    """主动查询订单：DB 优先，pending 时向支付宝二次确认。"""
    order = payment_crud.get_order(db, order_id)
    if order is None:
        return _err(1201, "订单不存在")
    if order.user_id != user.id:  # 只能查自己的订单
        return _err(1202, "无权访问该订单")
    if order.status == "pending":  # 未收到回调 → 主动查支付宝
        try:
            resp = query_order(order_id)
            if is_trade_success(resp.get("trade_status")):
                paid = payment_crud.mark_paid(
                    db,
                    order_id,
                    alipay_trade_no=resp.get("trade_no", ""),
                    buyer_id=resp.get("buyer_logon_id"),
                )
                if paid is not None:
                    user_crud.add_credits(db, order.user_id, order.credits)
                order = payment_crud.get_order(db, order_id)
        except AlipayError as exc:
            logger.warning("[pay] 查单失败: %s", exc.msg)
            return _err(exc.code, exc.msg)
    return _ok(order=serialize_order(order))


@router.get("/orders")
def my_orders(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)] = None,
) -> dict[str, Any]:
    """当前用户订单列表（新→旧）。"""
    orders = payment_crud.list_orders(db, user.id)
    return _ok(orders=[serialize_order(o) for o in orders])
