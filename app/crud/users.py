"""
====================================================================
文件用途：users 表 CRUD（用户数据访问）
====================================================================
作用：
    提供用户表的增删改查。P0 阶段核心是“匿名游客”账户管理
    （get_or_create_anonymous），其余方法为 P1 登录/计费预留。
依赖：
    - sqlalchemy.orm.Session（数据库会话）
    - app.models.User（用户模型）
调用方：
    - app/api/routes.py（后续：创建任务时挂载匿名用户）
    - scripts/init_db.py（后续：初始化游客账户）
====================================================================
"""

from sqlalchemy.exc import IntegrityError  # 主键/唯一约束冲突异常（并发兜底）
from sqlalchemy.orm import Session  # 数据库会话类型

from app.models import User  # 用户模型


def get_user(db: Session, user_id: int) -> User | None:
    """按主键查询用户。

    :param db: 数据库会话
    :param user_id: 用户主键
    :return: 用户对象；不存在返回 None
    """
    return db.get(User, user_id)  # 主键查询（走缓存，性能最优）


def get_or_create_anonymous(db: Session) -> User:
    """获取 P0 匿名游客（id=1），不存在则创建。

    P0 版本不做登录，所有任务默认挂载到该账户。
    :param db: 数据库会话
    :return: 匿名游客用户对象
    """
    user = db.get(User, 1)  # 先按主键查 id=1
    if user is None:  # 数据库中还没有游客账户
        try:
            user = User(id=1, credits_balance=999)  # 构造游客对象（999 次免费额度）
            db.add(user)  # 加入会话
            db.commit()  # 提交事务，写入数据库
        except IntegrityError:  # 并发下两个请求同时创建，后者会主键冲突
            db.rollback()  # 回滚本次插入
            user = db.get(User, 1)  # 重新查询已存在的游客（必定存在）
        db.refresh(user)  # 刷新对象（回填数据库生成的字段）
    return user  # 返回游客用户


def get_by_email(db: Session, email: str) -> User | None:
    """按邮箱查询用户（P1 登录功能预留）。

    :param db: 数据库会话
    :param email: 用户邮箱
    :return: 用户对象；不存在返回 None
    """
    return db.query(User).filter(User.email == email).first()  # 条件查询取第一条


def deduct_credit(db: Session, user_id: int, amount: int = 1) -> bool:
    """扣减用户积分（P1 计费预留）。

    :param db: 数据库会话
    :param user_id: 用户主键
    :param amount: 扣减数量，默认 1
    :return: 是否扣减成功（余额不足返回 False）
    """
    user = db.get(User, user_id)  # 查询用户
    if user is None or user.credits_balance < amount:  # 用户不存在或余额不足
        return False  # 扣减失败
    user.credits_balance -= amount  # 扣减余额
    db.commit()  # 提交事务
    return True  # 扣减成功
