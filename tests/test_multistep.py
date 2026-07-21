"""Tests de contrato y regresión para el Multi-Step Action Agent y Onboarding Agent.

Describen el comportamiento esperado del plan PLAN_MULTISTEP_ONBOARDING.md.
Tras los ajustes recientes la suite pasa contra el código actual, actuando como
regresión de las funcionalidades multi-paso:

- Planner con steps, validación de max_steps y permisos por rol.
- Executor ordenado, idempotente, con substitución literal de {{prev_result}} y
  reporte de ejecutados/cancelados ante fallos.
- HITL por paso (approve/reject/expire) con cancelación solo de dependientes.
- Onboarding: routing, denegación a empleados, plan de 3 pasos y whitelist de email.
- API `/chat` y `/chat/stream` reportan `requires_hitl=True` y emiten evento `interrupt`.

Se usan mocks de LLM y tools para evitar llamadas reales a APIs.
"""

import importlib
import json
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

# Entorno determinista para tests sin depender de .env real
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("DEEPINFRA_API_KEY", "fake-key-for-tests")
os.environ.setdefault("GROQ_API_KEY", "fake-groq-for-tests")
os.environ.setdefault("SUPABASE_URL", "")
os.environ.setdefault("SUPABASE_KEY", "")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "")

from src.agents import action_agent as action_agent_module
from src.agents import graph as graph_module
from src.agents.action_agent import action_executor_node, action_planner_node
from src.agents.hitl_node import hitl_node
from src.api.main import app
from src.auth.jwt_handler import create_access_token
from src.security.rate_limiter import reset_user

client = TestClient(app)


# -----------------------------------------------------------------------------
# Helpers y factories
# -----------------------------------------------------------------------------

def _token(role: str = "empleado", username: str = "ana.garcia") -> str:
    return create_access_token(
        {"username": username, "role": role, "display_name": "Test"}
    )


def _make_step(
    tool_name: str,
    arguments: dict,
    risk_level: str = "low",
    approval_status: str | None = None,
    execution_status: str = "not_started",
    depends_on_previous: bool = False,
    reasoning: str = "",
    result: str | None = None,
    executed_at: str | None = None,
    approved_by: str | None = None,
    approved_at: str | None = None,
) -> dict:
    if approval_status is None:
        approval_status = "pending" if risk_level == "high" else "not_required"
    return {
        "tool_name": tool_name,
        "arguments": arguments,
        "reasoning": reasoning,
        "depends_on_previous": depends_on_previous,
        "risk_level": risk_level,
        "approval_status": approval_status,
        "execution_status": execution_status,
        "idempotency_key": f"key_{tool_name}_{hash(json.dumps(arguments, sort_keys=True, ensure_ascii=True))}",
        "result": result,
        "executed_at": executed_at,
        "approved_by": approved_by,
        "approved_at": approved_at,
    }


def _make_action_plan(
    steps: list[dict],
    plan_status: str = "in_progress",
    current_step: int = 0,
    top_approval: str = "approved",
    top_execution: str = "not_started",
    requested_by: str = "ana.garcia",
    role: str = "empleado",
) -> dict:
    """Construye un action_plan con el schema futuro (steps + plan_status)."""
    first = steps[0] if steps else {}
    return {
        "action_id": "act_test_multistep",
        "requested_by": requested_by,
        "role": role,
        "created_at": datetime.now().isoformat(),
        "current_step": current_step,
        "plan_status": plan_status,
        "steps": steps,
        # Campos legacy planos para retrocompatibilidad
        "tool_name": first.get("tool_name"),
        "arguments": first.get("arguments", {}),
        "risk_level": first.get("risk_level", "low"),
        "approval_status": top_approval,
        "execution_status": top_execution,
        "idempotency_key": first.get("idempotency_key", ""),
        "reasoning": first.get("reasoning", ""),
        "executed_at": None,
    }


def _action_step(
    tool_name: str,
    arguments: dict,
    reasoning: str = "",
    depends_on_previous: bool = False,
    **_kwargs,
):
    """Crea un ActionStep (el schema que espera action_planner_node)."""
    return action_agent_module.ActionStep(
        tool_name=tool_name,
        arguments=arguments,
        reasoning=reasoning,
        depends_on_previous=depends_on_previous,
    )


