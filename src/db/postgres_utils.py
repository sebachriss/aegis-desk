"""Utilidades para conectar con Postgres/Supabase.

Normaliza DATABASE_URL para soportar passwords con caracteres especiales
(% , @, #, etc.) que de otro modo rompen psycopg/psycopg2.
"""

from urllib.parse import urlparse, quote, urlunparse


def normalize_database_url(url: str) -> str:
    """Re-encode userinfo de una DATABASE_URL para que sea valida para libpq."""
    parsed = urlparse(url)
    user = quote(parsed.username or "", safe="")
    password = quote(parsed.password or "", safe="")
    if user and password:
        netloc = f"{user}:{password}@{parsed.hostname}"
    elif user:
        netloc = f"{user}@{parsed.hostname}"
    elif password:
        netloc = f":{password}@{parsed.hostname}"
    else:
        netloc = parsed.hostname or ""
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


_pool = None


def get_postgres_pool(conninfo: str | None = None, **kwargs):
    """Devuelve un ConnectionPool de psycopg (v3) normalizado.

    El pool se cachea para reutilizarlo en la aplicacion.
    """
    global _pool
    if _pool is not None:
        return _pool

    import os
    import psycopg_pool

    if conninfo is None:
        from src.config import get_settings
        conninfo = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DATABASE_URL") or get_settings().database_url
    if not conninfo:
        raise RuntimeError("DATABASE_URL no configurada")

    normalized = normalize_database_url(conninfo)
    _pool = psycopg_pool.ConnectionPool(
        normalized,
        min_size=1,
        max_size=10,
        open=True,
        kwargs=kwargs,
    )
    _pool.wait()
    return _pool


def get_postgres_connection(conninfo: str | None = None, *, read_only: bool = False, **kwargs):
    """Devuelve una conexion psycopg (v3) normalizada.

    Args:
        conninfo: URL de conexion. Si es None, usa DATABASE_URL del .env.
        read_only: Si es True, fuerza la sesion a modo solo lectura.
        kwargs: argumentos extra para psycopg.connect.
    """
    import os
    import psycopg

    if conninfo is None:
        from src.config import get_settings
        conninfo = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DATABASE_URL") or get_settings().database_url
    if not conninfo:
        raise RuntimeError("DATABASE_URL no configurada")

    normalized = normalize_database_url(conninfo)
    if read_only:
        kwargs.setdefault("options", "-c default_transaction_read_only=on")
    return psycopg.connect(normalized, **kwargs)
