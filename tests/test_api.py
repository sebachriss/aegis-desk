import asyncio
import os
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = ""
os.environ["DEEPINFRA_API_KEY"] = "fake-key-for-tests"
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_KEY"] = ""
os.environ["SUPABASE_SERVICE_KEY"] = ""

from src.api.main import app
from src.auth.jwt_handler import create_access_token
from src.security.rate_limiter import reset_user

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

    def test_chat_too_long_returns_422(self):
        r = client.post("/chat", json={"query": "x" * 4001})
        assert r.status_code == 422


class TestJWT:
    def test_jwt_expired_is_rejected(self):
        expired_token = create_access_token(
            {"username": "ana.garcia", "role": "empleado", "display_name": "Ana"},
            expires_in_seconds=-1,
        )
        r = client.get("/me", headers={"Authorization": f"Bearer {expired_token}"})
        assert r.status_code == 401

    def test_jwt_bad_signature_is_rejected(self):
        token = create_access_token(
            {"username": "ana.garcia", "role": "empleado", "display_name": "Ana"}
        )
        tampered = token[:-5] + "XXXXX"
        r = client.get("/me", headers={"Authorization": f"Bearer {tampered}"})
        assert r.status_code == 401


class TestAdminEndpoints:
    def _admin_token(self):
        from src.security.rate_limiter import reset_login
        reset_login("testclient")
        r = client.post("/login", json={"username": "admin.aegis", "password": "admin123"})
        assert r.status_code == 200
        return r.json()["access_token"]

    def test_stats_requires_auth(self):
        client.cookies.clear()
        r = client.get("/stats")
        assert r.status_code == 401

    def test_hitl_pending_requires_admin(self):
        from src.security.rate_limiter import reset_login
        reset_login("testclient")
        r = client.post("/login", json={"username": "ana.garcia", "password": "ana123"})
        assert r.status_code == 200
        token = r.json()["access_token"]
        r2 = client.get("/hitl/pending", headers={"Authorization": f"Bearer {token}"})
        assert r2.status_code == 403


class TestRateLimitAPI:
    """Fase 3: 11 requests consecutivas del mismo usuario producen 429 en /chat."""

    def _empleado_token(self):
        return create_access_token(
            {"username": "ana.garcia", "role": "empleado", "display_name": "Ana"}
        )

    def test_chat_rate_limit_blocks_on_11th_request(self):
        reset_user("ana.garcia")
        token = self._empleado_token()
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="Hola!")
        with patch("src.agents.chat_agent.get_llm", return_value=mock_llm):
            for i in range(10):
                r = client.post(
                    "/chat",
                    json={"query": "hola"},
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert r.status_code == 200, r.text
            r = client.post(
                "/chat",
                json={"query": "hola"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 429
        assert "retry-after" in {k.lower() for k in r.headers.keys()}


class TestHITLEndpoints:
    """Fase 7: empleado no puede resolver pendientes."""

    def test_hitl_approve_requires_admin(self):
        token = create_access_token(
            {"username": "ana.garcia", "role": "empleado", "display_name": "Ana"}
        )
        r = client.post("/hitl/fake-thread/approve", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403


class TestCORS:
    """Fase 8: CORS rechaza origen no configurado."""

    def test_cors_preflight_rejects_unknown_origin(self):
        r = client.options(
            "/health",
            headers={
                "Origin": "https://evil.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert r.headers.get("access-control-allow-origin") is None
        assert r.status_code in (400, 403, 405)

    def test_cors_simple_request_does_not_leak_allow_origin(self):
        r = client.get("/health", headers={"Origin": "https://evil.com"})
        assert r.headers.get("access-control-allow-origin") != "https://evil.com"


class TestErrorHandling:
    """Fase 8: error interno no muestra stack trace ni datos de config."""

    def test_internal_error_does_not_leak_config_or_traceback(self):
        token = create_access_token(
            {"username": "admin.aegis", "role": "admin", "display_name": "Admin"}
        )
        with patch("src.api.main._graph") as mock_graph:
            mock_graph.invoke.side_effect = RuntimeError("DATABASE_URL=super-secret")
            r = client.post(
                "/chat",
                json={"query": "hola"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 500
        text = r.text.lower()
        assert "database_url" not in text
        assert "super-secret" not in text
        assert "traceback" not in text
        assert "error interno del servidor" in text


class TestConcurrency:
    """Fase 8: requests concurrentes no bloquean completamente la API."""

    def test_concurrent_health_requests_complete(self):
        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                tasks = [ac.get("/health") for _ in range(8)]
                results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
            return results

        results = asyncio.run(_run())
        assert all(r.status_code == 200 for r in results)
