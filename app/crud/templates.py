"""
====================================================================
文件用途：templates 表 CRUD（模板数据访问）
====================================================================
作用：
    提供模板表的增删改查，供 RAG 检索、任务回填、初始化脚本使用。
依赖：
    - sqlalchemy.orm.Session（数据库会话）
    - app.models.Template（模板模型）
调用方：
    - app/agents/nodes/rag_searcher（后续：检索后取模板配置）
    - scripts/init_db.py（后续：灌入 10 种内置模板）
    - app/api/routes.py（后续：模板列表接口）
====================================================================
"""

from typing import Any  # 任意类型（模板 config 是 JSON）

from sqlalchemy.orm import Session  # 数据库会话类型

from app.models import Template  # 模板模型


def list_templates(db: Session) -> list[Template]:
    """查询全部模板（按 id 升序）。

    :param db: 数据库会话
    :return: 模板列表
    """
    return db.query(Template).order_by(Template.id.asc()).all()  # 按主键升序全量查询


def get_template(db: Session, template_id: int | None) -> Template | None:
    """按主键查询模板；template_id 为 None 时返回 None。

    :param db: 数据库会话
    :param template_id: 模板主键（可能为 None，如任务尚未命中模板）
    :return: 模板对象；不存在/入参为 None 时返回 None
    """
    if template_id is None:  # 入参为空直接返回，避免无效查询
        return None
    return db.get(Template, template_id)  # 主键查询


def get_by_name(db: Session, name: str) -> Template | None:
    """按名称查询模板（初始化脚本幂等用：已存在则不重复插入）。

    :param db: 数据库会话
    :param name: 模板名称（如"学术论文"）
    :return: 模板对象；不存在返回 None
    """
    return db.query(Template).filter(Template.name == name).first()  # 按名称精确查询


def create_template(
    db: Session,
    *,
    name: str,
    description: str,
    config: dict[str, Any],
    vector_id: str | None = None,
    is_system: bool = True,
) -> Template:
    """创建模板（初始化脚本使用）。

    :param db: 数据库会话
    :param name: 模板名称
    :param description: 模板语义描述（RAG 检索用）
    :param config: 样式配置 JSON
    :param vector_id: ChromaDB 向量文档 ID（可空，灌向量后回填）
    :param is_system: 是否系统内置模板
    :return: 创建后的模板对象
    """
    tpl = Template(  # 构造模板对象
        name=name,
        description=description,
        config=config,
        vector_id=vector_id,
        is_system=is_system,
    )
    db.add(tpl)  # 加入会话
    db.commit()  # 提交事务
    db.refresh(tpl)  # 刷新对象（回填自增主键）
    return tpl  # 返回模板


def update_template(
    db: Session,
    template_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
    config: dict[str, Any] | None = None,
) -> Template | None:
    """更新模板字段（管理员后台使用）。

    :param db: 数据库会话
    :param template_id: 模板主键
    :param name/description/config: 待更新字段（None=不更新）
    :return: 更新后的模板对象；不存在返回 None
    """
    tpl = db.get(Template, template_id)
    if tpl is None:
        return None
    if name is not None:
        tpl.name = name
    if description is not None:
        tpl.description = description
    if config is not None:
        tpl.config = config
    db.commit()
    db.refresh(tpl)
    return tpl


def delete_template(db: Session, template_id: int) -> bool:
    """删除模板（管理员后台使用）。

    :param db: 数据库会话
    :param template_id: 模板主键
    :return: 是否删除成功（不存在返回 False）
    """
    tpl = db.get(Template, template_id)
    if tpl is None:
        return False
    db.delete(tpl)
    db.commit()
    return True


def increment_usage_count(db: Session, template_id: int) -> None:
    """模板命中计数 +1（用于 RAG 结果统计）。

    :param db: 数据库会话
    :param template_id: 模板主键
    """
    tpl = db.get(Template, template_id)  # 查询模板
    if tpl is not None:  # 模板存在才计数
        tpl.usage_count += 1  # 命中次数 +1
        db.commit()  # 提交事务
