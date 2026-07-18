import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

# Entorno determinista para tests sin depender de .env
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("DEEPINFRA_API_KEY", "fake-key-for-tests")
os.environ.setdefault("SUPABASE_URL", "")
os.environ.setdefault("SUPABASE_KEY", "")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "")


@pytest.fixture
def vacaciones_db(tmp_path, monkeypatch):
    """Base de datos SQLite temporal con tablas y seeds de vacaciones."""
    db = tmp_path / "aegis.db"
    monkeypatch.setattr("src.tools.sql.DB_PATH", db)
    monkeypatch.setattr("src.tools.tickets.DB_PATH", db)
    monkeypatch.setattr("src.tools.vacaciones.DB_PATH", db)
    from src.tools.sql import _init_db

    _init_db()
    yield db


@pytest.fixture
def action_plan_factory():
    """Factory para construir action plans de vacaciones."""
    def _make(tool_name, arguments, approval_status, role="empleado", user_id="ana.garcia"):
        return {
            "action_id": "act_test",
            "tool_name": tool_name,
            "arguments": arguments,
            "requested_by": user_id,
            "role": role,
            "risk_level": "high" if tool_name == "solicitar_vacaciones" else "low",
            "approval_status": approval_status,
            "execution_status": "not_started",
            "idempotency_key": "key_test",
            "created_at": datetime.now().isoformat(),
            "executed_at": None,
            "reasoning": "test",
        }

    return _make