def _mock_llm_for_steps(steps: list) -> MagicMock:
    """Crea un mock de LLM cuyo structured output devuelve steps + top-level legacy."""
    first = steps[0] if steps else None
    plan_obj = SimpleNamespace(
        tool_name=first.tool_name if first else None,
        arguments=first.arguments if first else {},
        reasoning=first.reasoning if first else "",
        steps=steps,
    )
    structured = MagicMock()
    structured.invoke.return_value = plan_obj
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


def _mock_tool(name: str, return_value: str = "ok", side_effect=None):
    return SimpleNamespace(
        name=name,
        invoke=MagicMock(return_value=return_value, side_effect=side_effect),
    )


def _parse_sse(text: str) -> list[dict]:
    """Parsea una respuesta SSE en lista de eventos (copia de test_streaming)."""
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


def _run_executor_to_completion(state: dict) -> dict:
    """Ejecuta action_executor_node en bucle hasta que el plan termine o falle."""
    result = action_executor_node(state)
    plan = result["action_plan"]
    while plan.get("plan_status") == "in_progress" and plan.get("current_step", 0) < len(plan.get("steps", [])):
        state["action_plan"] = plan
        result = action_executor_node(state)
        new_plan = result["action_plan"]
        if new_plan.get("current_step") == plan.get("current_step") and new_plan.get("plan_status") == plan.get("plan_status"):
            # No hubo progreso: evitar loop infinito
            break
        plan = new_plan
    return result


# -----------------------------------------------------------------------------
# Planner
# -----------------------------------------------------------------------------

class TestMultiStepPlanner:
    """Contratos del action_planner_node para planes multi-paso."""

    def test_simple_request_produces_one_step_plan(self):
        steps = [_action_step("crear_ticket", {"titulo": "x", "descripcion": "y", "prioridad": "baja"})]
        llm = _mock_llm_for_steps(steps)

        with patch("src.agents.action_agent.get_llm", return_value=llm):
            result = action_planner_node(
                {"query": "crea un ticket de baja prioridad", "user_id": "ana.garcia", "role": "empleado"}
            )

        plan = result.get("action_plan")
        assert plan is not None
        assert "steps" in plan, "El plan estructurado debe exponer steps"
        assert len(plan["steps"]) == 1
        assert plan["steps"][0]["tool_name"] == "crear_ticket"
        assert plan["steps"][0]["risk_level"] == "low"
        assert plan["steps"][0]["approval_status"] == "not_required"
        assert plan.get("plan_status") == "in_progress"
        assert plan.get("current_step") == 0

    def test_compound_request_produces_two_step_plan(self):
        steps = [
            _action_step("crear_ticket", {"titulo": "x", "descripcion": "y", "prioridad": "baja"}),
            _action_step(
                "enviar_email",
                {"para": "rrhh@aegiscorp.com", "asunto": "Nuevo ticket", "cuerpo": "..."},
            ),
        ]
        llm = _mock_llm_for_steps(steps)

        with patch("src.agents.action_agent.get_llm", return_value=llm):
            result = action_planner_node(
                {
                    "query": "crea un ticket y envía un email a rrhh@aegiscorp.com",
                    "user_id": "admin.aegis",
                    "role": "admin",
                }
            )

        plan = result["action_plan"]
        assert plan is not None
        assert "steps" in plan
        assert len(plan["steps"]) == 2
        assert plan["steps"][0]["risk_level"] == "low"
        assert plan["steps"][1]["tool_name"] == "enviar_email"
        assert plan["steps"][1]["risk_level"] == "high"

    def test_plan_exceeding_max_steps_is_rejected(self):
        steps = [
            _action_step("crear_ticket", {"titulo": f"t{i}", "descripcion": "x", "prioridad": "baja"})
            for i in range(4)
        ]
        llm = _mock_llm_for_steps(steps)

        with patch("src.agents.action_agent.get_llm", return_value=llm):
            result = action_planner_node(
                {"query": "crea cuatro tickets", "user_id": "admin.aegis", "role": "admin"}
            )

        # Límite duro de 3 pasos: plan completo rechazado, sin ejecución parcial
        assert result.get("action_plan") is None or result["action_plan"].get("plan_status") == "rejected"
        assert result.get("authorization_decision") == "denied"

    def test_plan_with_invalid_or_unallowed_tool_is_rejected(self):
        steps = [
            _action_step("crear_ticket", {"titulo": "x", "descripcion": "y", "prioridad": "baja"}),
            # Empleado no puede usar enviar_email; un paso inválido invalida TODO el plan
            _action_step(
                "enviar_email",
                {"para": "rrhh@aegiscorp.com", "asunto": "x", "cuerpo": "x"},
            ),
        ]
        llm = _mock_llm_for_steps(steps)

        with patch("src.agents.action_agent.get_llm", return_value=llm):
            result = action_planner_node(
                {
                    "query": "crea un ticket y envía un email a rrhh@aegiscorp.com",
                    "user_id": "ana.garcia",
                    "role": "empleado",
                }
            )

        assert result.get("action_plan") is None or result["action_plan"].get("plan_status") == "rejected"
        assert result.get("authorization_decision") == "denied"


