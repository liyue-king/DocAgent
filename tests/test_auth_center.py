"""个人中心相关测试：积分流水记账 + 改密/改邮箱 token 版本号失效（U4）。"""

from __future__ import annotations

from app.crud import users as user_crud


def _auth_headers(token: str) -> dict:
    """带 Bearer 前缀的请求头。"""
    return {"Authorization": f"Bearer {token}"}


def _register(client, email: str, password: str = "pass123456") -> dict:
    """注册并返回响应 JSON（测试环境 monkeypatch 验证码校验通过）。"""
    import app.api.auth as auth_mod

    auth_mod.email_code.verify_code = lambda _e, _c: True
    return client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "code": "123456"},
    ).json()


def test_register_writes_register_credit_log(client, db_session) -> None:
    """注册成功 → 初始 10 积分 + register 流水可见。"""
    _register(client, "alice@example.com")
    user = user_crud.get_by_email(db_session, "alice@example.com")
    assert user is not None and user.credits_balance == 10
    logs = user_crud.list_credit_logs(db_session, user.id)
    assert len(logs) == 1
    assert logs[0].amount == 10 and logs[0].balance_after == 10
    assert logs[0].action == "register"


def test_me_returns_credit_logs(client) -> None:
    """/me 返回最近积分明细（注册赠送流水可见）。"""
    r = _register(client, "bob@example.com")
    token = r["token"]
    resp = client.get("/api/v1/auth/me", headers=_auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["user"]["credits_balance"] == 10
    assert len(body["credit_logs"]) >= 1
    assert body["credit_logs"][0]["action"] == "register"


def test_deduct_credit_writes_task_consume_log(client, db_session) -> None:
    """任务消费扣分 → 负数流水 + 余额快照正确。"""
    _register(client, "carol@example.com")
    user = user_crud.get_by_email(db_session, "carol@example.com")
    assert user is not None
    assert user_crud.deduct_credit(db_session, user.id, 1) is True
    db_session.refresh(user)
    assert user.credits_balance == 9
    logs = user_crud.list_credit_logs(db_session, user.id)
    assert len(logs) == 2
    consume = logs[0]  # 最新在前
    assert consume.amount == -1 and consume.balance_after == 9
    assert consume.action == "task_consume"


def test_change_password_invalidates_old_token(client) -> None:
    """改密成功 → 旧 token 立即失效（tv 不匹配），新 token 可用。"""
    r = _register(client, "dave@example.com")
    token = r["token"]

    # 旧 token 改密前可用
    assert client.get("/api/v1/auth/me", headers=_auth_headers(token)).status_code == 200

    resp = client.post(
        "/api/v1/auth/change-password",
        headers=_auth_headers(token),
        json={"old_password": "pass123456", "new_password": "newpass888"},
    )
    assert resp.status_code == 200 and resp.json()["code"] == 0
    new_token = resp.json()["token"]

    # 旧 token 失效（401 + 1105），新 token 可用
    old = client.get("/api/v1/auth/me", headers=_auth_headers(token))
    assert old.status_code == 401 and old.json()["code"] == 1105
    fresh = client.get("/api/v1/auth/me", headers=_auth_headers(new_token))
    assert fresh.status_code == 200 and fresh.json()["code"] == 0


def test_change_password_wrong_old_rejected(client) -> None:
    """旧密码错误 → 1104，token 仍有效。"""
    r = _register(client, "erin@example.com")
    token = r["token"]
    resp = client.post(
        "/api/v1/auth/change-password",
        headers=_auth_headers(token),
        json={"old_password": "wrong-pass", "new_password": "newpass888"},
    )
    assert resp.json()["code"] == 1104
    # 未改动 → 旧 token 依旧有效
    assert client.get("/api/v1/auth/me", headers=_auth_headers(token)).status_code == 200


def test_change_email_updates_and_invalidates_old_token(client, monkeypatch) -> None:
    """改邮箱成功 → 邮箱更新、旧 token 失效、新 token 可用。"""
    import app.api.auth as auth_mod

    monkeypatch.setattr(auth_mod.email_code, "verify_code", lambda _e, _c: True)
    r = _register(client, "frank@example.com")
    token = r["token"]

    resp = client.post(
        "/api/v1/auth/change-email",
        headers=_auth_headers(token),
        json={"email": "frank-new@example.com", "code": "123456"},
    )
    assert resp.status_code == 200 and resp.json()["code"] == 0
    assert resp.json()["user"]["email"] == "frank-new@example.com"
    new_token = resp.json()["token"]

    old = client.get("/api/v1/auth/me", headers=_auth_headers(token))
    assert old.status_code == 401 and old.json()["code"] == 1105
    fresh = client.get("/api/v1/auth/me", headers=_auth_headers(new_token))
    assert fresh.status_code == 200
    assert fresh.json()["user"]["email"] == "frank-new@example.com"


def test_reset_password_success(client, monkeypatch) -> None:
    """重置密码成功 → 新密码可登录，旧 token 失效。"""
    import app.api.auth as auth_mod

    monkeypatch.setattr(auth_mod.email_code, "verify_code", lambda _e, _c: True)
    r = _register(client, "helen@example.com")
    old_token = r["token"]

    resp = client.post(
        "/api/v1/auth/reset",
        json={"email": "helen@example.com", "code": "123456", "password": "brandnew99"},
    )
    assert resp.status_code == 200 and resp.json()["code"] == 0

    # 旧 token 失效
    old = client.get("/api/v1/auth/me", headers=_auth_headers(old_token))
    assert old.status_code == 401 and old.json()["code"] == 1105
    # 新密码可登录
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "helen@example.com", "password": "brandnew99"},
    )
    assert login.json()["code"] == 0
    # 旧密码不可登录
    bad = client.post(
        "/api/v1/auth/login",
        json={"email": "helen@example.com", "password": "pass123456"},
    )
    assert bad.json()["code"] == 1104


