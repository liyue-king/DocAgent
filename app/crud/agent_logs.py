"""
====================================================================
文件用途：agent_logs 表 CRUD（Agent 步骤日志数据访问）
====================================================================
作用：
    提供 Agent 执行日志的追加与查询，是前端“日志终端”和
    Redis 日志缓存（db=2）的数据来源。
依赖：
    - sqlalchemy.orm.Session（数据库会话）
    - app.models.AgentLog / LogLevel（日志模型与级别枚举）
调用方：
    - app/agents/nodes/*（后续：各节点写入执行日志）
    - app/api/routes.py（后续：状态查询接口返回 logs）
====================================================================
"""

from sqlalchemy.orm import Session  # 数据库会话类型

from app.models import AgentLog, LogLevel  # 日志模型与级别枚举


def add_log(
    db: Session,
    *,
    task_id: str,
    agent_node: str,
    message: str,
    level: LogLevel = LogLevel.INFO,
) -> AgentLog:
    """追加一条 Agent 日志。

    :param db: 数据库会话
    :param task_id: 所属任务 UUID
    :param agent_node: 产生日志的节点名（如 executor）
    :param message: 日志正文
    :param level: 日志级别，默认 INFO
    :return: 创建后的日志对象
    """
    log = AgentLog(  # 构造日志对象
        task_id=task_id,
        agent_node=agent_node,
        log_level=level,
        log_message=message,
    )
    db.add(log)  # 加入会话
    db.commit()  # 提交事务
    db.refresh(log)  # 刷新对象（回填自增主键）
    return log  # 返回日志


def list_logs(db: Session, task_id: str, limit: int = 20) -> list[AgentLog]:
    """返回最近 limit 条日志（时间正序，供终端展示）。

    :param db: 数据库会话
    :param task_id: 任务 UUID
    :param limit: 最多返回条数，默认 20（与 Redis 缓存上限一致）
    :return: 时间正序的日志列表
    """
    rows = (  # 先按 id 倒序取最近 limit 条
        db.query(AgentLog)
        .filter(AgentLog.task_id == task_id)  # 过滤指定任务
        .order_by(AgentLog.id.desc())  # 按主键倒序（最新在前）
        .limit(limit)  # 只取最近 limit 条
        .all()
    )
    return list(reversed(rows))  # 反转回正序（旧 -> 新），符合终端展示习惯
