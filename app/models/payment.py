"""
====================================================================
文件用途：payments 表 ORM 模型（支付宝订单）
====================================================================
作用：
    记录用户购买套餐的支付订单：订单号（out_trade_no）、套餐、
    金额、状态（pending/paid/closed/failed）与支付宝回传的交易号。
依赖：
    - app.db.Base（ORM 基类）
调用方：
    - app/crud/payments.py（创建/查询/标记已支付）
    - app/api/pay.py（下单与回调落库）
说明：
    - order_id 为商户订单号，全局唯一，支付宝回调以它定位订单。
    - status 不建 ENUM（字符串即可），与 tasks 表状态机风格保持一致。
====================================================================
"""

from __future__ import annotations

from datetime import datetime  # 时间戳
from decimal import Decimal  # 金额
from typing import TYPE_CHECKING  # 类型检查标记

from sqlalchemy import (  # SQLAlchemy 核心组件
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.mysql import DATETIME, DECIMAL  # MySQL 专用类型
from sqlalchemy.orm import Mapped, mapped_column, relationship  # SQLAlchemy 2.0 映射

from app.db import Base  # ORM 公共基类

if TYPE_CHECKING:
    from app.models.user import User


class Payment(Base):
    """支付订单模型：对应 payments 表。"""

    __tablename__ = "payments"  # 表名

    # 主键：自增大整数
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 商户订单号（支付宝 out_trade_no），全局唯一
    order_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    # 下单用户：外键 -> users.id
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    # 套餐标识（pro/team）
    plan_id: Mapped[str] = mapped_column(String(20), nullable=False)
    # 套餐名称（快照，套餐改名不影响历史订单）
    plan_name: Mapped[str] = mapped_column(String(50), nullable=False)
    # 订单金额（元，两位小数）
    amount: Mapped[Decimal] = mapped_column(DECIMAL(10, 2), nullable=False)
    # 到账额度（次）
    credits: Mapped[int] = mapped_column(Integer, nullable=False)
    # 订单状态：pending / paid / closed / failed
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending"
    )
    # 支付宝交易号（支付成功后回填）
    alipay_trade_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 买家支付宝账号（回调回填）
    buyer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 支付成功时间
    paid_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    # 创建 / 更新时间（毫秒精度）
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        default=datetime.now,
        server_default=text("CURRENT_TIMESTAMP(3)"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        default=datetime.now,
        server_default=text("CURRENT_TIMESTAMP(3)"),
        onupdate=datetime.now,
    )

    # 关系：订单 -> 用户（反向 user.payments）
    user: Mapped[User] = relationship(back_populates="payments")

    # 索引：按用户查订单 / 按订单号查（唯一索引自带）
    __table_args__ = (Index("idx_payments_user", "user_id", "created_at"),)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Payment order_id={self.order_id} status={self.status}>"
