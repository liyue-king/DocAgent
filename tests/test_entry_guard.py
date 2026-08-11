"""entry_guard 兜底策略测试（B1：非法输出保留原格式，不再硬编码全改）。"""

from __future__ import annotations

from app.agents.graph import route_after_supervisor
from app.agents.nodes.entry_guard import (
    entry_guard_node,
    route_after_guard,
    validate_queue,
)


def test_validate_queue_rejects_unknown_action() -> None:
    """白名单外的 action → 判非法。"""
    ok, errors = validate_queue([{"action": "delete_all", "para_ids": [0]}], 5)
    assert not ok
    assert any("白名单" in e for e in errors)


def test_validate_queue_rejects_bad_para_id() -> None:
    """越界 / 非整数的 para_id → 判非法。"""
    ok, errors = validate_queue([{"action": "set_font", "para_ids": [99], "font": "宋体"}], 5)
    assert not ok
    assert any("越界" in e for e in errors)
    ok, errors = validate_queue([{"action": "set_font", "para_ids": ["0"], "font": "宋体"}], 5)
    assert not ok


def test_validate_queue_accepts_legal_ops() -> None:
    """合法指令队列（各 action 必填字段齐全）→ 通过。"""
    queue = [
        {"action": "set_font", "para_ids": [0, 1], "font": "宋体"},
        {"action": "set_font_size", "para_ids": [0], "size_pt": 12},
        {"action": "set_paragraph_space", "para_ids": [1], "space_before_pt": 0, "space_after_pt": 6},
    ]
    ok, errors = validate_queue(queue, 5)
    assert ok and errors == []


def test_valid_queue_passes_through() -> None:
    """合法队列 → executing，error_message 清空。"""
    state = {
        "task_queue": [{"action": "set_font", "para_ids": [0], "font": "宋体"}],
        "doc_dom_serial": {"paragraph_count": 5},
        "task_id": "",
    }
    updates = entry_guard_node(state)
    assert updates["status"] == "executing"
    assert updates["error_message"] == ""


def test_deterministic_path_replans_once() -> None:
    """确定性路径 + 未重试 → 切换 LLM 路径回跳 planner（仅 1 次）。"""
    state = {
        "task_queue": [{"action": "bad_action", "para_ids": [0]}],
        "doc_dom_serial": {"paragraph_count": 5},
        "planner_mode": "deterministic",
        "entry_guard_replans": 0,
        "task_id": "",
    }
    updates = entry_guard_node(state)
    assert updates["status"] == "planning"
    assert updates["planner_mode"] == "llm_augmented"
    assert updates["entry_guard_replans"] == 1


def test_route_after_guard_cancelled_short_circuit() -> None:
    """U2 回归：cancelled → error_node，防止回跳 planner 死循环。"""
    assert route_after_guard({"status": "cancelled"}) == "error_node"
    assert route_after_guard({"status": "executing"}) == "executor"
    assert route_after_guard({"status": "planning"}) == "planner"


def test_route_after_supervisor_cancelled() -> None:
    """U2 回归：supervisor 检测到取消 → error_node。"""
    assert route_after_supervisor({"status": "cancelled"}) == "error_node"
    assert route_after_supervisor({"status": "failed"}) == "error_node"
    assert route_after_supervisor({"status": "retrieving"}) == "rag_searcher"


def test_llm_path_falls_back_to_empty_queue() -> None:
    """B1 核心回归：LLM 路径输出非法 → 空队列保留原格式，不再硬编码全改。"""
    state = {
        "task_queue": [{"action": "bad_action", "para_ids": [0]}],
        "doc_dom_serial": {"paragraph_count": 5},
        "planner_mode": "llm_augmented",
        "entry_guard_replans": 1,
        "task_id": "",
    }
    updates = entry_guard_node(state)
    assert updates["status"] == "executing"  # 空队列 → executor 原样保存
    assert updates["task_queue"] == []
    assert updates["entry_guard_fallback"] is True
    assert "保留原格式" in updates["error_message"]
