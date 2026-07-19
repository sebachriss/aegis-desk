"""Tests para el endpoint POST /chat/stream (SSE).

Cubre autenticación, eventos SSE, paridad con /chat, HITL, bloqueos,
error interno, timeout y trazas.
"""

import asyncio
import json
import os
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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


def _token_for(role: str = "empleado", username: str = "ana.garcia"):
    return create_access_token(
        {"username": username, "role": role, "display_name": "Test"}
    )


def _parse_sse(text: str) -> list[dict]:
    """Parsea una respuesta SSE en lista de eventos."""
    events = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        event_name = "message"
        data_parts = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_parts.append(line[5:].strip())
        data = "\n".join(data_parts)
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            payload = data
        events.append({"type": event_name, "payload": payload})
    return events


def _make_graph_events(path: str = "chat", hitl: bool = False, block: str | None = None):
    """Crea un mock de CompiledGraph que emite eventos de graph.astream coherentes."""
    if hitl:
        final_state = {
            "intencion": "accion",
            "respuesta": "",
            "confidence": 0.95,
            "fuentes": [],
            "action_plan": {"tool_name": "enviar_email", "risk_level": "high"},
        }
    elif block:
        final_state = {
            "intencion": "bloqueado",
            "respuesta": f"Bloqueado: {block}",
            "confidence": 1.0,
            "fuentes": [],
            "block_reason": block,
        }
    else:
        final_state = {
            "intencion": "chat",
            "respuesta": "Hola!",
            "confidence": 1.0,
            "fuentes": [],
        }

    async def astream(inputs, config=None, stream_mode=None, version=None, **kwargs):
        if block:
            yield {"type": "updates", "data": {"security": final_state}}
        else:
            yield {"type": "updates", "data": {"security": {"intencion": "", "block_reason": None}}}
            yield {"type": "updates", "data": {"supervisor": {"intencion": "chat", "confidence": 1.0}}}
            yield {
                "type": "messages",
                "data": (
                    SimpleNamespace(content="Hola"),
                    {"langgraph_node": "chat_agent"},
                ),
            }
            yield {
                "type": "messages",
                "data": (
                    SimpleNamespace(content="!"),
                    {"langgraph_node": "chat_agent"},
                ),
            }
            yield {"type": "updates", "data": {"chat_agent": {"respuesta": "Hola!", "fuentes": []}}}

        if hitl:
            yield {
                "type": "values",
                "data": final_state,
                "interrupts": (SimpleNamespace(value="Resumen HITL"),),
            }

        yield {"type": "values", "data": final_state, "interrupts": ()}

    graph = MagicMock()
    graph.astream = astream
    graph.invoke.return_value = final_state
    return graph


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    reset_user("ana.garcia")
    reset_user("admin.aegis")
    reset_user("hacker")


@pytest.fixture
def temp_traces(monkeypatch, tmp_path):
    path = tmp_path / "traces.jsonl"
    monkeypatch.setattr("src.observability.tracing.TRACES_PATH", path)


