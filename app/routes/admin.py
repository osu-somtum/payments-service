"""Admin donation management routes (list, approve, reject)."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Path, Query
from fastapi.responses import ORJSONResponse
from starlette import status

from app.auth import resolve_session_user
from app.database import database
from app.repositories import donations as donations_repo
from app.usecases import donations as donations_uc
from app.webhooks import format_transaction, notify_review

router = APIRouter()

_DONATION_STATUSES = {"pending", "success", "failed"}
_DONATION_PROVIDERS = {"truemoney", "promptpay", "stripe"}


async def _resolve_admin(session_token: str | None) -> tuple[dict, ORJSONResponse | None]:
    """Return (admin_row, None) or (None, error_response)."""
    user_id = await resolve_session_user(session_token)
    if user_id is None:
        return {}, ORJSONResponse({"status": "Unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
    row = await database.fetch_one("SELECT id, name, priv FROM users WHERE id = :id", {"id": user_id})
    if row is None:
        return {}, ORJSONResponse({"status": "Unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
    # Privilege rank ≥ 2 = Administrator or Developer (bit 4 or 8 in bancho.py Privileges)
    # The check mirrors bancho.py's _resolve_admin(min_rank=2)
    ADMIN_BIT = 0b0001_0000  # Privileges.ADMINISTRATOR (bit 4)
    DEV_BIT   = 0b0010_0000  # Privileges.DEVELOPER    (bit 5)
    if not (int(row["priv"]) & (ADMIN_BIT | DEV_BIT)):
        return {}, ORJSONResponse({"status": "Forbidden"}, status_code=status.HTTP_403_FORBIDDEN)
    return dict(row), None


@router.get("/admin/donations")
async def admin_donations(
    session: str | None = Query(default=None),
    donation_status: str | None = Query(default=None, alias="status"),
    provider: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ORJSONResponse:
    _admin, err = await _resolve_admin(session)
    if err is not None:
        return err
    if donation_status is not None and donation_status not in _DONATION_STATUSES:
        return ORJSONResponse({"status": "Invalid donation status."}, status_code=status.HTTP_400_BAD_REQUEST)
    if provider is not None and provider not in _DONATION_PROVIDERS:
        return ORJSONResponse({"status": "Invalid donation provider."}, status_code=status.HTTP_400_BAD_REQUEST)
    rows, total = await donations_repo.fetch_many(status=donation_status, provider=provider, limit=limit, offset=offset)
    return ORJSONResponse({
        "status": "success",
        "transactions": [format_transaction(r) for r in rows],
        "total": total, "limit": limit, "offset": offset,
    })


@router.post("/admin/donations/{transaction_id}/approve")
async def admin_approve_donation(
    transaction_id: int = Path(..., ge=1),
    session: str | None = Query(default=None),
    actual_amount_thb: float | None = Body(default=None, ge=0),
    note: str | None = Body(default=None),
) -> ORJSONResponse:
    admin, err = await _resolve_admin(session)
    if err is not None:
        return err
    if note is not None and len(note) > 500:
        return ORJSONResponse({"status": "Review note must be at most 500 characters."}, status_code=status.HTTP_400_BAD_REQUEST)
    try:
        transaction = await donations_uc.approve_transaction(
            transaction_id=transaction_id, actor_id=admin["id"],
            actual_amount_thb=actual_amount_thb, review_note=note,
            decision_source="admin_dashboard",
        )
    except donations_uc.DonationError as exc:
        return ORJSONResponse({"status": str(exc)}, status_code=status.HTTP_400_BAD_REQUEST)

    await database.execute(
        "INSERT INTO logs (`from`, `to`, `action`, `msg`, `time`) VALUES (:f, :t, :a, :m, NOW())",
        {"f": admin["id"], "t": transaction["target_user_id"], "a": "donation_approve",
         "m": f"Approved donation #{transaction_id} for {transaction['approved_amount_thb']} THB. Note: {note or 'none'}"},
    )
    try:
        await notify_review(transaction, action="approved", actor_name=admin.get("name"))
    except Exception:
        pass
    return ORJSONResponse({"status": "success", "message": "Donation approved.", "transaction": format_transaction(transaction)})


@router.post("/admin/donations/{transaction_id}/reject")
async def admin_reject_donation(
    transaction_id: int = Path(..., ge=1),
    session: str | None = Query(default=None),
    reason: str = Body(..., embed=True),
) -> ORJSONResponse:
    admin, err = await _resolve_admin(session)
    if err is not None:
        return err
    reason = reason.strip()
    if not reason or len(reason) > 500:
        return ORJSONResponse({"status": "Reason must be 1-500 characters."}, status_code=status.HTTP_400_BAD_REQUEST)
    try:
        transaction = await donations_uc.reject_transaction(
            transaction_id=transaction_id, actor_id=admin["id"],
            review_note=reason, decision_source="admin_dashboard",
        )
    except donations_uc.DonationError as exc:
        return ORJSONResponse({"status": str(exc)}, status_code=status.HTTP_400_BAD_REQUEST)

    await database.execute(
        "INSERT INTO logs (`from`, `to`, `action`, `msg`, `time`) VALUES (:f, :t, :a, :m, NOW())",
        {"f": admin["id"], "t": transaction["target_user_id"], "a": "donation_reject",
         "m": f"Rejected donation #{transaction_id}. Reason: {reason}"},
    )
    try:
        await notify_review(transaction, action="rejected", actor_name=admin.get("name"))
    except Exception:
        pass
    return ORJSONResponse({"status": "success", "message": "Donation rejected.", "transaction": format_transaction(transaction)})
