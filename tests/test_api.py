import pytest
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)

class TestHealth:
    def test_health(self):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["service"] == "aegis-desk"

class TestAuth:
    def test_login_ok(self):
        r = client.post("/login", json={"username": "admin.aegis", "password": "admin123"})
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data
        assert data["role"] == "admin"

    def test_login_bad(self):
        r = client.post("/login", json={"username": "admin.aegis", "password": "wrong"})
        assert r.status_code == 401

    def test_login_rate_limit(self):
        from src.security.rate_limiter import reset_login
        reset_login("testclient")
        for i in range(12):
            r = client.post("/login", json={"username": "x", "password": "y"})
            assert r.status_code in (401, 429)
            if r.status_code == 429:
                break
        else:
            # after 12 attempts, next should be rate limited
            r = client.post("/login", json={"username": "x", "password": "y"})
            assert r.status_code == 429
        assert r.headers.get("retry-after") or r.headers.get("Retry-After")

    def test_me_requires_auth(self):
        client.cookies.clear()
        r = client.get("/me")
        assert r.status_code == 401

    def test_me_with_token(self):
        from src.security.rate_limiter import reset_login
        reset_login("testclient")
        r = client.post("/login", json={"username": "admin.aegis", "password": "admin123"})
        assert r.status_code == 200, r.text
        token = r.json()["access_token"]
        r2 = client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert r2.status_code == 200
        assert r2.json()["username"] == "admin.aegis"