def test_reset_password_unknown_email_1104(client, monkeypatch) -> None:
    """未注册邮箱 → 1104。"""
    import app.api.auth as auth_mod

    monkeypatch.setattr(auth_mod.email_code, "verify_code", lambda _e, _c: True)
    resp = client.post(
        "/api/v1/auth/reset",
        json={"email": "ghost@example.com", "code": "123456", "password": "brandnew99"},
    )
    assert resp.json()["code"] == 1104


def test_reset_password_bad_code_1101(client, monkeypatch) -> None:
    """验证码错误 → 1101（不改动密码）。"""
    import app.api.auth as auth_mod

    _register(client, "iris@example.com")
    # 先注册（验证码通过），再模拟验证码校验失败
    monkeypatch.setattr(auth_mod.email_code, "verify_code", lambda _e, _c: False)
    resp = client.post(
        "/api/v1/auth/reset",
        json={"email": "iris@example.com", "code": "000000", "password": "brandnew99"},
    )
    assert resp.json()["code"] == 1101
    # 旧密码仍可登录（未被覆盖）
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "iris@example.com", "password": "pass123456"},
    )
    assert login.json()["code"] == 0


def test_change_email_conflict_1103(client, monkeypatch) -> None:
    """新邮箱已被他人注册 → 1103。"""
    import app.api.auth as auth_mod

    monkeypatch.setattr(auth_mod.email_code, "verify_code", lambda _e, _c: True)
    _register(client, "gina@example.com")
    r2 = _register(client, "gina2@example.com")
    token = r2["token"]
    resp = client.post(
        "/api/v1/auth/change-email",
        headers=_auth_headers(token),
        json={"email": "gina@example.com", "code": "123456"},
    )
    assert resp.json()["code"] == 1103


def test_login_token_after_change_password_valid(client) -> None:
    """改密后再登录签发的 token 必须携带最新 tv（否则被误判失效）。"""
    r = _register(client, "jane@example.com")
    token = r["token"]
    resp = client.post(
        "/api/v1/auth/change-password",
        headers=_auth_headers(token),
        json={"old_password": "pass123456", "new_password": "newpass888"},
    )
    assert resp.json()["code"] == 0
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "jane@example.com", "password": "newpass888"},
    )
    assert login.json()["code"] == 0
    login_token = login.json()["token"]
    fresh = client.get("/api/v1/auth/me", headers=_auth_headers(login_token))
    assert fresh.status_code == 200 and fresh.json()["code"] == 0


def test_login_token_after_reset_valid(client, monkeypatch) -> None:
    """重置密码后再登录签发的 token 必须携带最新 tv（否则被误判失效）。"""
    import app.api.auth as auth_mod

    monkeypatch.setattr(auth_mod.email_code, "verify_code", lambda _e, _c: True)
    _register(client, "kate@example.com")
    resp = client.post(
        "/api/v1/auth/reset",
        json={"email": "kate@example.com", "code": "123456", "password": "brandnew99"},
    )
    assert resp.json()["code"] == 0
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "kate@example.com", "password": "brandnew99"},
    )
    assert login.json()["code"] == 0
    login_token = login.json()["token"]
    fresh = client.get("/api/v1/auth/me", headers=_auth_headers(login_token))
    assert fresh.status_code == 200 and fresh.json()["code"] == 0
