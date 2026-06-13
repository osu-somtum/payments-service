"""Auth helpers for payment-service.

- Session validation: direct DB lookup (shared MySQL sessions table).
- Bot auth: bearer token matching BOT_API_TOKEN.
- Internal endpoint guard: X-Internal-Token for bancho.py ↔ payment-service calls.
"""
from __future__ import annotations

from fastapi import Header, HTTPException, status

from app import settings
from app.database import database


async def resolve_session_user(session_token: str | None) -> int | None:
    """Return userid for a valid session token, or None."""
    if not session_token:
        return None
    row = await database.fetch_one(
        "SELECT userid FROM sessions WHERE session_token = :token",
        {"token": session_token},
    )
    return int(row["userid"]) if row else None


def require_bot_token(authorization: str | None = Header(default=None)) -> None:
    if not settings.BOT_API_TOKEN:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Bot API not configured.")
    if authorization != f"Bearer {settings.BOT_API_TOKEN}":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid bot token.")


def require_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
    if not settings.BANCHO_INTERNAL_TOKEN:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Internal token not configured.")
    if x_internal_token != settings.BANCHO_INTERNAL_TOKEN:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid internal token.")
