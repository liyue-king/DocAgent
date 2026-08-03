"""
====================================================================
文件用途：tasks 表 CRUD（任务全生命周期数据访问）
====================================================================
作用：
    提供任务从“创建 → 状态流转 → 成功/失败收尾”的全过程数据操作，
    是 LangGraph 状态机与 API 路由共同依赖的核心数据层。
依赖：
    - sqlalchemy.orm.Session（数据库会话）
    - app.models.Task / TaskStatus（任务模型与状态枚举）
    - app.config.settings（任务过期时长）
调用方：
    - app/api/routes.py（后续：提交/查询任务）
    - app/agents/nodes/*（后续：各节点更新任务状态）
    - scripts/cleanup（后续：过期任务清理）
====================================================================
"""

from datetime import datetime, timedelta  # 时间戳与时间差
from decimal import Decimal  # 高精度金额
from typing import Any  # 任意字段类型

from sqlalchemy.orm import Session  # 数据库会话类型

from app.config import settings  # 读取任务过期时长配置
from app.models import Task, TaskStatus  # 任务模型与状态枚举


def create_task(
    db: Session,
    *,
    task_id: str,
    prompt_text: str,
    input_file_name: str,
    input_file_hash: str,
    input_file_path: str,
    user_id: int = 1,
    template_id: int | None = None,
    expires_at: datetime | None = None,
) -> Task:
    """新建任务（初始状态 pending）。

    :param db: 数据库会话
    :param task_id: 任务 UUID（与 Celery task_id 一致）
    :param prompt_text: 用户自然语言需求
    :param input_file_name: 上传文件名
    :param input_file_hash: 文件哈希
    :param input_file_path: MinIO 输入对象路径
    :param user_id: 所属用户，默认匿名游客 1
    :param template_id: 命中的模板（可选；通常由 RAG 检索后回填）
    :param expires_at: 过期时间，默认 now + 24h
    :return: 创建后的任务对象
    """
    now = datetime.now()  # 当前时间（计算默认过期时间）
    task = Task(  # 构造任务对象
        id=task_id,                    # 任务 ID
        user_id=user_id,               # 所属用户
        template_id=template_id,       # 关联模板（可空）
        prompt_text=prompt_text,       # 需求文本
        input_file_name=input_file_name,  # 文件名
        input_file_hash=input_file_hash,  # 文件哈希
        input_file_path=input_file_path,  # 输入路径
        status=TaskStatus.PENDING,     # 初始状态：待处理
        expires_at=expires_at or (now + timedelta(hours=settings.task_expire_hours)),  # 过期时间（默认 24h）
    )
    db.add(task)  # 加入会话
    db.commit()  # 提交事务
    db.refresh(task)  # 刷新对象（回填数据库生成字段）
    return task  # 返回任务


def get_task(db: Session, task_id: str) -> Task | None:
    """按 UUID 查询任务。

    :param db: 数据库会话
    :param task_id: 任务 UUID
    :return: 任务对象；不存在返回 None
    """
    return db.get(Task, task_id)  # 主键查询


def update_task(db: Session, task_id: str, **fields: Any) -> Task | None:
    """通用字段更新（status/progress/current_step/template_id/retry_count 等）。

    :param db: 数据库会话
    :param task_id: 任务 UUID
    :param fields: 需要更新的字段（键值对）
    :return: 更新后的任务；任务不存在返回 None
    """
    task = db.get(Task, task_id)  # 查询任务
    if task is None:  # 任务不存在
        return None  # 直接返回
    # 白名单校验：只允许更新“真实的表列”，排除 relationship 等非列属性，防止误传污染关系
    allowed = Task.__table__.columns.keys()  # 表列名集合（status/progress/...）
    for key, value in fields.items():  # 遍历待更新字段
        if key in allowed:  # 仅更新表中真实存在的列
            setattr(task, key, value)  # 赋值
    db.commit()  # 提交事务
    db.refresh(task)  # 刷新对象
    return task  # 返回更新后的任务


def set_running(
    db: Session, task_id: str, status: TaskStatus, progress: int, step: str | None = None
) -> Task | None:
    """推进状态机（retrieving/planning/executing/validating 阶段通用）。

    :param db: 数据库会话
    :param task_id: 任务 UUID
    :param status: 目标状态
    :param progress: 进度百分比（0-100）
    :param step: 当前步骤描述
    :return: 更新后的任务
    """
    return update_task(db, task_id, status=status, progress=progress, current_step=step)  # 委托通用更新


def mark_started(db: Session, task_id: str) -> Task | None:
    """Worker 开始执行时调用，记录 started_at。

    :param db: 数据库会话
    :param task_id: 任务 UUID
    :return: 更新后的任务
    """
    return update_task(db, task_id, started_at=datetime.now())  # 记录开始时间


def mark_success(
    db: Session,
    task_id: str,
    *,
    output_file_path: str,
    processing_time_ms: int,
    llm_total_tokens: int = 0,
    cost_usd: Decimal = Decimal(0),
) -> Task | None:
    """任务成功收尾：写入输出路径与运行指标。

    :param db: 数据库会话
    :param task_id: 任务 UUID
    :param output_file_path: MinIO 输出对象路径
    :param processing_time_ms: 处理耗时（毫秒）
    :param llm_total_tokens: LLM 消耗 token 数
    :param cost_usd: LLM 费用（USD）
    :return: 更新后的任务
    """
    return update_task(  # 委托通用更新
        db,
        task_id,
        status=TaskStatus.SUCCESS,      # 状态 -> 成功
        progress=100,                   # 进度 -> 100%
        output_file_path=output_file_path,  # 回填输出路径
        completed_at=datetime.now(),    # 记录完成时间
        processing_time_ms=processing_time_ms,  # 记录耗时
        llm_total_tokens=llm_total_tokens,      # 记录 token
        cost_usd=cost_usd,                      # 记录费用
    )


def mark_failed(db: Session, task_id: str) -> Task | None:
    """任务失败收尾。错误详情通过 agent_logs 记录（ERROR 级）。

    :param db: 数据库会话
    :param task_id: 任务 UUID
    :return: 更新后的任务
    """
    return update_task(db, task_id, status=TaskStatus.FAILED, completed_at=datetime.now())  # 状态->失败+完成时间


def mark_expired(db: Session, task_id: str) -> Task | None:
    """任务过期（24h 生命周期结束，文件将被 MinIO ILM 清理）。

    :param db: 数据库会话
    :param task_id: 任务 UUID
    :return: 更新后的任务
    """
    return update_task(db, task_id, status=TaskStatus.EXPIRED)  # 状态 -> 过期


def list_expired_tasks(db: Session, now: datetime | None = None) -> list[Task]:
    """查询所有已过期的非终态任务（清理任务用，P1）。

    :param db: 数据库会话
    :param now: 参考时间，默认当前时间
    :return: 满足条件的任务列表
    """
    now = now or datetime.now()  # 取参考时间（默认现在）
    return (
        db.query(Task)
        .filter(
            Task.expires_at < now,  # 已过过期时间
            Task.status.notin_([TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.EXPIRED]),  # 且非终态
        )
        .all()
    )