class TestVacacionesTools:
    """Tests de las tools de vacaciones (backend SQLite, deterministas)."""

    def test_consultar_saldo_vacaciones(self, vacaciones_db):
        from src.tools.vacaciones import consultar_saldo_vacaciones

        result = consultar_saldo_vacaciones.invoke({"created_by": "ana.garcia", "role": "empleado"})
        assert "disponibles" in result
        assert "22" in result
        assert "usados" in result

    def test_solicitud_valida_descuenta_saldo_y_crea_registro(self, vacaciones_db):
        from src.tools.vacaciones import (
            consultar_saldo_vacaciones,
            listar_solicitudes_vacaciones,
            solicitar_vacaciones,
        )

        result = solicitar_vacaciones.invoke(
            {
                "fecha_inicio": "2099-08-03",
                "fecha_fin": "2099-08-07",
                "motivo": "descanso",
                "created_by": "ana.garcia",
                "role": "empleado",
            }
        )
        assert "aprobada" in result.lower()

        saldo = consultar_saldo_vacaciones.invoke({"created_by": "ana.garcia", "role": "empleado"})
        assert "usados: 5" in saldo or "usados 5" in saldo
        assert "disponibles: 17" in saldo or "disponibles 17" in saldo

        lista = listar_solicitudes_vacaciones.invoke({"created_by": "ana.garcia", "role": "empleado"})
        assert "aprobada" in lista.lower()
        assert "ana@aegiscorp.com" in lista

    def test_solicitud_fechas_invalidas_no_modifica_db(self, vacaciones_db):
        from src.tools.vacaciones import consultar_saldo_vacaciones, solicitar_vacaciones

        invalid_cases = [
            ("2099-13-01", "2099-08-05"),
            ("2020-08-01", "2099-08-05"),
            ("2099-08-10", "2099-08-05"),
        ]
        for fi, ff in invalid_cases:
            with pytest.raises(ValueError, match="Error:"):
                solicitar_vacaciones.invoke(
                    {
                        "fecha_inicio": fi,
                        "fecha_fin": ff,
                        "motivo": "x",
                        "created_by": "ana.garcia",
                        "role": "empleado",
                    }
                )

        saldo = consultar_saldo_vacaciones.invoke({"created_by": "ana.garcia", "role": "empleado"})
        assert "usados: 0" in saldo or "usados 0" in saldo

    def test_saldo_insuficiente_rechaza(self, vacaciones_db):
        from src.tools.vacaciones import consultar_saldo_vacaciones, solicitar_vacaciones

        # Consume 20 días hábiles (1-28 de agosto = 4 semanas exactas)
        solicitar_vacaciones.invoke(
            {
                "fecha_inicio": "2099-08-01",
                "fecha_fin": "2099-08-28",
                "motivo": "consume saldo",
                "created_by": "ana.garcia",
                "role": "empleado",
            }
        )

        with pytest.raises(ValueError, match="Error:"):
            solicitar_vacaciones.invoke(
                {
                    "fecha_inicio": "2099-09-01",
                    "fecha_fin": "2099-09-05",
                    "motivo": "x",
                    "created_by": "ana.garcia",
                    "role": "empleado",
                }
            )

        saldo = consultar_saldo_vacaciones.invoke({"created_by": "ana.garcia", "role": "empleado"})
        assert "usados: 20" in saldo or "usados 20" in saldo

    def test_mas_de_20_dias_rechaza(self, vacaciones_db):
        from src.tools.vacaciones import solicitar_vacaciones

        with pytest.raises(ValueError, match="Error:"):
            solicitar_vacaciones.invoke(
                {
                    "fecha_inicio": "2099-08-01",
                    "fecha_fin": "2099-08-31",
                    "motivo": "x",
                    "created_by": "ana.garcia",
                    "role": "empleado",
                }
            )

    def test_dias_habiles_cruzan_fin_de_semana(self, vacaciones_db):
        from src.tools.vacaciones import consultar_saldo_vacaciones, solicitar_vacaciones

        # 2099-08-07 es viernes, 2099-08-10 es lunes -> 2 días hábiles
        result = solicitar_vacaciones.invoke(
            {
                "fecha_inicio": "2099-08-07",
                "fecha_fin": "2099-08-10",
                "motivo": "puente",
                "created_by": "ana.garcia",
                "role": "empleado",
            }
        )
        assert "2" in result

        saldo = consultar_saldo_vacaciones.invoke({"created_by": "ana.garcia", "role": "empleado"})
        assert "usados: 2" in saldo or "usados 2" in saldo

    def test_empleado_no_consulta_saldo_ajeno(self, vacaciones_db):
        from src.tools.vacaciones import consultar_saldo_vacaciones

        result = consultar_saldo_vacaciones.invoke(
            {
                "created_by": "ana.garcia",
                "role": "empleado",
                "empleado_email": "carlos.ruiz",
            }
        )
        assert "Error:" in result

    def test_admin_puede_consultar_saldo_ajeno(self, vacaciones_db):
        from src.tools.vacaciones import consultar_saldo_vacaciones

        result = consultar_saldo_vacaciones.invoke(
            {
                "created_by": "admin.aegis",
                "role": "admin",
                "empleado_email": "carlos.ruiz",
            }
        )
        assert "disponibles" in result

    def test_listar_solicitudes_filtra_por_ownership(self, vacaciones_db):
        from src.tools.vacaciones import listar_solicitudes_vacaciones, solicitar_vacaciones

        solicitar_vacaciones.invoke(
            {
                "fecha_inicio": "2099-08-03",
                "fecha_fin": "2099-08-04",
                "motivo": "ana",
                "created_by": "ana.garcia",
                "role": "empleado",
            }
        )
        solicitar_vacaciones.invoke(
            {
                "fecha_inicio": "2099-08-05",
                "fecha_fin": "2099-08-06",
                "motivo": "carlos",
                "created_by": "carlos.ruiz",
                "role": "empleado",
            }
        )

        lista_ana = listar_solicitudes_vacaciones.invoke({"created_by": "ana.garcia", "role": "empleado"})
        assert "ana" in lista_ana
        assert "carlos" not in lista_ana

        lista_admin = listar_solicitudes_vacaciones.invoke({"created_by": "admin.aegis", "role": "admin"})
        assert "ana" in lista_admin
        assert "carlos" in lista_admin


