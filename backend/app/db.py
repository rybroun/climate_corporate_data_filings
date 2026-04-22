"""
Supabase database client.

Wraps the Supabase Python client to provide both table-level CRUD
and a pool-like interface for raw SQL via the PostgREST API.
No separate DATABASE_URL needed — just SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_client = None


def get_client():
    """Get or create the Supabase client."""
    global _client
    if _client is None:
        if not settings.supabase_url or not settings.supabase_service_role_key:
            logger.warning("SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set")
            return None
        from supabase import create_client
        _client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    return _client


class SupabasePool:
    """Wrapper that gives pipeline steps a consistent interface for DB operations.

    Uses Supabase's table API for reads/writes rather than raw SQL,
    since PostgREST doesn't support arbitrary SQL.
    """

    def __init__(self):
        self._client = get_client()

    @property
    def available(self) -> bool:
        return self._client is not None

    def table(self, name: str):
        if not self._client:
            return None
        return self._client.table(name)

    def storage(self):
        if not self._client:
            return None
        return self._client.storage

    # --- Convenience methods matching what pipeline steps need ---

    def select(self, table_name: str, columns: str = "*", **filters) -> list[dict]:
        """SELECT with filters. Returns list of row dicts."""
        if not self._client:
            return []
        try:
            q = self._client.table(table_name).select(columns)
            for col, val in filters.items():
                q = q.eq(col, val)
            result = q.execute()
            return result.data or []
        except Exception:
            logger.error("select from %s failed", table_name, exc_info=True)
            return []

    def select_ilike(self, table_name: str, column: str, pattern: str, columns: str = "*", limit: int = 5) -> list[dict]:
        """SELECT with ILIKE pattern match."""
        if not self._client:
            return []
        try:
            result = (
                self._client.table(table_name)
                .select(columns)
                .ilike(column, pattern)
                .limit(limit)
                .execute()
            )
            return result.data or []
        except Exception:
            logger.error("select_ilike from %s failed", table_name, exc_info=True)
            return []

    def insert(self, table_name: str, data: dict, on_conflict: str | None = None) -> dict | None:
        """INSERT a row. Returns the inserted row dict, or None."""
        if not self._client:
            return None
        try:
            q = self._client.table(table_name).insert(data)
            if on_conflict:
                q = self._client.table(table_name).upsert(data, on_conflict=on_conflict)
            result = q.execute()
            return result.data[0] if result.data else None
        except Exception:
            logger.error("insert into %s failed", table_name, exc_info=True)
            return None

    def upsert(self, table_name: str, data: dict, on_conflict: str = "") -> dict | None:
        """UPSERT a row. Returns the upserted row dict, or None."""
        if not self._client:
            return None
        try:
            result = self._client.table(table_name).upsert(data, on_conflict=on_conflict).execute()
            return result.data[0] if result.data else None
        except Exception:
            logger.error("upsert into %s failed", table_name, exc_info=True)
            return None

    def rpc(self, fn_name: str, params: dict) -> list[dict]:
        """Call a Postgres function via RPC."""
        if not self._client:
            return []
        try:
            result = self._client.rpc(fn_name, params).execute()
            return result.data or []
        except Exception:
            logger.error("rpc %s failed", fn_name, exc_info=True)
            return []


_pool: SupabasePool | None = None


def get_pool() -> SupabasePool | None:
    """Return the SupabasePool wrapper, or None if not configured."""
    global _pool
    if _pool is None:
        _pool = SupabasePool()
        if not _pool.available:
            return None
    return _pool


async def init_pool():
    """Initialize the Supabase client at startup."""
    get_pool()


async def close_pool():
    """No-op for Supabase client."""
    pass
