from fastapi.testclient import TestClient

from tests.conftest import register

API = "/api/v1"


def test_health(client: TestClient) -> None:
    res = client.get(f"{API}/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
    assert res.headers["X-Request-ID"]


def test_register_logs_in_and_returns_profile(client: TestClient) -> None:
    user = register(client, email="Jiyoon@Example.com")
    assert user["email"] == "jiyoon@example.com"
    assert user["job_type"] == "design"
    assert user["issuer_name"] == "김지윤"
    assert "password_hash" not in user

    cookie = client.cookies.get("fh_session")
    assert cookie

    me = client.get(f"{API}/users/me")
    assert me.status_code == 200
    assert me.json()["id"] == user["id"]


def test_session_cookie_flags(client: TestClient) -> None:
    res = client.post(
        f"{API}/auth/register",
        json={
            "name": "A",
            "email": "a@example.com",
            "password": "password123",
            "job_type": "dev",
            "agree_terms": True,
        },
    )
    set_cookie = res.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "max-age" not in set_cookie  # 로그인 유지 미선택 → 세션 쿠키


def test_register_rejects_duplicate_email_case_insensitive(client: TestClient) -> None:
    register(client, email="dup@example.com")
    res = client.post(
        f"{API}/auth/register",
        json={
            "name": "B",
            "email": "DUP@example.com",
            "password": "password123",
            "job_type": "dev",
            "agree_terms": True,
        },
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "email_taken"


def test_register_requires_terms_and_valid_input(client: TestClient) -> None:
    res = client.post(
        f"{API}/auth/register",
        json={
            "name": "A",
            "email": "a@example.com",
            "password": "password123",
            "job_type": "dev",
            "agree_terms": False,
        },
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "terms_not_agreed"

    res = client.post(
        f"{API}/auth/register",
        json={
            "name": "A",
            "email": "not-an-email",
            "password": "short",
            "job_type": "chef",
            "agree_terms": True,
        },
    )
    assert res.status_code == 422
    body = res.json()["error"]
    assert body["code"] == "validation_error"
    assert {tuple(d["loc"])[-1] for d in body["details"]} == {"email", "password", "job_type"}


def test_login_logout_flow(client: TestClient) -> None:
    register(client)
    client.cookies.clear()

    assert client.get(f"{API}/users/me").status_code == 401

    res = client.post(
        f"{API}/auth/login", json={"email": "jiyoon@example.com", "password": "password123", "remember": True}
    )
    assert res.status_code == 200
    assert "max-age" in res.headers["set-cookie"].lower()
    old_token = client.cookies.get("fh_session")
    assert client.get(f"{API}/users/me").status_code == 200

    assert client.post(f"{API}/auth/logout").status_code == 204
    # 로그아웃한 토큰은 서버에서 무효
    client.cookies.set("fh_session", old_token)
    assert client.get(f"{API}/users/me").status_code == 401


def test_login_wrong_password_and_unknown_email_look_the_same(client: TestClient) -> None:
    register(client)
    client.cookies.clear()
    wrong = client.post(f"{API}/auth/login", json={"email": "jiyoon@example.com", "password": "nope-nope"})
    unknown = client.post(f"{API}/auth/login", json={"email": "ghost@example.com", "password": "nope-nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_login_rate_limited_after_repeated_failures(client: TestClient) -> None:
    register(client)
    client.cookies.clear()
    for _ in range(5):
        res = client.post(f"{API}/auth/login", json={"email": "jiyoon@example.com", "password": "wrong-pass"})
        assert res.status_code == 401
    res = client.post(f"{API}/auth/login", json={"email": "jiyoon@example.com", "password": "password123"})
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "too_many_attempts"


def test_update_me(client: TestClient) -> None:
    register(client)
    res = client.patch(
        f"{API}/users/me",
        json={
            "issuer_display_name": "지윤 디자인 스튜디오",
            "bank_name": "가상 은행",
            "default_llm_mode": "local",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["issuer_display_name"] == "지윤 디자인 스튜디오"
    assert body["default_llm_mode"] == "local"

    # 이메일은 바꿀 수 없고, 필수 값은 비울 수 없다
    assert client.patch(f"{API}/users/me", json={"email": "x@example.com"}).status_code == 422
    res = client.patch(f"{API}/users/me", json={"name": None})
    assert res.status_code == 422
    assert res.json()["error"]["details"] == {"fields": ["name"]}


def test_csrf_rejects_foreign_origin(client: TestClient) -> None:
    register(client)
    res = client.post(f"{API}/auth/logout", headers={"Origin": "https://evil.example"})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "csrf_rejected"

    res = client.patch(
        f"{API}/users/me", json={"name": "B"}, headers={"Referer": "https://evil.example/page"}
    )
    assert res.status_code == 403

    res = client.patch(f"{API}/users/me", json={"name": "B"}, headers={"Origin": "http://localhost:5173"})
    assert res.status_code == 200


def test_unknown_route_uses_error_format(client: TestClient) -> None:
    res = client.get(f"{API}/nope")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


def test_csrf_allows_same_origin_on_any_host(client: TestClient) -> None:
    # LAN IP로 접속하면 Origin과 Host가 같은 주소다 (허용 목록에 없어도 같은 출처면 통과)
    register(client)
    lan = {"Origin": "http://192.168.0.150:5173", "Host": "192.168.0.150:5173"}
    assert client.patch(f"{API}/users/me", json={"name": "B"}, headers=lan).status_code == 200

    # Host만 맞춘 다른 사이트의 요청은 거절
    spoofed = {"Origin": "http://192.168.0.99:5173", "Host": "192.168.0.150:5173"}
    assert client.patch(f"{API}/users/me", json={"name": "C"}, headers=spoofed).status_code == 403


def test_change_password_and_login_with_new_one(client: TestClient) -> None:
    register(client)
    res = client.patch(
        f"{API}/users/me/password", json={"current_password": "password123", "new_password": "new-pass-456"}
    )
    assert res.status_code == 204

    client.cookies.clear()
    assert (
        client.post(f"{API}/auth/login", json={"email": "jiyoon@example.com", "password": "new-pass-456"}).status_code
        == 200
    )
    client.cookies.clear()
    assert (
        client.post(f"{API}/auth/login", json={"email": "jiyoon@example.com", "password": "password123"}).status_code
        == 401
    )


def test_change_password_rejects_wrong_current_and_same_password(client: TestClient) -> None:
    register(client)
    res = client.patch(
        f"{API}/users/me/password", json={"current_password": "wrong-pass", "new_password": "new-pass-456"}
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "wrong_password"

    res = client.patch(
        f"{API}/users/me/password", json={"current_password": "password123", "new_password": "password123"}
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "same_password"

    res = client.patch(f"{API}/users/me/password", json={"current_password": "password123", "new_password": "짧음"})
    assert res.status_code == 422


def test_change_password_revokes_other_sessions(client: TestClient) -> None:
    register(client)
    first_session = client.cookies.get("fh_session")

    client.cookies.clear()
    res = client.post(f"{API}/auth/login", json={"email": "jiyoon@example.com", "password": "password123"})
    assert res.status_code == 200
    second_session = client.cookies.get("fh_session")

    client.cookies.set("fh_session", second_session)
    res = client.patch(
        f"{API}/users/me/password", json={"current_password": "password123", "new_password": "new-pass-456"}
    )
    assert res.status_code == 204

    # 변경에 쓴 세션은 유지되고, 다른 세션은 무효가 된다
    client.cookies.set("fh_session", second_session)
    assert client.get(f"{API}/users/me").status_code == 200
    client.cookies.set("fh_session", first_session)
    assert client.get(f"{API}/users/me").status_code == 401