# -----------------------------------------------------------------------------
# Executor
# -----------------------------------------------------------------------------

class TestMultiStepExecutor:
    """Contratos del action_executor_node para ejecución paso a paso."""

    def test_low_steps_execute_in_order_and_store_per_step_results(self, monkeypatch):
        ticket_mock = _mock_tool("crear_ticket", return_value="Ticket #5 creado")
        email_mock = _mock_tool("enviar_email", return_value="Email enviado")
        monkeypatch.setattr(action_agent_module, "TOOLS", {"crear_ticket": ticket_mock, "enviar_email": email_mock})

        steps = [
            _make_step("crear_ticket", {"titulo": "A", "descripcion": "x", "prioridad": "baja"}),
            _make_step("crear_ticket", {"titulo": "B", "descripcion": "y", "prioridad": "media"}),
            _make_step("crear_ticket", {"titulo": "C", "descripcion": "z", "prioridad": "alta"}),
        ]
        plan = _make_action_plan(steps)

        result = _run_executor_to_completion({"role": "empleado", "user_id": "ana.garcia", "action_plan": plan})

        plan = result["action_plan"]
        assert ticket_mock.invoke.call_count == 3, "Debe ejecutar los 3 pasos low en orden"
        assert plan["steps"][0]["execution_status"] == "succeeded"
        assert plan["steps"][0]["result"] == "Ticket #5 creado"
        assert plan["steps"][1]["execution_status"] == "succeeded"
        assert plan["steps"][2]["execution_status"] == "succeeded"
        assert plan["plan_status"] == "completed"

        call_titles = [call.args[0]["titulo"] for call in ticket_mock.invoke.call_args_list]
        assert call_titles == ["A", "B", "C"]

    def test_step_failure_cancels_remaining_steps_and_sets_plan_failed(self, monkeypatch):
        def fail_on_second(args):
            if args.get("titulo") == "B":
                raise ValueError("Error: fallo el paso 2")
            return "Ticket creado"

        ticket_mock = _mock_tool("crear_ticket", side_effect=fail_on_second)
        monkeypatch.setattr(action_agent_module, "TOOLS", {"crear_ticket": ticket_mock})

        steps = [
            _make_step("crear_ticket", {"titulo": "A"}, execution_status="succeeded", result="Ticket #1"),
            _make_step("crear_ticket", {"titulo": "B"}),
            _make_step("crear_ticket", {"titulo": "C"}),
        ]
        plan = _make_action_plan(steps, current_step=1, top_approval="approved", top_execution="not_started")

        result = action_executor_node({"role": "empleado", "user_id": "ana.garcia", "action_plan": plan})

        plan = result["action_plan"]
        assert plan["steps"][1]["execution_status"] == "failed"
        assert plan["steps"][2]["execution_status"] == "cancelled"
        assert plan["plan_status"] == "failed"
        # El resumen debe reportar qué se ejecutó y qué se canceló
        assert "Ejecutados" in result["respuesta"] or "Cancelados" in result["respuesta"]

    def test_succeeded_step_is_never_re_executed(self, monkeypatch):
        ticket_mock = _mock_tool("crear_ticket", return_value="Ticket creado")
        monkeypatch.setattr(action_agent_module, "TOOLS", {"crear_ticket": ticket_mock})

        steps = [
            _make_step("crear_ticket", {"titulo": "A"}, execution_status="succeeded", result="Ticket #1"),
            _make_step("crear_ticket", {"titulo": "B"}),
        ]
        plan = _make_action_plan(steps, current_step=1, top_approval="approved", top_execution="not_started")

        result = action_executor_node({"role": "empleado", "user_id": "ana.garcia", "action_plan": plan})

        assert ticket_mock.invoke.call_count == 1
        assert ticket_mock.invoke.call_args[0][0]["titulo"] == "B"
        assert result["action_plan"]["steps"][1]["execution_status"] == "succeeded"

    def test_prev_result_placeholder_is_substituted_literally(self, monkeypatch):
        email_mock = _mock_tool("enviar_email", return_value="Email enviado")
        monkeypatch.setattr(action_agent_module, "TOOLS", {"enviar_email": email_mock})

        steps = [
            _make_step("crear_ticket", {"titulo": "x"}, execution_status="succeeded", result="TICKET-123"),
            _make_step(
                "enviar_email",
                {"para": "rrhh@aegiscorp.com", "asunto": "Ticket", "cuerpo": "{{prev_result}}"},
                depends_on_previous=True,
                approval_status="approved",
            ),
        ]
        plan = _make_action_plan(steps, current_step=1, top_approval="approved", top_execution="not_started")

        action_executor_node({"role": "admin", "user_id": "admin.aegis", "action_plan": plan})

        call = email_mock.invoke.call_args[0][0]
        assert call["cuerpo"] == "TICKET-123"
        assert call["asunto"] == "Ticket"  # No se interpoló en campos sin placeholder

    def test_created_by_and_role_injected_per_step(self, monkeypatch):
        ticket_mock = _mock_tool("crear_ticket", return_value="Ticket creado")
        monkeypatch.setattr(action_agent_module, "TOOLS", {"crear_ticket": ticket_mock})

        steps = [
            _make_step("crear_ticket", {"titulo": "A"}),
            _make_step("crear_ticket", {"titulo": "B"}),
        ]
        plan = _make_action_plan(steps, top_approval="approved", top_execution="not_started")

        _run_executor_to_completion({"role": "empleado", "user_id": "ana.garcia", "action_plan": plan})

        for call in ticket_mock.invoke.call_args_list:
            args = call.args[0]
            assert args["created_by"] == "ana.garcia"
            assert args["role"] == "empleado"

    def test_executor_iteration_ceiling_respected(self):
        # El grafo debe incluir un route_from_executor que evite loops infinitos
        route = graph_module.route_from_executor

        steps = [_make_step("crear_ticket", {"titulo": f"t{i}"}) for i in range(3)]
        state = {
            "action_plan": _make_action_plan(steps, current_step=0),
            "executor_iterations": 5,  # > max_steps (3) + 1
        }
        assert route(state) == graph_module.END


