"""Adaptador de Supabase para Aegis Desk.

Expone clientes distintos para operaciones de autenticacion (anon/public)
y de backend/admin (service/secret). Se usa solo si SUPABASE_URL y las keys
estan configuradas.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.config import get_settings

if TYPE_CHECKING:
    from supabase.client import Client


def is_supabase_configured() -> bool:
    """Devuelve True si hay credenciales de Supabase configuradas."""
    settings = get_settings()
    return bool(settings.supabase_url and settings.supabase_key)


def _create_client(key: str) -> "Client":
    """Crea un cliente de Supabase con la key dada."""
    try:
        from supabase import create_client
    except ImportError as exc:
        raise RuntimeError("Paquete 'supabase' no instalado. Ejecuta: pip install supabase") from exc
    settings = get_settings()
    return create_client(settings.supabase_url, key)


def get_supabase_client() -> "Client":
    """Cliente anon/public para auth y operaciones de frontend."""
    settings = get_settings()
    return _create_client(settings.supabase_key)


def get_supabase_service_client() -> "Client":
    """Cliente service/secret para operaciones de backend (RLS bypass)."""
    settings = get_settings()
    key = settings.supabase_service_key or settings.supabase_key
    return _create_client(key)
