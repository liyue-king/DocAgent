"""
====================================================================
文件用途：payments 表 CRUD（支付宝订单数据访问）
====================================================================
作用：
    提供订单创建、查询、支付成功落库（幂等：同一订单只到账一次）。
依赖：
    - sqlalchemy.orm.Session
    - app.models.Payment（订单模型）
调用方：
    - app/api/pay.py（下单 / 通知 / 查单）
说明：
    - mark_paid 带状态守卫：仅 pending 订单可转为 paid，防止
      异步通知与主动查单双通道重复加积分。
====================================================================
"""

from __future__ import annotations

from datetime import datetime  # 支付时间
from decimal import Decimal  # 金额

from sqlalchemy import update  # 原子条件更新
from sqlalchemy.orm import Session  # 数据库会话类型

from app.models import Payment  # 订单模型


def create_order(
    db: Session,
    *,
    order_id: str,
    user_id: int,
    plan_id: str,
    plan_name: str,
    amount: Decimal,
    credits: int,
) -> Payment:
    """创建支付订单（初始状态 pending）。

    :param db: 数据库会话
    :param order_id: 商户订单号（out_trade_no，唯一）
    :param user_id: 下单用户
    :param plan_id: 套餐标识
    :param plan_name: 套餐名称
    :param amount: 订单金额（元）
    :param credits: 到账额度（次）
    :return: 创建的订单对象
    """
    order = Payment(
        order_id=order_id,
        user_id=user_id,
        plan_id=plan_id,
        plan_name=plan_name,
        amount=amount,
        credits=credits,
        status="pending",
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def get_order(db: Session, order_id: str) -> Payment | None:
    """按商户订单号查询订单。"""
    return db.query(Payment).filter(Payment.order_id == order_id).first()


def list_orders(db: Session, user_id: int, limit: int = 50) -> list[Payment]:
    """查询用户最近订单（新→旧）。"""
    return (
        db.query(Payment)
        .filter(Payment.user_id == user_id)
        .order_by(Payment.created_at.desc())
        .limit(limit)
        .all()
    )


def mark_paid(
    db: Session, order_id: str, alipay_trade_no: str, buyer_id: str | None = None
) -> Payment | None:
    """订单支付成功落库（幂等：仅 pending 可转 paid）。

    :param db: 数据库会话
    :param order_id: 商户订单号
    :param alipay_trade_no: 支付宝交易号
    :param buyer_id: 买家支付宝账号
    :return: 更新后的订单；订单不存在或非 pending 返回 None
    """
    result = db.execute(
        update(Payment)
        .where(
            Payment.order_id == order_id,
            Payment.status == "pending",  # 状态守卫：仅 pending 可转 paid
        )
        .values(
            status="paid",
            alipay_trade_no=alipay_trade_no,
            buyer_id=buyer_id,
            paid_at=datetime.now(),
        )
    )
    if result.rowcount == 0:  # 订单不存在或已处理
        db.rollback()
        return None
    db.commit()
    return get_order(db, order_id)
