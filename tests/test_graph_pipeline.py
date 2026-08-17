"""LangGraph 全链路集成测试：编排闭环 / 重试闭环 / cancel 竞态 / 兜底语义。

覆盖 bug 清单 2/3/4/5/13/14：worker 终态守卫、success_node 取消守卫、
retry_count 落库、entry_guard fallback 语义闭环、build_graph 编译缓存。
全部为单元级集成（SQLite 内存库 + 真实 docx + 节点替换），不依赖外部服务。
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest

from app.crud import tasks as crud
from app.models import TaskStatus


def _seed_config() -> dict:
    """读取种子模板配置（学术论文，供确定性路径使用）。"""
    seed_path = Path(__file__).resolve().parent.parent / "scripts" / "seed_templates.json"
    return json.loads(seed_path.read_text(encoding="utf-8"))[0]["config"]


@pytest.fixture()
def graph_env(db_session, monkeypatch, tmp_path: Path):
    """图集成测试环境：节点持久化落 SQLite 内存库 + checkpoint 隔离。"""
    monkeypatch.setattr("app.db.SessionLocal", lambda: db_session)
    from app.config import settings

    monkeypatch.setattr(settings, "checkpoint_db_path", ":memory:")

    from app.agents import graph as graph_mod

    graph_mod.clear_graph_cache()  # 清缓存：保证本次编译读取被替换的节点
    try:
        yield graph_mod, db_session, tmp_path
    finally:
        graph_mod.clear_graph_cache()


def _degrade_storage(monkeypatch) -> None:
    """MinIO 不可用模拟：所有上传抛异常（节点应降级不中断）。"""
    from app.services.storage import storage

    def _boom(*args, **kwargs):
        raise RuntimeError("minio down (test)")

    monkeypatch.setattr(storage, "upload_file", _boom)
    monkeypatch.setattr(storage, "upload_bytes", _boom)


def _make_task(db_session, tid: str) -> None:
    """建任务行（游客 user_id=1，不触发积分扣减）。"""
    crud.create_task(
        db_session,
        task_id=tid,
        prompt_text="帮我排版",
        input_file_name="a.docx",
        input_file_hash="h",
        input_file_path="2026/08/11/t/a.docx",
    )


def test_graph_full_pipeline_success_real(graph_env, test_docx_path, monkeypatch) -> None:
    """全链路编排（真实执行）：最终 SUCCESS + 输出文件 + DB 状态推进。"""
    graph_mod, db_session, _ = graph_env
    tid = str(uuid.uuid4())
    _make_task(db_session, tid)
    _degrade_storage(monkeypatch)
    config = _seed_config()

    def fake_rag(state):
        return {
            "selected_template_id": None,
            "selected_template_config": config,
            "retrieved_templates": [],
            "status": "planning",
        }

    monkeypatch.setattr("app.agents.nodes.rag_searcher_node", fake_rag)

    final = graph_mod.run_agent(
        {
            "task_id": tid,
            "user_prompt": "帮我排版",  # 无个性化关键词 → 确定性路径，0 token
            "working_file_path": test_docx_path,
            "input_file_path": "in/a.docx",
        }
    )
    assert final["status"] == "done"
    assert os.path.exists(final["output_file_path"])
    task = crud.get_task(db_session, tid)
    assert task is not None
    assert task.status == TaskStatus.SUCCESS
    assert task.progress == 100
    assert task.output_file_path == final["output_file_path"]
    assert task.retry_count == 0


def test_graph_retry_loop_closes_and_persists_retry_count(
    graph_env, test_docx_path, monkeypatch
) -> None:
    """重试闭环：validator 首次不达标 → planner 增量修补 → 二次达标 → SUCCESS。

    同时验证 bug 4：retry_count 通过 notify 落库（前端展示不再恒 0）。
    """
    graph_mod, db_session, _ = graph_env
    tid = str(uuid.uuid4())
    _make_task(db_session, tid)
    _degrade_storage(monkeypatch)
    config = _seed_config()

    def fake_rag(state):
        return {
            "selected_template_id": None,
            "selected_template_config": config,
            "retrieved_templates": [],
            "status": "planning",
        }

    monkeypatch.setattr("app.agents.nodes.rag_searcher_node", fake_rag)

    calls = {"n": 0}
    failing = {
        "passed": False,
        "coverage": 0.5,
        "total": 6,
        "matched": 3,
        "missed": [
            {
                "para_id": 1,
                "style": "normal",
                "text_preview": "这是正文段落",
                "reason": "font_size",
                "expected": {"font_size_pt": 12},
                "actual": {"font_size_pt": 10.5},
            }
        ],
    }
    passing = {"passed": True, "coverage": 1.0, "total": 6, "matched": 6, "missed": []}

    def fake_cov(doc, template_config, llm_overrides=None):
        calls["n"] += 1
        return passing if calls["n"] >= 2 else failing

    monkeypatch.setattr("app.agents.nodes.validator.compute_coverage", fake_cov)

    final = graph_mod.run_agent(
        {
            "task_id": tid,
            "user_prompt": "帮我排版",
            "working_file_path": test_docx_path,
            "input_file_path": "in/a.docx",
        }
    )
    assert calls["n"] == 2  # 首轮未达标 + 增量修补后达标
    assert final["status"] == "done"
    task = crud.get_task(db_session, tid)
    assert task is not None
    assert task.status == TaskStatus.SUCCESS
    assert task.retry_count == 1  # bug 4：retry_count 已落库


def test_worker_skips_terminal_task(graph_env) -> None:
    """cancel 竞态（bug 2）：任务在队列期间已被取消 → worker 跳过，不再
    mark_started 覆盖 CANCELLED 终态。"""
    _, db_session, _ = graph_env
    tid = str(uuid.uuid4())
    _make_task(db_session, tid)
    crud.mark_cancelled(db_session, tid)

    from app.tasks import process_document_task

    result = process_document_task(tid)
    assert result == {}  # 未进入任何处理
    task = crud.get_task(db_session, tid)
    assert task.status == TaskStatus.CANCELLED
    assert task.started_at is None  # mark_started 未被调用


def test_success_node_keeps_cancelled_state(graph_env, test_docx_path, monkeypatch) -> None:
    """success_node 取消终态守卫（bug 3）：执行完成瞬间用户取消 → 不覆盖
    CANCELLED、不扣积分，仅保留输出路径。"""
    _, db_session, tmp_path = graph_env
    tid = str(uuid.uuid4())
    _make_task(db_session, tid)
    crud.mark_cancelled(db_session, tid)
    _degrade_storage(monkeypatch)

    out = tmp_path / "modified_a.docx"
    out.write_bytes(Path(test_docx_path).read_bytes())

    from app.agents.nodes.success import success_node

    res = success_node(
        {
            "task_id": tid,
            "output_file_path": str(out),
            "working_file_path": test_docx_path,
            "started_at_ts": 1000.0,
            "llm_total_tokens": 0,
            "agent_logs": [],
        }
    )
    assert res["status"] == "done"
    task = crud.get_task(db_session, tid)
    assert task.status == TaskStatus.CANCELLED  # 终态未被覆盖
    assert task.output_file_path == str(out)  # 输出路径仍被保留


def test_validator_fallback_short_circuits(graph_env) -> None:
    """entry_guard fallback 语义闭环（bug 5）：validator 感知 fallback →
    不再套模板覆盖率判定，直接直通成功（避免增量修补把模板格式又套回去）。"""
    from app.agents.nodes.validator import validator_node

    state = {
        "task_id": "",
        "entry_guard_fallback": True,
        "output_file_path": "",
        "retry_count": 0,
    }
    updates = validator_node(state)
    assert updates["status"] == "done"
    assert updates["validation_report"]["passed"] is True
    assert updates["validation_report"]["coverage"] == 1.0


def test_planner_fallback_guard(graph_env) -> None:
    """planner 感知 fallback（bug 5 防御）：即使异常回跳也不重新规划。"""
    from app.agents.nodes.planner import planner_node

    updates = planner_node({"task_id": "", "entry_guard_fallback": True})
    assert updates["status"] == "planning"
    assert updates["task_queue"] == []


def test_build_graph_compiled_cache(graph_env) -> None:
    """build_graph 编译缓存（bug 13）：重复调用复用同一编译实例。"""
    graph_mod, _, _ = graph_env
    g1 = graph_mod.build_graph()
    g2 = graph_mod.build_graph()
    assert g1 is g2  # 不再每次 invoke 重新编译
    graph_mod.clear_graph_cache()
    g3 = graph_mod.build_graph()
    assert g3 is not g1  # 清缓存后可重新编译（测试替换节点场景）


def test_validator_read_failure_routes_to_error(graph_env) -> None:
    """防死循环（v6.2 回归）：validator 读取失败（status=failed）→ 路由 error_node，
    不再按 passed/retry_count 回跳 planner（否则修补→再失败→无限循环）。"""
    from app.agents.nodes.validator import route_after_validator

    assert route_after_validator({"status": "failed"}) == "error_node"
    # 正常重试语义不受影响
    assert (
        route_after_validator(
            {"status": "planning", "validation_report": {"passed": False}, "retry_count": 1}
        )
        == "planner"
    )
    assert (
        route_after_validator(
            {"status": "planning", "validation_report": {"passed": False}, "retry_count": 3}
        )
        == "error_node"
    )