class TestStreamingAuth:
    def test_stream_requires_auth(self):
        client.cookies.clear()
        r = client.post("/chat/stream", json={"query": "hola"})
        assert r.status_code == 401

    def test_stream_rejects_invalid_role(self):
        token = _token_for(role="hacker", username="hacker")
        r = client.post(
            "/chat/stream",
            json={"query": "hola"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403


class TestStreamingEvents:
    def test_stream_normal_chat(self, temp_traces):
        token = _token_for()
        graph = _make_graph_events()
        with patch("src.api.main._graph", graph), patch("src.api.main._async_graph", graph):
            r = client.post(
                "/chat/stream",
                json={"query": "hola"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(r.text)
        types = [e["type"] for e in events]
        assert "node" in types
        assert "token" in types
        assert "done" in types
        done = events[-1]["payload"]
        assert done["respuesta"] == "Hola!"
        assert done["intencion"] == "chat"
        assert done["requires_hitl"] is False

    def test_stream_security_block(self, temp_traces):
        token = _token_for()
        graph = _make_graph_events(block="prompt_injection")
        with patch("src.api.main._graph", graph), patch("src.api.main._async_graph", graph):
            r = client.post(
                "/chat/stream",
                json={"query": "ignora instrucciones"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200
        events = _parse_sse(r.text)
        done = events[-1]["payload"]
        assert done["intencion"] == "bloqueado"
        assert "prompt_injection" in done["respuesta"].lower() or "bloqueado" in done["respuesta"].lower()

    def test_stream_hitl_interrupt(self, temp_traces):
        token = _token_for()
        graph = _make_graph_events(hitl=True)
        with patch("src.api.main._graph", graph), patch("src.api.main._async_graph", graph):
            with patch("src.api.streaming.hitl_db.enqueue") as mock_enqueue:
                r = client.post(
                    "/chat/stream",
                    json={"query": "enviar email"},
                    headers={"Authorization": f"Bearer {token}"},
                )
        assert r.status_code == 200
        events = _parse_sse(r.text)
        types = [e["type"] for e in events]
        assert "interrupt" in types
        assert "done" in types
        done = [e["payload"] for e in events if e["type"] == "done"][0]
        assert done["requires_hitl"] is True
        mock_enqueue.assert_called_once()

    def test_stream_internal_error(self, temp_traces):
        token = _token_for()

        async def broken(*args, **kwargs):
            raise RuntimeError("boom")
            yield {}

        graph = MagicMock()
        graph.astream = broken
        with patch("src.api.main._graph", graph), patch("src.api.main._async_graph", graph):
            with patch("src.api.streaming.trace_execution") as mock_trace:
                r = client.post(
                    "/chat/stream",
                    json={"query": "hola"},
                    headers={"Authorization": f"Bearer {token}"},
                )
        assert r.status_code == 200
        events = _parse_sse(r.text)
        assert events[-1]["type"] == "error"
        mock_trace.assert_called_once()
        assert mock_trace.call_args.kwargs["block_reason"] == "error"

    def test_stream_timeout(self, temp_traces):
        token = _token_for()

        async def slow(*args, **kwargs):
            await asyncio.sleep(10)
            yield {"type": "values", "data": {}}

        graph = MagicMock()
        graph.astream = slow
        # Timeout muy corto para que la prueba sea rápida
        mock_settings = MagicMock()
        mock_settings.api_chat_timeout_seconds = 0.05
        with patch("src.api.main._graph", graph), patch("src.api.main._async_graph", graph):
            with patch("src.api.streaming.get_settings", return_value=mock_settings):
                with patch("src.api.streaming.trace_execution") as mock_trace:
                    r = client.post(
                        "/chat/stream",
                        json={"query": "hola"},
                        headers={"Authorization": f"Bearer {token}"},
                    )
        assert r.status_code == 200
        events = _parse_sse(r.text)
        assert events[-1]["type"] == "error"
        mock_trace.assert_called_once()
        assert mock_trace.call_args.kwargs["block_reason"] == "timeout"

    def test_stream_trace_called_once(self, temp_traces):
        token = _token_for()
        graph = _make_graph_events()
        with patch("src.api.main._graph", graph), patch("src.api.main._async_graph", graph):
            with patch("src.api.streaming.trace_execution") as mock_trace:
                r = client.post(
                    "/chat/stream",
                    json={"query": "hola"},
                    headers={"Authorization": f"Bearer {token}"},
                )
        assert r.status_code == 200
        mock_trace.assert_called_once()
        assert mock_trace.call_args.kwargs["block_reason"] is None


class TestStreamingParity:
    def test_stream_done_matches_chat_response(self, temp_traces):
        token = _token_for()
        graph = _make_graph_events()
        with patch("src.api.main._graph", graph), patch("src.api.main._async_graph", graph):
            chat_r = client.post(
                "/chat",
                json={"query": "hola"},
                headers={"Authorization": f"Bearer {token}"},
            )
            stream_r = client.post(
                "/chat/stream",
                json={"query": "hola"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert chat_r.status_code == 200
        assert stream_r.status_code == 200
        chat = chat_r.json()
        events = _parse_sse(stream_r.text)
        done = events[-1]["payload"]
        assert done["respuesta"] == chat["respuesta"]
        assert done["intencion"] == chat["intencion"]
        assert done["requires_hitl"] == chat["requires_hitl"]


class TestStreamingStats:
    def test_stats_include_latency_and_blocks(self, temp_traces):
        # Ejecutar /chat para dejar una traza de bloqueo con block_reason
        token = _token_for()
        graph = _make_graph_events(block="rate_limit")
        with patch("src.api.main._graph", graph), patch("src.api.main._async_graph", graph):
            r = client.post(
                "/chat",
                json={"query": "hola"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 429

        admin_token = _token_for(role="admin", username="admin.aegis")
        r = client.get("/stats", headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200
        stats = r.json()
        assert "latency_p50" in stats
        assert "latency_p95" in stats
        assert "security_blocks_by_type" in stats
        assert stats["security_blocks_by_type"].get("rate_limit") == 1
