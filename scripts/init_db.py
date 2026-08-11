"""
====================================================================
脚本用途：初始化数据库（幂等，可重复执行）
====================================================================
作用：
    1. 导入全部 ORM 模型 → Base.metadata.create_all 创建缺失的表
       （现有表不动，只补缺失表；users.is_admin 列用幂等 ALTER 补齐）。
    2. 确保匿名游客账号（id=1，999 次额度）存在。
    3. 将 ADMIN_EMAILS 配置的邮箱批量提升为管理员（幂等）。
运行：PYTHONPATH=. python scripts/init_db.py
====================================================================
"""

from __future__ import annotations

from sqlalchemy import inspect, text  # 表结构检查 / 原生 DDL

from app.config import settings  # 管理员邮箱配置
from app.crud import users  # 用户 CRUD（游客账号）
from app.db import Base, SessionLocal, engine  # ORM 引擎与会话
from app.models import (  # noqa: F401  # 导入全部模型注册到 Base.metadata
    AgentLog,
    ChatMessage,
    CreditLog,
    KnowledgeDoc,
    Payment,
    Task,
    Template,
    User,
)


def _ensure_user_admin_column() -> None:
    """幂等补充 users.is_admin 列（create_all 不会修改已存在的表）。"""
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("users")}
    if "is_admin" in columns:
        print("[init_db] users.is_admin 列已存在")
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN is_admin "
                "TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否管理员'"
            )
        )
    print("[init_db] users.is_admin 列已添加")


def _ensure_user_token_version_column() -> None:
    """幂等补充 users.token_version 列（U4 新增，改密/重置后失效旧 token）。"""
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("users")}
    if "token_version" in columns:
        print("[init_db] users.token_version 列已存在")
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN token_version "
                "INT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'token 版本号（改密/重置后+1）'"
            )
        )
    print("[init_db] users.token_version 列已添加")


def _ensure_task_status_cancelled() -> None:
    """幂等补充 tasks.status ENUM 的 cancelled 值（U2 取消新增，create_all 不修改已存在表）。

    早期版本建表时 ENUM 缺 'cancelled'，写入时报 1265 Data truncated。
    """
    from app.models.enums import TaskStatus

    values = ",".join(f"'{m.value}'" for m in TaskStatus)  # 与枚举严格对齐
    with engine.connect() as conn:
        row = conn.execute(text("SHOW COLUMNS FROM tasks LIKE 'status'")).fetchone()
    if row and "cancelled" in row[1]:
        print("[init_db] tasks.status ENUM 已含 cancelled")
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE tasks MODIFY COLUMN status "
                f"ENUM({values}) NOT NULL DEFAULT 'pending' COMMENT '任务状态九态枚举'"
            )
        )
    print("[init_db] tasks.status ENUM 已补充 cancelled 值")


def _promote_admin_emails() -> None:
    """按 ADMIN_EMAILS 配置批量提升管理员（幂等）。"""
    admins = {
        email.strip().lower()
        for email in settings.admin_emails.split(",")
        if email.strip()
    }
    if not admins:
        print("[init_db] 未配置 ADMIN_EMAILS，跳过管理员提升")
        return
    with engine.begin() as conn:
        for email in admins:
            conn.execute(
                text("UPDATE users SET is_admin = 1 WHERE LOWER(email) = :email"),
                {"email": email},
            )
    print(f"[init_db] 管理员邮箱已提升：{', '.join(sorted(admins))}")


def main() -> None:
    """建表 + 补列 + 游客账号 + 管理员提升。"""
    Base.metadata.create_all(bind=engine)  # 幂等：只创建缺失的表
    _ensure_user_admin_column()  # 已存在的 users 表补 is_admin 列
    _ensure_user_token_version_column()  # 已存在的 users 表补 token_version 列
    _ensure_task_status_cancelled()  # 已存在的 tasks 表补 status ENUM 的 cancelled 值
    _promote_admin_emails()  # 配置的管理员邮箱授权
    print("[init_db] 数据表检查完成（缺失表已创建）")

    db = SessionLocal()
    try:
        guest = users.get_or_create_anonymous(db)  # 幂等创建游客
        print(f"[init_db] 匿名游客账号就绪：id={guest.id} credits={guest.credits_balance}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
