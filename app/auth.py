"""Auth helpers for payment-service.

- Session validation: direct DB lookup (shared MySQL sessions table) — bancho.py.
- osu-web: it forwards the signed-in player's requests with the shared secret and their id.
- Bot auth: bearer token matching BOT_API_TOKEN.
- Internal endpoint guard: X-Internal-Token for bancho.py ↔ payment-service calls.
"""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status
from starlette.requests import Request

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


def _from_osu_web(request: Request) -> bool:
    """Whether the request carries osu-web's shared secret (it vouches for X-User-Id / X-User-Admin)."""
    token = request.headers.get("x-internal-token", "")
    return bool(settings.OSU_WEB_INTEROP_SECRET) and hmac.compare_digest(token, settings.OSU_WEB_INTEROP_SECRET)


async def request_user(request: Request) -> int | None:
    """The signed-in player making this request, or None.

    bancho: the "session" cookie or an Authorization bearer session token.
    osu-web: X-User-Id, only when the request carries osu-web's shared secret.
    """
    if settings.IS_OSU_WEB:
        if not _from_osu_web(request):
            return None
        try:
            return int(request.headers.get("x-user-id", ""))
        except ValueError:
            return None

    session_token = request.cookies.get("session")
    if not session_token:
        scheme, _, value = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() == "bearer" and value:
            session_token = value.strip()
    return await resolve_session_user(session_token)


def osu_web_admin(request: Request) -> bool:
    """osu-web: whether it says the player is staff allowed to review donations (X-User-Admin: 1)."""
    return _from_osu_web(request) and request.headers.get("x-user-admin") == "1"


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
