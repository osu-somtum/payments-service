"""The game server's players: bancho.py's users table, or osu-web's phpbb_users.

Both are read as (id, name), so queries elsewhere don't depend on which server this runs with.
"""
from __future__ import annotations

from typing import Any

from app import settings
from app.database import database

if settings.IS_OSU_WEB:
    # osu-web's accounts, in its own database on the same MySQL server.
    USERS_TABLE = f"(SELECT user_id AS id, username AS name FROM `{settings.OSU_WEB_DB_NAME}`.`phpbb_users`)"
else:
    USERS_TABLE = "users"


async def fetch(user_id: int) -> dict[str, Any] | None:
    """The player as {"id", "name"}, or None when there's no such account."""
    row = await database.fetch_one(f"SELECT id, name FROM {USERS_TABLE} u WHERE id = :id", {"id": user_id})
    return {"id": int(row["id"]), "name": row["name"]} if row is not None else None
