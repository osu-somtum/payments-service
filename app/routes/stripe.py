"""Stripe Checkout + webhook routes."""
from __future__ import annotations

import stripe as stripe_lib
from fastapi import APIRouter, Body, Request
from fastapi.responses import ORJSONResponse
from starlette import status

from app import settings
from app.adapters import stripe as stripe_adapter
from app.auth import resolve_session_user
from app.database import database
from app.repositories import donations as donations_repo
from app.usecases import donations as donations_uc
from app.webhooks import format_transaction

router = APIRouter()

_DOMAIN = f"https://payment.{settings.DOMAIN}"


@router.post("/donate/stripe/checkout")
async def stripe_checkout(
    request: Request,
    amount_thb: float = Body(..., gt=0, embed=True),
    target_user_id: int | None = Body(default=None, embed=True),
    anonymous: bool = Body(default=False, embed=True),
    message: str | None = Body(default=None, embed=True),
) -> ORJSONResponse:
    if not settings.STRIPE_ENABLED:
        return ORJSONResponse(
            {"status": "disabled", "message": "Stripe is not configured."},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    session_token = request.cookies.get("session")
    if not session_token:
        auth = request.headers.get("authorization", "")
        scheme, _, value = auth.partition(" ")
        if scheme.lower() == "bearer" and value:
            session_token = value.strip()

    donor_id = await resolve_session_user(session_token)
    if donor_id is None:
        return ORJSONResponse({"status": "Unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)

    try:
        donations_uc.validate_amount(amount_thb, required_message="Amount is required.")
    except donations_uc.DonationError as exc:
        return ORJSONResponse({"status": str(exc)}, status_code=status.HTTP_400_BAD_REQUEST)

    if message is not None and len(message) > 280:
        return ORJSONResponse({"status": "Message must be at most 280 characters."}, status_code=status.HTTP_400_BAD_REQUEST)

    target_id = donor_id if target_user_id is None else int(target_user_id)
    target_row = await database.fetch_one("SELECT id, name FROM users WHERE id = :id", {"id": target_id})
    if target_row is None:
        return ORJSONResponse({"status": "Target user not found."}, status_code=status.HTTP_404_NOT_FOUND)

    try:
        result = await stripe_adapter.create_checkout_session(
            amount_thb=amount_thb,
            donor_user_id=donor_id,
            target_user_id=target_id,
            target_name=str(target_row["name"]),
            success_url=f"https://{settings.DOMAIN}/donate?stripe=success&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"https://{settings.DOMAIN}/donate",
        )
    except Exception as exc:
        print(f"[stripe] create_checkout_session failed: {exc!r}", flush=True)
        return ORJSONResponse(
            {"status": "error", "message": f"Failed to create Stripe session: {exc}"},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    # Store metadata on the pending transaction so we can match it on webhook
    days_requested = donations_uc.calculate_days(amount_thb)
    await donations_repo.create(
        provider="stripe",
        donor_user_id=donor_id,
        target_user_id=target_id,
        requested_amount_thb=amount_thb,
        days_requested=days_requested,
        status="pending",
        anonymous=bool(anonymous) and target_id != donor_id,
        message=message,
        provider_reference=result["session_id"],
    )

    return ORJSONResponse({"status": "ok", "url": result["url"], "session_id": result["session_id"]})


@router.post("/donate/stripe/webhook")
async def stripe_webhook(request: Request) -> ORJSONResponse:
    """Stripe sends checkout.session.completed here when payment succeeds."""
    if not settings.STRIPE_ENABLED:
        return ORJSONResponse({"status": "disabled"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if not settings.STRIPE_WEBHOOK_SECRET:
        return ORJSONResponse({"status": "webhook secret not configured"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe_adapter.construct_webhook_event(payload, sig_header)
    except stripe_lib.SignatureVerificationError:
        return ORJSONResponse({"status": "invalid signature"}, status_code=status.HTTP_400_BAD_REQUEST)

    if event["type"] == "checkout.session.expired":
        session_obj = event["data"]["object"]
        row = await database.fetch_one(
            "SELECT id FROM donation_transactions WHERE provider = 'stripe' AND provider_reference = :ref AND status = 'pending'",
            {"ref": session_obj["id"]},
        )
        if row:
            await donations_repo.mark_failed(
                transaction_id=int(row["id"]),
                reviewed_by=None,
                review_note="Stripe checkout session expired.",
                decision_source="stripe_auto",
            )
        return ORJSONResponse({"status": "ok"})

    if event["type"] != "checkout.session.completed":
        return ORJSONResponse({"status": "ignored"})

    session_obj = event["data"]["object"]
    stripe_session_id: str = session_obj["id"]
    metadata: dict = session_obj.get("metadata") or {}

    # Match the pending transaction we created in /checkout
    row = await database.fetch_one(
        "SELECT id FROM donation_transactions WHERE provider = 'stripe' AND provider_reference = :ref AND status = 'pending'",
        {"ref": stripe_session_id},
    )
    if row is None:
        # Not found — idempotent, Stripe may retry
        return ORJSONResponse({"status": "not_found"}, status_code=status.HTTP_404_NOT_FOUND)

    transaction_id = int(row["id"])
    amount_thb = float(metadata.get("amount_thb") or session_obj.get("amount_total", 0) / 100)
    print(f"[webhook] approving transaction_id={transaction_id} amount_thb={amount_thb}", flush=True)

    try:
        await donations_uc.approve_transaction(
            transaction_id=transaction_id,
            actor_id=None,
            actual_amount_thb=amount_thb,
            review_note="Stripe payment confirmed.",
            decision_source="stripe_auto",
        )
        print(f"[webhook] approved transaction_id={transaction_id} ok", flush=True)
    except donations_uc.DonationError as exc:
        print(f"[webhook] DonationError transaction_id={transaction_id}: {exc!r}", flush=True)
        return ORJSONResponse({"status": "skipped", "reason": str(exc)})
    except Exception as exc:
        print(f"[webhook] unexpected error transaction_id={transaction_id}: {exc!r}", flush=True)
        raise

    return ORJSONResponse({"status": "ok"})
