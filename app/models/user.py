"""
====================================================================
文件用途：users 表 ORM 模型（用户实体）
====================================================================
作用：
    定义 users 表的字段、约束与关系。P0 版本不做登录注册，
    所有任务默认挂载到匿名游客账户（id=1）。
依赖：
    - app.db.Base（ORM 基类）
调用方：
    - app/crud/users.py（用户 CRUD）
    - scripts/init_db.py（插入匿名游客，后续）
说明：
    - 电话/邮箱唯一索引已预留（P1 登录功能使用）。
    - created_at/updated_at 为 datetime(3) 毫秒精度，与蓝图 DDL 对齐。
====================================================================
"""

from __future__ import annotations  # 延迟求值注解：配合 TYPE_CHECKING 解决前向引用报红

from datetime import datetime  # 时间戳类型
from typing import TYPE_CHECKING  # 类型检查专用标记：仅 IDE/类型检查时导入

from sqlalchemy import BigInteger, Boolean, Integer, String, text  # 列类型与 SQL 表达式
from sqlalchemy.dialects.mysql import (
    DATETIME,  # MySQL 专用 DATETIME（支持毫秒精度 fsp=3）
)
from sqlalchemy.orm import (  # SQLAlchemy 2.0 映射 API
    Mapped,
    mapped_column,
    relationship,
)

from app.db import Base  # ORM 公共基类

if TYPE_CHECKING:
    # 仅用于类型检查/IDE 提示，运行时不会真正导入（避免循环导入）
    from app.models.task import Task


class User(Base):
    """用户模型：对应 users 表。"""

    __tablename__ = "users"  # 表名

    # 主键：自增大整数
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 手机号：唯一索引，可空（P1 登录预留）
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    # 邮箱：唯一索引，可空（P1 登录预留）
    email: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    # 密码哈希：默认空字符串（P1 启用登录后使用）
    password_hash: Mapped[str] = mapped_column(String(255), default="", server_default="")
    # 积分余额：免费额度 10 次
    credits_balance: Mapped[int] = mapped_column(Integer, default=10, server_default="10", comment="免费额度10次")
    # 是否启用：软删除/封禁标记
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    # 创建时间：毫秒精度，默认当前时间
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), default=datetime.now, server_default=text("CURRENT_TIMESTAMP(3)")
    )
    # 更新时间：毫秒精度，更新时自动刷新
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        default=datetime.now,
        server_default=text("CURRENT_TIMESTAMP(3)"),
        onupdate=datetime.now,
    )

    # 关系：一个用户拥有多个任务（反向导航 user.tasks）
    tasks: Mapped[list[Task]] = relationship(back_populates="user")

    def __repr__(self) -> str:  # pragma: no cover
        """调试友好的对象描述。"""
        return f"<User id={self.id} phone={self.phone}>"
