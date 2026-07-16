import pytest

from src.security.pii_filter import filter_pii
from src.security.rbac import can_access, get_allowed_tools, validate_role
from src.security.rate_limiter import check_login_rate_limit, check_rate_limit
from src.tools.sql import _has_limit_clause, _validate_select

class TestRBAC:
    def test_validate_role_known(self):
        assert validate_role("admin")
        assert validate_role("empleado")

    def test_validate_role_unknown(self):
        assert not validate_role("hacker")
        assert not validate_role("")
        assert not validate_role(None)

    def test_can_access_empleado(self):
        assert can_access("empleado", "rag")
        assert not can_access("empleado", "datos")

    def test_can_access_admin(self):
        assert can_access("admin", "datos")

class TestPII:
    def test_email_masked(self):
        out, dets = filter_pii("Contacta a ana@aegiscorp.com")
        assert "a***@aegiscorp.com" in out

    def test_salario_masked(self):
        out, dets = filter_pii("salario: 75000")
        assert "salario: ***" in out

    def test_iban_card_address_masked(self):
        text = "IBAN ES91 2345 6789 0123 4567 8901, tarjeta 1234 5678 9012 3456, vivo en Calle Mayor 1"
        out, dets = filter_pii(text)
        assert "ES **** **** 8901" in out
        assert "**** **** **** 3456" in out
        assert "[DIRECCION OCULTA]" in out

class TestRateLimiter:
    def test_rate_limit_blocks_after_max(self):
        from src.security.rate_limiter import reset_user
        reset_user("test_user")
        for i in range(10):
            assert check_rate_limit("test_user")["allowed"]
        assert not check_rate_limit("test_user")["allowed"]

    def test_login_rate_limit_blocks_after_max(self):
        from src.security.rate_limiter import reset_login
        reset_login("10.0.0.1")
        for i in range(12):
            assert check_login_rate_limit("10.0.0.1")["allowed"]
        assert not check_login_rate_limit("10.0.0.1")["allowed"]

class TestSQLValidation:
    def test_validate_select_accepts_select(self):
        assert _validate_select("SELECT * FROM empleados") is None

    def test_validate_select_rejects_drop(self):
        assert _validate_select("DROP TABLE empleados") is not None

    def test_has_limit_clause_detects_limit(self):
        assert _has_limit_clause("SELECT * FROM empleados LIMIT 10")
        assert not _has_limit_clause("SELECT * FROM empleados")
