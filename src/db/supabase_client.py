"""Adaptador opcional de Supabase para tickets y SQL en Aegis Desk.

Usado solo si están configuradas SUPABASE_URL y SUPABASE_KEY.
En caso contrario el sistema sigue usando SQLite local.
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


def get_supabase_client() -> "Client":
    """Devuelve un cliente de Supabase (lazy import)."""
    try:
        from supabase import create_client
    except ImportError as exc:
        raise RuntimeError("Paquete 'supabase' no instalado. Ejecuta: pip install supabase") from exc
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_key)