# -----------------------------------------------------------------------------
# Routing
# -----------------------------------------------------------------------------

class TestMultiStepRouting:
    """Contratos de enrutamiento con planes multi-paso."""

    def test_route_from_planner_goes_hitl_if_current_step_is_high(self):
        steps = [
            _make_step("crear_ticket", {"titulo": "x"}, risk_level="low"),
            _make_step("enviar_email", {"para": "rrhh@aegiscorp.com"}, risk_level="high", approval_status="pending"),
        ]
        plan = _make_action_plan(steps, current_step=1, top_approval="pending", top_execution="not_started")

        assert graph_module.route_from_planner({"action_plan": plan}) == "hitl_review"

    def test_route_from_executor_loops_to_executor_or_hitl_or_end(self):
        # Pasos ejecutables -> loop al executor
        steps = [
            _make_step("crear_ticket", {"titulo": "A"}, approval_status="not_required"),
            _make_step("enviar_email", {"para": "x"}, risk_level="high", approval_status="pending"),
        ]
        plan = _make_action_plan(steps, current_step=0, top_approval="approved", top_execution="not_started")
        assert graph_module.route_from_executor({"action_plan": plan}) == "action_executor"

        # Siguiente paso high pendiente -> hitl_review
        plan["current_step"] = 1
        assert graph_module.route_from_executor({"action_plan": plan}) == "hitl_review"

    def test_route_from_hitl_routes_to_executor_when_step_approved(self):
        steps = [
            _make_step("enviar_email", {"para": "x"}, risk_level="high", approval_status="approved"),
        ]
        plan = _make_action_plan(steps, current_step=0, top_approval="approved", top_execution="not_started")

        assert graph_module.route_from_hitl({"action_plan": plan}) == "action_executor"


# -----------------------------------------------------------------------------
# HITL por paso
# -----------------------------------------------------------------------------

