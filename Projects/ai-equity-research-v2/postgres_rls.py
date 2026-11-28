"""PostgreSQL transaction-local tenant context for owner-scoped stores."""
from __future__ import annotations
from typing import Any


def connect_with_owner_context(url: str, owner_id: str | None, actor_id: str | None = None, *, connect_timeout: int = 15) -> Any:
    """Bind trusted identity to this transaction; context cannot leak across transactions."""
    owner, actor = str(owner_id or "").strip(), str(actor_id or "").strip()
    if not owner and not actor:
        raise ValueError("PostgreSQL tenant context requires an authenticated owner or actor.")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("Driver PostgreSQL belum terpasang. Instal psycopg[binary].") from exc
    connection = psycopg.connect(url, row_factory=dict_row, connect_timeout=connect_timeout)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('app.current_owner_id', %s, true), "
                "set_config('app.current_actor_id', %s, true)",
                (owner, actor),
            )
        return connection
    except Exception:
        connection.close()
        raise
