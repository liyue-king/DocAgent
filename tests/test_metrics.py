"""Prometheus 指标测试（O2）：/metrics 输出聚合指标。"""

from __future__ import annotations

import uuid

from app.crud import tasks as crud


def _make_task(db_session, status: str, processing_ms: int | None, tokens: int = 0) -> str:
    tid = str(uuid.uuid4())
    crud.create_task(
        db_session,
        task_id=tid,
        prompt_text="x",
        input_file_name="a.docx",
        input_file_hash="h",
        input_file_path="k",
        user_id=1,
    )
    task = crud.get_task(db_session, tid)
    task.status = status
    task.processing_time_ms = processing_ms
    task.llm_total_tokens = tokens
    db_session.commit()
    return tid


def test_metrics_endpoint_content(client, db_session) -> None:
    """/metrics 返回任务计数 + 时长直方图 + LLM token 汇总。"""
    _make_task(db_session, "success", 2500, tokens=120)
    _make_task(db_session, "success", 400, tokens=80)
    _make_task(db_session, "failed", 3000, tokens=30)

    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    text = resp.text

    # 任务计数（按状态）
    assert 'docagent_tasks_total{status="success"} 2' in text
    assert 'docagent_tasks_total{status="failed"} 1' in text
    # 时长直方图（累计桶）：400ms 命中 le=0.5；2.5s/3s 命中 le=5；全部命中 +Inf
    assert 'docagent_task_duration_seconds_bucket{le="0.5"} 1' in text
    assert 'docagent_task_duration_seconds_bucket{le="2"} 1' in text
    assert 'docagent_task_duration_seconds_bucket{le="5"} 3' in text
    assert 'docagent_task_duration_seconds_bucket{le="+Inf"} 3' in text
    assert "docagent_task_duration_seconds_sum" in text
    assert "docagent_task_duration_seconds_count 3" in text
    # LLM token 汇总
    assert "docagent_llm_tokens_total 230" in text
    # 队列积压（Redis 不可用 → 0）
    assert "docagent_queue_pending 0" in text