class TestVacacionesActionAgent:
    """Tests de planificación, RBAC, HITL y ejecución del action agent."""

    def test_solicitar_vacaciones_es_high_risk(self):
        from src.agents.action_agent import _determine_risk_level

        assert _determine_risk_level("solicitar_vacaciones") == "high"
        assert _determine_risk_level("consultar_saldo_vacaciones") == "low"
        assert _determine_risk_level("listar_solicitudes_vacaciones") == "low"

    def test_action_planner_genera_plan_pendiente(self):
        from src.agents.action_agent import ActionPlan, action_planner_node

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.invoke.return_value = ActionPlan(
            tool_name="solicitar_vacaciones",
            arguments={
                "fecha_inicio": "2099-08-01",
                "fecha_fin": "2099-08-05",
                "motivo": "descanso",
            },
            reasoning="solicitar vacaciones",
        )
        mock_llm.with_structured_output.return_value = mock_structured

        with patch("src.agents.action_agent.get_llm", return_value=mock_llm):
            result = action_planner_node(
                {
                    "query": "Quiero solicitar vacaciones del 1 al 5 de agosto",
                    "user_id": "ana.garcia",
                    "role": "empleado",
                }
            )

        assert result["tool_name"] == "solicitar_vacaciones"
        assert result["action_plan"]["risk_level"] == "high"
        assert result["action_plan"]["approval_status"] == "pending"
        assert result["authorization_decision"] == "allowed"

    def test_action_planner_rechaza_fechas_invalidas(self):
        from src.agents.action_agent import ActionPlan, action_planner_node

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.invoke.return_value = ActionPlan(
            tool_name="solicitar_vacaciones",
            arguments={
                "fecha_inicio": "2020-08-01",
                "fecha_fin": "2020-08-05",
                "motivo": "x",
            },
            reasoning="x",
        )
        mock_llm.with_structured_output.return_value = mock_structured

        with patch("src.agents.action_agent.get_llm", return_value=mock_llm):
            result = action_planner_node(
                {
                    "query": "Solicito vacaciones pasadas",
                    "user_id": "ana.garcia",
                    "role": "empleado",
                }
            )

        assert result["action_plan"] is None
        assert "Error:" in result["respuesta"]

    def test_action_executor_no_ejecuta_sin_aprobacion(self, vacaciones_db, action_plan_factory):
        from src.agents.action_agent import action_executor_node
        from src.tools.vacaciones import consultar_saldo_vacaciones

        plan = action_plan_factory(
            "solicitar_vacaciones",
            {"fecha_inicio": "2099-08-01", "fecha_fin": "2099-08-05", "motivo": "x"},
            "pending",
        )
        result = action_executor_node(
            {"role": "empleado", "user_id": "ana.garcia", "action_plan": plan}
        )
        assert "no ha sido aprobada" in result["respuesta"].lower()

        saldo = consultar_saldo_vacaciones.invoke({"created_by": "ana.garcia", "role": "empleado"})
        assert "usados: 0" in saldo or "usados 0" in saldo

    def test_replay_bloquea_ejecucion_doble(self, vacaciones_db, action_plan_factory):
        from src.agents.action_agent import action_executor_node

        plan = action_plan_factory(
            "solicitar_vacaciones",
            {"fecha_inicio": "2099-08-01", "fecha_fin": "2099-08-05", "motivo": "x"},
            "approved",
        )
        result1 = action_executor_node(
            {"role": "empleado", "user_id": "ana.garcia", "action_plan": plan}
        )
        assert "aprobada" in result1["respuesta"].lower()

        result2 = action_executor_node(
            {"role": "empleado", "user_id": "ana.garcia", "action_plan": plan}
        )
        assert result1["respuesta"] == result2["respuesta"]

    def test_action_executor_rechaza_plan_expirado(self, vacaciones_db, action_plan_factory):
        from src.agents.action_agent import action_executor_node

        plan = action_plan_factory(
            "solicitar_vacaciones",
            {"fecha_inicio": "2099-08-01", "fecha_fin": "2099-08-05", "motivo": "x"},
            "expired",
        )
        result = action_executor_node(
            {"role": "empleado", "user_id": "ana.garcia", "action_plan": plan}
        )
        assert "no ha sido aprobada" in result["respuesta"].lower()


