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

from sqlalchemy import String, cast, or_  # 搜索/类型转换
from sqlalchemy.exc import IntegrityError  # 主键/唯一约束冲突异常（并发兜底）
from sqlalchemy.orm import Session  # 数据库会话类型

from app.models import CreditLog, User  # 积分流水 / 用户模型


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


def create_user(
    db: Session, email: str, password_hash: str, credits_balance: int = 10
) -> User:
    """注册新用户（邮箱唯一，冲突抛 IntegrityError）。

    :param db: 数据库会话
    :param email: 用户邮箱（唯一索引）
    :param password_hash: 密码哈希（security.hash_password 生成）
    :param credits_balance: 初始额度，默认 10 次（免费版）
    :return: 创建后的用户
    :raises IntegrityError: 邮箱已存在（调用方捕获转业务错误）
    """
    user = User(
        email=email,
        password_hash=password_hash,
        credits_balance=credits_balance,
    )
    db.add(user)
    db.flush()  # 先拿到自增 id，再写注册赠送流水
    _write_credit_log(db, user.id, credits_balance, credits_balance, "register")
    db.commit()
    db.refresh(user)
    return user


def _write_credit_log(
    db: Session, user_id: int, amount: int, balance_after: int, action: str
) -> None:
    """写一笔积分流水（与余额变动同事务，保证对账一致）。"""
    db.add(
        CreditLog(
            user_id=user_id,
            amount=amount,
            balance_after=balance_after,
            action=action,
        )
    )


def add_credits(
    db: Session, user_id: int, amount: int, action: str = "recharge"
) -> User | None:
    """给用户增加积分（支付成功到账），同时记一笔收入流水。

    :param db: 数据库会话
    :param user_id: 用户主键
    :param amount: 增加额度（次）
    :param action: 流水动作，默认 recharge（充值到账）
    :return: 更新后的用户；用户不存在返回 None
    """
    user = db.get(User, user_id)
    if user is None:
        return None
    user.credits_balance += amount  # 余额累加
    _write_credit_log(db, user.id, amount, user.credits_balance, action)  # 同事务记账
    db.commit()
    db.refresh(user)
    return user


def deduct_credit(
    db: Session, user_id: int, amount: int = 1, action: str = "task_consume"
) -> bool:
    """扣减用户积分（任务消费），成功时记一笔支出流水。

    :param db: 数据库会话
    :param user_id: 用户主键
    :param amount: 扣减数量，默认 1
    :param action: 流水动作，默认 task_consume（任务消费）
    :return: 是否扣减成功（余额不足返回 False）
    """
    user = db.get(User, user_id)  # 查询用户
    if user is None or user.credits_balance < amount:  # 用户不存在或余额不足
        return False  # 扣减失败
    user.credits_balance -= amount  # 扣减余额
    _write_credit_log(db, user.id, -amount, user.credits_balance, action)  # 同事务记账
    db.commit()  # 提交事务
    return True  # 扣减成功


def list_credit_logs(db: Session, user_id: int, limit: int = 20) -> list[CreditLog]:
    """查询用户最近积分流水（个人中心展示，按时间倒序）。"""
    return (
        db.query(CreditLog)
        .filter(CreditLog.user_id == user_id)
        .order_by(CreditLog.created_at.desc(), CreditLog.id.desc())
        .limit(limit)
        .all()
    )


def list_users(
    db: Session,
    search: str = "",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[User], int]:
    """分页查询用户（管理员用户管理）：支持按邮箱 / ID 模糊搜索。"""
    query = db.query(User)
    if search:
        keyword = f"%{search}%"
        query = query.filter(
            or_(
                User.email.like(keyword),
                cast(User.id, String).like(keyword),
            )
        )
    total = query.count()
    users = query.order_by(User.id.asc()).offset(offset).limit(limit).all()
    return users, total


def update_user_profile(
    db: Session,
    user_id: int,
    *,
    credits_balance: int | None = None,
    is_active: bool | None = None,
    is_admin: bool | None = None,
) -> User | None:
    """管理员修改用户资料：余额（记账）/ 启用状态 / 管理员标记。"""
    user = db.get(User, user_id)
    if user is None:
        return None
    if credits_balance is not None:
        delta = int(credits_balance) - user.credits_balance
        if delta != 0:
            user.credits_balance = int(credits_balance)
            _write_credit_log(
                db,
                user.id,
                delta,
                user.credits_balance,
                "admin_adjust",
            )
    if is_active is not None:
        user.is_active = bool(is_active)
    if is_admin is not None:
        user.is_admin = bool(is_admin)
    db.commit()
    db.refresh(user)
    return user
