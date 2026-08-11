"""API 错误码测试（TestClient + SQLite 依赖覆盖，无外部服务）。"""

from __future__ import annotations

import uuid

from app.crud import tasks as crud


def test_process_missing_prompt_1001(client, docx_bytes) -> None:
    r = client.post(
        "/api/v1/process",
        files={"file": ("x.docx", docx_bytes, "application/octet-stream")},
        data={"prompt": "   "},
    )
    assert r.json()["code"] == 1001


def test_process_non_docx_1003(client) -> None:
    r = client.post(
        "/api/v1/process",
        files={"file": ("x.txt", b"hi", "text/plain")},
        data={"prompt": "排版"},
    )
    assert r.json()["code"] == 1003


def test_process_minio_down_4001(client, docx_bytes, monkeypatch) -> None:
    """MinIO 存储不可用 → 4001，且不产生任务记录（显式 mock 上传失败）。"""
    from app.api import routes as routes_mod
    from app.services.storage import StorageUnavailable

    def _boom(*_a, **_k) -> None:
        raise StorageUnavailable("mock minio down")

    monkeypatch.setattr(routes_mod.storage, "upload_bytes", _boom)
    r = client.post(
        "/api/v1/process",
        files={"file": ("x.docx", docx_bytes, "application/octet-stream")},
        data={"prompt": "帮我排版成学术论文格式"},
    )
    assert r.json()["code"] == 4001


def test_task_not_found_2001(client) -> None:
    r = client.get("/api/v1/task/not-exist-id")
    assert r.json()["code"] == 2001


def test_download_not_found_2001(client) -> None:
    r = client.get("/api/v1/download/not-exist-id")
    assert r.json()["code"] == 2001


def test_download_pending_2002(client, db_session) -> None:
    """未完成的任务下载被拒（2002）。"""
    tid = str(uuid.uuid4())
    crud.create_task(
        db_session, task_id=tid, prompt_text="x", input_file_name="a.docx",
        input_file_hash="h", input_file_path="k", user_id=1,
    )
    r = client.get(f"/api/v1/download/{tid}")
    assert r.json()["code"] == 2002


def test_get_task_pending_ok(client, db_session) -> None:
    """pending 任务轮询正常返回（Redis 不可用自动降级 MySQL）。"""
    tid = str(uuid.uuid4())
    crud.create_task(
        db_session, task_id=tid, prompt_text="x", input_file_name="a.docx",
        input_file_hash="h", input_file_path="k", user_id=1,
    )
    r = client.get(f"/api/v1/task/{tid}")
    body = r.json()
    assert body["code"] == 0
    assert body["status"] == "pending"
    assert body["progress"] == 0
    assert body["logs"] == []
    assert body["download_url"] is None


def test_stream_task_missing_2001(client) -> None:
    """SSE：任务不存在 → 立即推送 error 事件帧并关闭。"""
    with client.stream("GET", "/api/v1/task/not-exist/stream") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        content = r.read().decode("utf-8")
    assert "event: error" in content
    assert '"code": 2001' in content


def test_stream_success_task_terminal(client, db_session) -> None:
    """SSE：成功任务 → status 帧（含 download_url）后关闭，无心跳残留。"""
    from app.models import TaskStatus

    tid = str(uuid.uuid4())
    crud.create_task(
        db_session, task_id=tid, prompt_text="x", input_file_name="a.docx",
        input_file_hash="h", input_file_path="k", user_id=1,
    )
    crud.update_task(
        db_session, tid,
        status=TaskStatus.SUCCESS, progress=100,
        output_file_path="unreachable.docx",
    )
    with client.stream("GET", f"/api/v1/task/{tid}/stream") as r:
        content = r.read().decode("utf-8")
    assert "event: status" in content
    assert '"status": "success"' in content
    assert '"progress": 100' in content
    assert '"download_url"' in content  # MinIO 不可用 → 降级本地下载路径


def test_cancel_task_not_found_2001(client) -> None:
    r = client.post("/api/v1/task/not-exist-id/cancel")
    assert r.json()["code"] == 2001


def test_cancel_pending_task_ok(client, db_session) -> None:
    """pending 任务可取消 → status=cancelled（Redis 不可用降级 MySQL 判定）。"""
    from app.models import TaskStatus

    tid = str(uuid.uuid4())
    crud.create_task(
        db_session, task_id=tid, prompt_text="x", input_file_name="a.docx",
        input_file_hash="h", input_file_path="k", user_id=1,
    )
    r = client.post(f"/api/v1/task/{tid}/cancel")
    body = r.json()
    assert body["code"] == 0
    task = crud.get_task(db_session, tid)
    assert task.status == TaskStatus.CANCELLED
    # 取消后下载被拒 2002（终态但无输出路径/不允许下载）
    r2 = client.get(f"/api/v1/download/{tid}")
    assert r2.json()["code"] == 2002


def test_cancel_terminal_task_2002(client, db_session) -> None:
    """已成功/失败的任务不可取消（2002）。"""
    from app.models import TaskStatus

    tid = str(uuid.uuid4())
    crud.create_task(
        db_session, task_id=tid, prompt_text="x", input_file_name="a.docx",
        input_file_hash="h", input_file_path="k", user_id=1,
    )
    crud.update_task(db_session, tid, status=TaskStatus.SUCCESS, progress=100)
    r = client.post(f"/api/v1/task/{tid}/cancel")
    assert r.json()["code"] == 2002


def test_health_structure(client) -> None:
    """健康探测：四服务字段齐全（本环境全部不可用 → degraded）。"""
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert set(body["services"]) == {"mysql", "redis", "minio", "chroma"}
    assert body["status"] in ("ok", "degraded")