class TestVacacionesHITL:
    """Tests del nodo HITL para solicitudes de vacaciones."""

    def test_hitl_rechaza_expirado(self, action_plan_factory):
        from src.agents.hitl_node import hitl_node

        plan = action_plan_factory(
            "solicitar_vacaciones",
            {"fecha_inicio": "2099-08-01", "fecha_fin": "2099-08-05", "motivo": "x"},
            "pending",
        )
        plan["created_at"] = (datetime.now() - timedelta(seconds=1000)).isoformat()

        with patch("src.agents.hitl_node.interrupt", return_value="approve"):
            result = hitl_node({"action_plan": plan, "user_id": "ana.garcia"})

        assert result["action_plan"]["approval_status"] == "expired"

    def test_hitl_decision_invalida_rechaza(self, action_plan_factory):
        from src.agents.hitl_node import hitl_node

        plan = action_plan_factory(
            "solicitar_vacaciones",
            {"fecha_inicio": "2099-08-01", "fecha_fin": "2099-08-05", "motivo": "x"},
            "pending",
        )

        with patch("src.agents.hitl_node.interrupt", return_value="maybe"):
            result = hitl_node({"action_plan": plan, "user_id": "ana.garcia"})

        assert result["action_plan"]["approval_status"] == "rejected"

    def test_hitl_redacta_motivo_solicitud_vacaciones(self):
        from src.agents.hitl_node import _redact_sensitive_args

        args = {
            "fecha_inicio": "2099-08-01",
            "fecha_fin": "2099-08-05",
            "motivo": "x" * 100 + " sensitive tail",
        }
        safe = _redact_sensitive_args("solicitar_vacaciones", args)
        assert safe["fecha_inicio"] == "2099-08-01"
        assert safe["fecha_fin"] == "2099-08-05"
        assert "dias" in safe or "dias_habiles" in safe
        assert len(safe["motivo"]) <= 83  # 80 + "..."


class TestVacacionesSupervisor:
    """Tests de routing del supervisor para intenciones de vacaciones."""

    def test_solicitar_vacaciones_ruta_a_accion(self):
        from src.agents.supervisor import supervisor_node

        result = supervisor_node(
            {"query": "Quiero solicitar vacaciones del 1 al 5 de agosto"}
        )
        assert result["intencion"] == "accion"

    def test_consultar_saldo_ruta_a_accion(self):
        from src.agents.supervisor import supervisor_node

        result = supervisor_node({"query": "¿Cuál es mi saldo de vacaciones?"})
        assert result["intencion"] == "accion"

    def test_politica_vacaciones_sigue_rag(self):
        from src.agents.supervisor import supervisor_node

        result = supervisor_node({"query": "¿Cuál es la política de vacaciones?"})
        assert result["intencion"] == "rag"


class TestVacacionesRBAC:
    """Tests de RBAC para las nuevas tools."""

    def test_vacaciones_tools_permitidas_para_empleado_y_admin(self):
        from src.security.rbac import get_allowed_tools

        empleado = {getattr(t, "name", None) for t in get_allowed_tools("empleado")}
        admin = {getattr(t, "name", None) for t in get_allowed_tools("admin")}

        for name in [
            "consultar_saldo_vacaciones",
            "solicitar_vacaciones",
            "listar_solicitudes_vacaciones",
        ]:
            assert name in empleado, f"{name} falta para empleado"
            assert name in admin, f"{name} falta para admin"

    def test_rol_invalido_falla_cerrado(self):
        from src.security.rbac import get_allowed_tools, validate_role

        assert not validate_role("hacker")
        with pytest.raises(ValueError):
            get_allowed_tools("hacker")
