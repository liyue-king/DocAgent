"""
====================================================================
文件用途：credit_logs 表 ORM 模型（积分流水账）
====================================================================
作用：
    记录用户积分每一笔变动（充值/消费/调整），含变动后余额快照，
    供个人中心「积分明细」展示与对账。
依赖：
    - app.db.Base（ORM 基类）
    - app.models.user.User（外键归属）
调用方：
    - app/crud/users.py（add_credits / deduct_credit 内记账）
    - app/api/auth.py（/me 扩展返回最近明细）
说明：
    - amount 正数=收入（充值/赠送），负数=支出（任务消费）。
    - balance_after 为变动后的余额快照（幂等对账用）。
====================================================================
"""

from __future__ import annotations  # 延迟求值注解：配合 TYPE_CHECKING 解决前向引用报红

from datetime import datetime  # 时间戳类型
from typing import TYPE_CHECKING  # 类型检查专用标记

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, text  # 列类型
from sqlalchemy.dialects.mysql import DATETIME  # MySQL 专用 DATETIME（毫秒精度）
from sqlalchemy.orm import Mapped, mapped_column, relationship  # SQLAlchemy 2.0 映射

from app.db import Base  # ORM 公共基类

if TYPE_CHECKING:
    from app.models.user import User


class CreditLog(Base):
    """积分流水模型：对应 credit_logs 表。"""

    __tablename__ = "credit_logs"  # 表名

    # 主键：自增大整数
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 所属用户：外键 -> users.id，删用户级联删流水
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # 变动量：正=收入（充值），负=支出（任务消费）
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    # 变动后余额快照（对账/展示）
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    # 变动动作：register(注册赠送) / task_consume(任务消费) / recharge(充值到账)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    # 创建时间：毫秒精度
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        default=datetime.now,
        server_default=text("CURRENT_TIMESTAMP(3)"),
    )

    # 关系：多对一，流水 -> 用户
    user: Mapped[User] = relationship(back_populates="credit_logs")

    # 索引：按用户查最近流水（个人中心高频查询）
    __table_args__ = (Index("idx_user_created", "user_id", "created_at"),)

    def __repr__(self) -> str:  # pragma: no cover
        """调试友好的对象描述。"""
        return f"<CreditLog id={self.id} user={self.user_id} amount={self.amount}>"
