"""
====================================================================
文件用途：SQLAlchemy 引擎与会话管理（数据库连接层）
====================================================================
作用：
    创建全局数据库引擎（engine）、会话工厂（SessionLocal），
    并提供 FastAPI 的请求级会话依赖（get_db）。
依赖：
    - app.config.settings.mysql_dsn：数据库连接串
调用方：
    - app/models/*.py   -> Base（所有 ORM 模型的公共基类）
    - app/crud/*.py     -> SessionLocal（数据访问）
    - 后续 API 路由     -> get_db（FastAPI 依赖注入）
说明：
    - 使用同步引擎 + PyMySQL 驱动，Celery Worker 与初始化脚本共用。
====================================================================
"""

from collections.abc import Generator  # 生成器类型（get_db 返回值注解）

from sqlalchemy import create_engine  # 创建数据库引擎
from sqlalchemy.orm import (  # ORM 基类 + 会话类型 + 会话工厂
    DeclarativeBase,
    Session,
    sessionmaker,
)

from app.config import settings  # 读取数据库连接配置

# ---------------- 全局引擎 ----------------
engine = create_engine(
    settings.mysql_dsn,       # 连接串：mysql+pymysql://...?charset=utf8mb4
    pool_size=10,             # 连接池基础大小（支撑 Celery 并发任务）
    max_overflow=20,          # 连接池可超出的最大连接数（高峰扩容）
    pool_pre_ping=True,       # 取连接前先探测，避免 MySQL 重启后拿到失效连接
    pool_recycle=3600,        # 连接 1 小时回收，防止 MySQL wait_timeout 断连
    echo=False,               # 不打印 SQL 日志（调试时可改为 True）
)

# ---------------- 会话工厂 ----------------
SessionLocal = sessionmaker(
    bind=engine,            # 绑定上面的引擎
    autoflush=False,        # 关闭自动 flush（避免隐式提前写入数据库）
    expire_on_commit=False, # 提交后不使对象属性过期（提交后仍可读取对象字段）
)


class Base(DeclarativeBase):
    """所有 ORM 模型的公共基类：SQLAlchemy 用它收集全部模型元数据。"""


def get_db() -> Generator[Session]:
    """FastAPI 依赖注入入口：为每个请求提供独立的数据库会话。

    :yield: 请求级数据库会话（路由处理器使用完毕后自动关闭）
    """
    db = SessionLocal()  # 创建请求级会话
    try:
        yield db         # 把会话交给路由处理器使用
    except Exception:
        db.rollback()    # 出现异常时回滚未提交的事务
        raise            # 继续向上抛异常（由全局异常处理兜底）
    finally:
        db.close()       # 无论成功失败，请求结束后关闭会话释放连接