class TestMultiStepHITL:
    """Contratos de HITL granular: aprobación/rechazo por paso."""

    def test_high_step_interrupt_approve_then_executes_and_continues(self):
        steps = [
            _make_step("crear_ticket", {"titulo": "x"}, execution_status="succeeded", result="Ticket #1"),
            _make_step(
                "enviar_email",
                {"para": "rrhh@aegiscorp.com", "asunto": "x", "cuerpo": "x"},
                risk_level="high",
                approval_status="pending",
            ),
        ]
        plan = _make_action_plan(
            steps,
            current_step=1,
            top_approval="pending",
            top_execution="not_started",
        )

        with patch("src.agents.hitl_node.interrupt", return_value="approve"):
            result = hitl_node({"action_plan": plan, "user_id": "ana.garcia"})

        step = result["action_plan"]["steps"][1]
        assert step["approval_status"] == "approved"
        assert step["approved_by"] is not None
        assert step["approved_at"] is not None
        assert result.get("requires_human_review") is False

    def test_reject_step_cancels_dependent_later_steps(self):
        steps = [
            _make_step(
                "enviar_email",
                {"para": "rrhh@aegiscorp.com"},
                risk_level="high",
                approval_status="pending",
            ),
            _make_step("enviar_email", {"para": "it@aegiscorp.com"}, depends_on_previous=True),
            _make_step("crear_ticket", {"titulo": "x"}, depends_on_previous=False),
        ]
        plan = _make_action_plan(steps, current_step=0, top_approval="pending", top_execution="not_started")

        with patch("src.agents.hitl_node.interrupt", return_value="reject"):
            result = hitl_node({"action_plan": plan, "user_id": "ana.garcia"})

        steps_out = result["action_plan"]["steps"]
        assert steps_out[0]["approval_status"] == "rejected"
        assert steps_out[1]["execution_status"] == "cancelled"
        # El paso 2 es independiente y no debería cancelarse por el rechazo del paso 0
        assert steps_out[2]["execution_status"] != "cancelled"

    def test_expired_or_invalid_decision_rejects_step(self):
        old = (datetime.now() - timedelta(seconds=1000)).isoformat()
        steps = [
            _make_step(
                "enviar_email",
                {"para": "rrhh@aegiscorp.com"},
                risk_level="high",
                approval_status="pending",
            )
        ]
        plan = _make_action_plan(steps, top_approval="pending", top_execution="not_started")
        plan["created_at"] = old

        with patch("src.agents.hitl_node.interrupt", return_value="approve"):
            result = hitl_node({"action_plan": plan, "user_id": "ana.garcia"})

        assert result["action_plan"]["steps"][0]["approval_status"] in ("expired", "rejected")

        plan2 = _make_action_plan(
            [_make_step("enviar_email", {"para": "rrhh@aegiscorp.com"}, risk_level="high", approval_status="pending")],
            top_approval="pending",
            top_execution="not_started",
        )
        with patch("src.agents.hitl_node.interrupt", return_value="maybe"):
            result2 = hitl_node({"action_plan": plan2, "user_id": "ana.garcia"})

        assert result2["action_plan"]["steps"][0]["approval_status"] == "rejected"

    def test_two_high_steps_produce_two_sequential_interrupts(self):
        steps = [
            _make_step("enviar_email", {"para": "rrhh@aegiscorp.com"}, risk_level="high", approval_status="pending"),
            _make_step("enviar_email", {"para": "it@aegiscorp.com"}, risk_level="high", approval_status="pending"),
        ]

        plan0 = _make_action_plan(steps, current_step=0, top_approval="pending", top_execution="not_started")
        with patch("src.agents.hitl_node.interrupt", return_value="approve") as mock_interrupt:
            r0 = hitl_node({"action_plan": plan0, "user_id": "ana.garcia"})

        steps[0]["approval_status"] = "approved"
        steps[0]["approved_by"] = "admin.julia"
        plan1 = _make_action_plan(steps, current_step=1, top_approval="pending", top_execution="not_started")
        with patch("src.agents.hitl_node.interrupt", return_value="approve") as mock_interrupt2:
            r1 = hitl_node({"action_plan": plan1, "user_id": "ana.garcia"})

        assert mock_interrupt.called
        assert mock_interrupt2.called
        assert r0["action_plan"]["steps"][0]["approved_by"] == "admin.julia"
        assert r1["action_plan"]["steps"][1]["approved_by"] is not None
        assert r1["action_plan"]["steps"][1]["approved_at"] is not None


# -----------------------------------------------------------------------------
# Onboarding (Fase 4)
# -----------------------------------------------------------------------------

