"""TrueMoney voucher redeem route."""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Body
from fastapi.responses import ORJSONResponse
from starlette import status
from starlette.requests import Request

from app import settings
from app.auth import resolve_session_user
from app.repositories import donations as donations_repo
from app.usecases import donations as donations_uc
from app.webhooks import format_transaction

router = APIRouter()

_CONTACT_ADMIN_MSG = (
    "ระบบเติมเงินขัดข้อง กรุณาติดต่อแอดมินเพื่อขอความช่วยเหลือ "
    "(payment system error — please contact an administrator)."
)


@router.post("/donate/redeem")
async def donate_redeem(
    request: Request,
    voucher_code: str = Body(..., embed=True),
    target_user_id: int | None = Body(default=None, embed=True),
    anonymous: bool = Body(default=False, embed=True),
    message: str | None = Body(default=None, embed=True),
) -> ORJSONResponse:
    if not settings.TRUEMONEY_ENABLED:
        return ORJSONResponse(
            {"status": "disabled", "message": "TrueMoney donations are currently disabled."},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # Read session from cookie or Authorization bearer header
    session_token = request.cookies.get("session")
    if not session_token:
        auth = request.headers.get("authorization", "")
        scheme, _, value = auth.partition(" ")
        if scheme.lower() == "bearer" and value:
            session_token = value.strip()

    donor_id = await resolve_session_user(session_token)
    if donor_id is None:
        return ORJSONResponse({"status": "Unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)

    if not voucher_code or not voucher_code.strip():
        return ORJSONResponse({"status": "Voucher code is required."}, status_code=status.HTTP_400_BAD_REQUEST)
    if message is not None and len(message) > 280:
        return ORJSONResponse({"status": "Message must be at most 280 characters."}, status_code=status.HTTP_400_BAD_REQUEST)

    from app.database import database
    target_id = donor_id if target_user_id is None else int(target_user_id)
    target_row = await database.fetch_one("SELECT id, name FROM users WHERE id = :id", {"id": target_id})
    if target_row is None:
        return ORJSONResponse({"status": "Target user not found."}, status_code=status.HTTP_404_NOT_FOUND)

    from app.adapters import truemoney
    result = await truemoney.redeem_voucher(settings.TRUEMONEY_PHONE, voucher_code)
    provider_reference = hashlib.sha256(voucher_code.strip().encode("utf-8", errors="replace")).hexdigest()

    if result["status"] in ("ERROR", "FAIL"):
        transaction_id = await donations_repo.create(
            provider="truemoney", donor_user_id=donor_id, target_user_id=target_id,
            requested_amount_thb=0, days_requested=0,
            anonymous=bool(anonymous) and target_id != donor_id,
            message=message, provider_reference=provider_reference,
        )
        await donations_repo.mark_failed(
            transaction_id=transaction_id, reviewed_by=None,
            review_note=str(result.get("reason") or "TrueMoney error."),
            decision_source="truemoney_auto",
        )
        http_status = status.HTTP_502_BAD_GATEWAY if result["status"] == "ERROR" else status.HTTP_400_BAD_REQUEST
        return ORJSONResponse(
            {"status": result["status"].lower(), "message": result.get("reason"), "transaction_id": transaction_id},
            status_code=http_status,
        )

    amount_thb = int(result["amount"])
    days_requested = donations_uc.calculate_days(amount_thb)
    transaction_id = await donations_repo.create(
        provider="truemoney", donor_user_id=donor_id, target_user_id=target_id,
        requested_amount_thb=amount_thb, days_requested=days_requested,
        anonymous=bool(anonymous) and target_id != donor_id,
        message=message, provider_reference=provider_reference,
    )
    try:
        transaction = await donations_uc.approve_transaction(
            transaction_id=transaction_id, actor_id=None,
            actual_amount_thb=amount_thb,
            review_note="Automatically redeemed TrueMoney voucher.",
            decision_source="truemoney_auto",
        )
    except Exception as exc:
        return ORJSONResponse(
            {
                "status": "error", "message": _CONTACT_ADMIN_MSG,
                "detail": f"voucher redeemed but grant failed; transaction={transaction_id} err={exc!r}",
                "transaction_id": transaction_id,
            },
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return ORJSONResponse({
        "status": "success",
        "transaction": format_transaction(transaction),
        "transaction_id": transaction_id,
        "amount_thb": transaction["approved_amount_thb"],
        "days_granted": transaction["days_granted"],
        "donor_end": transaction["donor_end"],
    })

    if not settings.TRUEMONEY_ENABLED:
        return ORJSONResponse(
            {"status": "disabled", "message": "TrueMoney donations are currently disabled."},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    token = session or _session_from_header(authorization)
    donor_id = await resolve_session_user(token)
    if donor_id is None:
        return ORJSONResponse({"status": "Unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)

    if not voucher_code or not voucher_code.strip():
        return ORJSONResponse({"status": "Voucher code is required."}, status_code=status.HTTP_400_BAD_REQUEST)
    if message is not None and len(message) > 280:
        return ORJSONResponse({"status": "Message must be at most 280 characters."}, status_code=status.HTTP_400_BAD_REQUEST)

    from app.database import database
    target_id = donor_id if target_user_id is None else int(target_user_id)
    target_row = await database.fetch_one("SELECT id, name FROM users WHERE id = :id", {"id": target_id})
    if target_row is None:
        return ORJSONResponse({"status": "Target user not found."}, status_code=status.HTTP_404_NOT_FOUND)

    from app.adapters import truemoney
    result = await truemoney.redeem_voucher(settings.TRUEMONEY_PHONE, voucher_code)
    provider_reference = hashlib.sha256(voucher_code.strip().encode("utf-8", errors="replace")).hexdigest()

    if result["status"] in ("ERROR", "FAIL"):
        transaction_id = await donations_repo.create(
            provider="truemoney", donor_user_id=donor_id, target_user_id=target_id,
            requested_amount_thb=0, days_requested=0,
            anonymous=bool(anonymous) and target_id != donor_id,
            message=message, provider_reference=provider_reference,
        )
        await donations_repo.mark_failed(
            transaction_id=transaction_id, reviewed_by=None,
            review_note=str(result.get("reason") or "TrueMoney error."),
            decision_source="truemoney_auto",
        )
        http_status = status.HTTP_502_BAD_GATEWAY if result["status"] == "ERROR" else status.HTTP_400_BAD_REQUEST
        return ORJSONResponse(
            {"status": result["status"].lower(), "message": result.get("reason"), "transaction_id": transaction_id},
            status_code=http_status,
        )

    amount_thb = int(result["amount"])
    days_requested = donations_uc.calculate_days(amount_thb)
    transaction_id = await donations_repo.create(
        provider="truemoney", donor_user_id=donor_id, target_user_id=target_id,
        requested_amount_thb=amount_thb, days_requested=days_requested,
        anonymous=bool(anonymous) and target_id != donor_id,
        message=message, provider_reference=provider_reference,
    )
    try:
        transaction = await donations_uc.approve_transaction(
            transaction_id=transaction_id, actor_id=None,
            actual_amount_thb=amount_thb,
            review_note="Automatically redeemed TrueMoney voucher.",
            decision_source="truemoney_auto",
        )
    except Exception as exc:
        return ORJSONResponse(
            {
                "status": "error", "message": _CONTACT_ADMIN_MSG,
                "detail": f"voucher redeemed but grant failed; transaction={transaction_id} err={exc!r}",
                "transaction_id": transaction_id,
            },
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return ORJSONResponse({
        "status": "success",
        "transaction": format_transaction(transaction),
        "transaction_id": transaction_id,
        "amount_thb": transaction["approved_amount_thb"],
        "days_granted": transaction["days_granted"],
        "donor_end": transaction["donor_end"],
    })
