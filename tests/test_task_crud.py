"""任务 CRUD 测试（SQLite 内存库，覆盖全生命周期状态机）。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from app.crud import tasks as crud
from app.models import TaskStatus


def _tid() -> str:
    return str(uuid.uuid4())


def _create(db, task_id: str, user_id: int = 1):
    return crud.create_task(
        db,
        task_id=task_id,
        prompt_text="帮我排版",
        input_file_name="a.docx",
        input_file_hash="h",
        input_file_path="2026/08/10/t/a.docx",
        user_id=user_id,
    )


def test_create_and_get(db_session) -> None:
    tid = _tid()
    task = _create(db_session, tid)
    assert task.status == TaskStatus.PENDING
    assert task.progress == 0
    got = crud.get_task(db_session, tid)
    assert got is not None and got.id == tid
    assert crud.get_task(db_session, _tid()) is None


def test_update_task_whitelist(db_session) -> None:
    """update_task 白名单：非表列字段不写入。"""
    tid = _tid()
    _create(db_session, tid)
    crud.update_task(db_session, tid, progress=50, not_a_column="ignored")
    task = crud.get_task(db_session, tid)
    assert task.progress == 50
    assert not hasattr(task, "not_a_column")


def test_status_transitions(db_session) -> None:
    """pending → started → executing → success 全链路。"""
    tid = _tid()
    _create(db_session, tid)
    crud.mark_started(db_session, tid)
    assert crud.get_task(db_session, tid).started_at is not None
    crud.set_running(db_session, tid, TaskStatus.EXECUTING, 60, "样式修改执行中")
    t = crud.get_task(db_session, tid)
    assert t.status == TaskStatus.EXECUTING and t.progress == 60
    assert t.current_step == "样式修改执行中"
    crud.mark_success(db_session, tid, output_file_path="out.docx", processing_time_ms=100)
    t = crud.get_task(db_session, tid)
    assert t.status == TaskStatus.SUCCESS
    assert t.progress == 100
    assert t.output_file_path == "out.docx"
    assert t.completed_at is not None


def test_mark_failed(db_session) -> None:
    tid = _tid()
    _create(db_session, tid)
    crud.mark_failed(db_session, tid)
    assert crud.get_task(db_session, tid).status == TaskStatus.FAILED


def test_list_expired_tasks(db_session) -> None:
    """已过期的非终态任务被列出；终态（success）不再判过期。"""
    tid = _tid()
    _create(db_session, tid, )
    crud.update_task(db_session, tid, expires_at=datetime.now() - timedelta(hours=1))
    assert any(t.id == tid for t in crud.list_expired_tasks(db_session))
    crud.mark_success(db_session, tid, output_file_path="o", processing_time_ms=1)
    assert not any(t.id == tid for t in crud.list_expired_tasks(db_session))


def test_list_tasks_by_user_isolation(db_session) -> None:
    """按用户隔离：只看自己的任务，不分页返回全量。"""
    ids = [_create(db_session, _tid(), user_id=7).id for _ in range(3)]
    _create(db_session, _tid(), user_id=8)  # 其他用户的任务
    tasks = crud.list_tasks_by_user(db_session, 7)
    assert len(tasks) == 3
    assert {t.id for t in tasks} == set(ids)
    assert all(t.user_id == 7 for t in tasks)
    assert crud.list_tasks_by_user(db_session, 999) == []