class TestOnboarding:
    """Contratos del Onboarding Agent y su routing."""

    def _mock_onboarding_llm(self, es_alta: bool, nombre: str | None = None, email: str | None = None, departamento: str | None = None):
        llm = MagicMock()
        structured = MagicMock()
        structured.invoke.return_value = SimpleNamespace(
            es_alta=es_alta, nombre=nombre, email=email, departamento=departamento
        )
        llm.with_structured_output.return_value = structured
        return llm

    def test_admin_routes_to_onboarding_intention(self):
        assert graph_module.route_from_supervisor({"intencion": "onboarding", "role": "admin"}) == "onboarding_agent"

    def test_empleado_alta_is_denied(self, monkeypatch):
        onboarding = importlib.import_module("src.agents.onboarding_agent")
        monkeypatch.setattr(onboarding, "get_fast_llm", lambda **kw: self._mock_onboarding_llm(True))

        result = onboarding.onboarding_node(
            {
                "query": "dar de alta a Pedro Gómez (pedro@aegiscorp.com) en Ventas",
                "user_id": "ana.garcia",
                "role": "empleado",
            }
        )
        assert result.get("authorization_decision") == "denied" or "administradores" in result.get("respuesta", "").lower()

    def test_onboarding_agent_returns_deterministic_three_step_plan(self, monkeypatch):
        onboarding = importlib.import_module("src.agents.onboarding_agent")
        monkeypatch.setattr(onboarding, "get_fast_llm", lambda **kw: self._mock_onboarding_llm(True))

        result = onboarding.onboarding_node(
            {
                "query": "dar de alta a Pedro Gómez (pedro@aegiscorp.com) en Ventas",
                "user_id": "admin.aegis",
                "role": "admin",
            }
        )
        plan = result.get("action_plan")
        assert plan is not None
        assert "steps" in plan
        assert len(plan["steps"]) == 3
        tool_names = [s["tool_name"] for s in plan["steps"]]
        assert tool_names == ["crear_ticket", "crear_accesos", "enviar_email"]

    def test_onboarding_external_email_is_rejected(self, monkeypatch):
        onboarding = importlib.import_module("src.agents.onboarding_agent")
        monkeypatch.setattr(onboarding, "get_fast_llm", lambda **kw: self._mock_onboarding_llm(True))

        result = onboarding.onboarding_node(
            {
                "query": "dar de alta a Pedro (pedro@gmail.com) en Ventas",
                "user_id": "admin.aegis",
                "role": "admin",
            }
        )
        assert result.get("action_plan") is None or result["action_plan"].get("plan_status") == "rejected"


# -----------------------------------------------------------------------------
# API / streaming
# -----------------------------------------------------------------------------

