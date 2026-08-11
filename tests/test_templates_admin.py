"""模板管理后台测试（U6）：管理员权限 + 向量化降级回滚 + 系统模板保护。"""

from __future__ import annotations

from app.config import settings
from app.crud import templates as tpl_crud


def _register_admin(client, db_session, monkeypatch, email: str = "admin@example.com") -> str:
    """注册管理员邮箱并登录，返回 token（monkeypatch admin_emails 配置）。"""
    import app.api.auth as auth_mod

    auth_mod.email_code.verify_code = lambda _e, _c: True
    monkeypatch.setattr(settings, "admin_emails", email)
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "pass123456", "code": "123456"},
    )
    assert r.json()["code"] == 0
    login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "pass123456"}
    )
    return login.json()["token"]


def _register_plain(client, email: str = "user@example.com") -> str:
    import app.api.auth as auth_mod

    auth_mod.email_code.verify_code = lambda _e, _c: True
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "pass123456", "code": "123456"},
    )
    return r.json()["token"]


def test_create_template_requires_admin(client, db_session) -> None:
    """普通用户调用 POST /templates → 403（1108）。"""
    token = _register_plain(client)
    resp = client.post(
        "/api/v1/templates",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "测试模板", "description": "用于测试的模板", "config": {}},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 1108


def test_create_template_vector_fail_rolls_back(client, db_session, monkeypatch) -> None:
    """向量库不可用 → 1401，且 MySQL 无残留行（回滚生效，显式 mock 向量化失败）。"""
    from app.api import templates as tpl_api
    from app.services.knowledge import KnowledgeUnavailable

    def _boom(*_a, **_k) -> None:
        raise KnowledgeUnavailable("mock chroma down")

    monkeypatch.setattr(tpl_api.template_seed, "upsert_vector", _boom)
    token = _register_admin(client, db_session, monkeypatch)
    before = len(tpl_crud.list_templates(db_session))
    resp = client.post(
        "/api/v1/templates",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "回滚模板", "description": "向量库挂掉时的模板", "config": {}},
    )
    assert resp.json()["code"] == 1401
    assert "向量库" in resp.json()["msg"]
    # 回滚：模板表行数不变，且无该名称的残留
    assert len(tpl_crud.list_templates(db_session)) == before
    assert tpl_crud.get_by_name(db_session, "回滚模板") is None


def test_update_template_not_found_2001(client, db_session, monkeypatch) -> None:
    """编辑不存在的模板 → 2001。"""
    token = _register_admin(client, db_session, monkeypatch)
    resp = client.put(
        "/api/v1/templates/9999",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "不存在", "description": "无此模板", "config": {}},
    )
    assert resp.json()["code"] == 2001


def test_delete_system_template_rejected(client, db_session, monkeypatch) -> None:
    """系统内置模板不可删除 → 1001。"""
    token = _register_admin(client, db_session, monkeypatch)
    tpl = tpl_crud.create_template(
        db_session,
        name="内置模板",
        description="系统内置",
        config={},
        vector_id="tmpl_099",
        is_system=True,
    )
    resp = client.delete(
        f"/api/v1/templates/{tpl.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.json()["code"] == 1001
    assert "内置" in resp.json()["msg"]
    assert tpl_crud.get_template(db_session, tpl.id) is not None


def test_delete_template_not_found_2001(client, db_session, monkeypatch) -> None:
    """删除不存在的模板 → 2001。"""
    token = _register_admin(client, db_session, monkeypatch)
    resp = client.delete(
        "/api/v1/templates/9999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.json()["code"] == 2001