class TestMultiStepAPI:
    """Contratos de /chat y /chat/stream con planes multi-paso."""

    def test_chat_multi_step_high_requires_hitl_and_thread_id(self, monkeypatch, tmp_path):
        reset_user("admin.aegis")

        ticket_mock = _mock_tool("crear_ticket", return_value="Ticket #5 creado")
        email_mock = _mock_tool("enviar_email", return_value="Email enviado")
        monkeypatch.setattr(action_agent_module, "TOOLS", {"crear_ticket": ticket_mock, "enviar_email": email_mock})

        steps = [
            _action_step("crear_ticket", {"titulo": "x", "descripcion": "y", "prioridad": "baja"}),
            _action_step("enviar_email", {"para": "rrhh@aegiscorp.com", "asunto": "x", "cuerpo": "x"}),
        ]
        planner_llm = _mock_llm_for_steps(steps)
        monkeypatch.setattr(action_agent_module, "get_llm", lambda **kw: planner_llm)

        new_graph = graph_module.build_graph(checkpointer=MemorySaver())
        monkeypatch.setattr("src.api.main._graph", new_graph)

        r = client.post(
            "/chat",
            json={"query": "crea un ticket y envía un email a rrhh@aegiscorp.com"},
            headers={"Authorization": f"Bearer {_token('admin', 'admin.aegis')}"},
        )

        assert r.status_code == 200, r.text
        data = r.json()
        assert data["requires_hitl"] is True, "Un plan con paso high debe requerir HITL"
        assert data["thread_id"]

    def test_stream_emits_interrupt_for_high_step_and_done_requires_hitl(self, monkeypatch, tmp_path):
        """Contrato streaming: al toparse con un paso high el stream emite un
        evento `interrupt` y cierra con `done` marcando `requires_hitl=True`.
        La aprobación y continuación de pasos high adicionales se maneja
        fuera del stream vía /hitl/approve (ver TestMultiStepHITL)."""
        reset_user("admin.aegis")

        steps = [
            _make_step("crear_ticket", {"titulo": "x"}, execution_status="succeeded", result="Ticket #1"),
            _make_step(
                "enviar_email",
                {"para": "rrhh@aegiscorp.com", "asunto": "x", "cuerpo": "x"},
                risk_level="high",
                approval_status="pending",
            ),
            _make_step(
                "enviar_email",
                {"para": "it@aegiscorp.com", "asunto": "y", "cuerpo": "y"},
                risk_level="high",
                approval_status="pending",
            ),
        ]

        async def fake_astream(inputs, config=None, stream_mode=None, version=None, **kwargs):
            # Simula el grafo real: planifica, ejecuta pasos low y se detiene en el primer paso high.
            plan = _make_action_plan(steps, current_step=1)
            yield {"type": "updates", "data": {"action_planner": {"action_plan": plan}}}
            yield {
                "type": "values",
                "data": {"action_plan": plan, "__interrupt__": (SimpleNamespace(value="Paso 1 high"),)},
            }

        mock_graph = MagicMock()
        mock_graph.astream = fake_astream
        monkeypatch.setattr("src.api.main._graph", mock_graph)
        monkeypatch.setattr("src.api.main._async_graph", mock_graph)
        monkeypatch.setattr("src.api.streaming.hitl_db.enqueue", MagicMock())

        r = client.post(
            "/chat/stream",
            json={"query": "crea un ticket y envía dos emails"},
            headers={"Authorization": f"Bearer {_token('admin', 'admin.aegis')}"},
        )

        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(r.text)
        types = [e["type"] for e in events]

        # El primer paso high debe pausar el stream con un evento interrupt.
        assert types.count("interrupt") == 1, f"Se esperaba 1 interrupt, se obtuvo {events}"

        done = events[-1]
        assert done["type"] == "done"
        payload = done["payload"]
        assert payload["requires_hitl"] is True
        assert payload["thread_id"]
        assert "aprobación" in payload["respuesta"].lower() or "HITL" in payload["respuesta"].upper()


# -----------------------------------------------------------------------------
# Integración de grafo (smoke)
# -----------------------------------------------------------------------------

class TestGraphIntegration:
    """Validación end-to-end con el grafo real parcheado."""

    def test_compound_action_routes_through_multistep(self, monkeypatch):
        reset_user("admin.aegis")

        ticket_mock = _mock_tool("crear_ticket", return_value="Ticket #1 creado")
        email_mock = _mock_tool("enviar_email", return_value="Email enviado")
        monkeypatch.setattr(action_agent_module, "TOOLS", {"crear_ticket": ticket_mock, "enviar_email": email_mock})

        steps = [
            _action_step("crear_ticket", {"titulo": "x", "descripcion": "y", "prioridad": "baja"}),
            _action_step("enviar_email", {"para": "rrhh@aegiscorp.com"}),
        ]
        planner_llm = _mock_llm_for_steps(steps)
        monkeypatch.setattr(action_agent_module, "get_llm", lambda **kw: planner_llm)

        graph = graph_module.build_graph(checkpointer=MemorySaver())
        config = {"configurable": {"thread_id": "test-thread"}}
        result = graph.invoke(
            {
                "messages": [],
                "query": "crea un ticket y envía un email a rrhh@aegiscorp.com",
                "user_id": "admin.aegis",
                "role": "admin",
                "intencion": "",
                "respuesta": "",
                "fuentes": [],
                "confidence": 0.0,
                "requires_human_review": False,
                "retries": 0,
                "action_retries": 0,
                "tool_name": None,
                "authorization_decision": None,
                "action_plan": None,
                "approved_by": None,
                "approved_at": None,
            },
            config=config,
        )

        plan = result.get("action_plan")
        assert plan is not None
        assert "steps" in plan, "El grafo debe producir un plan con steps"
        assert len(plan["steps"]) == 2
        assert plan["steps"][1]["tool_name"] == "enviar_email"
        assert plan["steps"][1]["risk_level"] == "high"
        # El paso high debe pausar el grafo para HITL
        assert result.get("__interrupt__") or result.get("requires_human_review")
