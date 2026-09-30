"""osu-web store orders (PAYMENTS_BACKEND=osu-web): paying an osu!store order with TrueMoney or Stripe.

osu-web forwards the player's checkout here (X-Internal-Token + X-User-Id) with the order and its
total; once paid, this tells osu-web (InterOp store-order-paid), which fulfils the order as usual.
"""
from __future__ import annotations

import asyncio
import hashlib

import stripe as stripe_lib
from fastapi import APIRouter, Body
from fastapi.responses import ORJSONResponse
from starlette import status
from starlette.requests import Request

from app import settings
from app.adapters import stripe as stripe_adapter
from app.adapters import truemoney
from app.auth import request_user
from app.database import database
from app.repositories import donations as donations_repo
from app.usecases import donations as donations_uc

router = APIRouter()

_CONTACT_ADMIN_MSG = (
    "Your payment went through, but the order couldn't be completed. Please contact an administrator "
    "with order #{order_id}."
)


def _baht(amount: float) -> str:
    return f"฿{amount:,.2f}".replace(".00", "")


async def _order_payment(request: Request, order_id: int, amount_thb: float) -> tuple[int | None, ORJSONResponse | None]:
    """(the paying player, None) or (None, the refusal)."""
    user_id = await request_user(request)
    if user_id is None:
        return None, ORJSONResponse({"status": "Unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        donations_uc.validate_amount(amount_thb, required_message="The order has no total.")
    except donations_uc.DonationError as exc:
        return None, ORJSONResponse({"status": "error", "message": str(exc)}, status_code=status.HTTP_400_BAD_REQUEST)
    if order_id <= 0:
        return None, ORJSONResponse({"status": "error", "message": "No order."}, status_code=status.HTTP_400_BAD_REQUEST)
    return user_id, None


@router.post("/store/truemoney/redeem")
async def store_truemoney_redeem(
    request: Request,
    order_id: int = Body(..., embed=True),
    amount_thb: float = Body(..., embed=True),
    voucher_code: str = Body(..., embed=True),
    description: str | None = Body(default=None, embed=True),
) -> ORJSONResponse:
    if not settings.TRUEMONEY_ENABLED:
        return ORJSONResponse(
            {"status": "disabled", "message": "TrueMoney payments are currently disabled."},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    user_id, refusal = await _order_payment(request, order_id, amount_thb)
    if refusal is not None:
        return refusal

    # A voucher is only redeemed when it's worth exactly the order's total: checked first, so a
    # wrong one is refused without taking anything from it.
    checked = await truemoney.verify_voucher(settings.TRUEMONEY_PHONE, voucher_code)
    if checked["status"] != "SUCCESS":
        http_status = status.HTTP_502_BAD_GATEWAY if checked["status"] == "ERROR" else status.HTTP_400_BAD_REQUEST
        message = "TrueMoney couldn't be reached. Please try again." if checked["status"] == "ERROR" else checked["reason"]
        return ORJSONResponse({"status": "fail", "message": message}, status_code=http_status)
    if round(checked["amount"], 2) != round(amount_thb, 2):
        return ORJSONResponse({
            "status": "fail",
            "message": f"This voucher is for {_baht(checked['amount'])}, but the order is {_baht(amount_thb)}. "
                       f"Make a voucher for exactly {_baht(amount_thb)}.",
        }, status_code=status.HTTP_400_BAD_REQUEST)

    reference = hashlib.sha256(voucher_code.strip().encode("utf-8", errors="replace")).hexdigest()
    transaction_id = await donations_repo.create(
        provider="truemoney", donor_user_id=user_id, target_user_id=user_id,
        requested_amount_thb=amount_thb, days_requested=0,
        message=description, provider_reference=reference, store_order_id=order_id,
    )
    redeemed = await truemoney.redeem_voucher(settings.TRUEMONEY_PHONE, voucher_code)
    if redeemed["status"] != "SUCCESS":
        await donations_repo.mark_failed(
            transaction_id=transaction_id, reviewed_by=None,
            review_note=str(redeemed.get("reason") or "TrueMoney error."), decision_source="truemoney_auto",
        )
        return ORJSONResponse({"status": "fail", "message": redeemed.get("reason")}, status_code=status.HTTP_400_BAD_REQUEST)

    await donations_repo.mark_success(
        transaction_id=transaction_id, approved_amount_thb=float(redeemed["amount"]), days_granted=0,
        donor_end=0, reviewed_by=None, review_note=f"Store order #{order_id}.", decision_source="truemoney_auto",
    )
    if float(redeemed["amount"]) != amount_thb:
        # Changed between checking and redeeming: the money is in, but not what the order costs.
        return ORJSONResponse(
            {"status": "error", "message": _CONTACT_ADMIN_MSG.format(order_id=order_id)},
            status_code=status.HTTP_409_CONFLICT,
        )
    try:
        await donations_uc.mark_store_order_paid(
            order_id=order_id, provider="truemoney", reference=reference, amount_thb=amount_thb,
        )
    except Exception as exc:
        print(f"[store] truemoney paid but order {order_id} not completed (tx {transaction_id}): {exc!r}", flush=True)
        return ORJSONResponse(
            {"status": "error", "message": _CONTACT_ADMIN_MSG.format(order_id=order_id)},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return ORJSONResponse({"status": "success", "transaction_id": transaction_id})


@router.post("/store/stripe/checkout")
async def store_stripe_checkout(
    request: Request,
    order_id: int = Body(..., embed=True),
    amount_thb: float = Body(..., embed=True),
    success_url: str = Body(..., embed=True),
    cancel_url: str = Body(..., embed=True),
    description: str | None = Body(default=None, embed=True),
    charge_currency: str | None = Body(default=None, embed=True),
    charge_amount: float | None = Body(default=None, embed=True),
) -> ORJSONResponse:
    if not settings.STRIPE_ENABLED:
        return ORJSONResponse(
            {"status": "disabled", "message": "Card payments are not available right now."},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    user_id, refusal = await _order_payment(request, order_id, amount_thb)
    if refusal is not None:
        return refusal
    # What the player was shown: baht, or (outside Thailand) US$.
    if charge_currency is not None and (charge_currency not in {"thb", "usd"} or not charge_amount or charge_amount <= 0):
        return ORJSONResponse({"status": "error", "message": "Unknown currency."}, status_code=status.HTTP_400_BAD_REQUEST)

    try:
        result = await stripe_adapter.create_store_checkout(
            amount_thb=amount_thb, charge_currency=charge_currency, charge_amount=charge_amount,
            order_id=order_id, user_id=user_id,
            description=description or "", success_url=success_url, cancel_url=cancel_url,
        )
    except Exception as exc:
        print(f"[stripe] create_store_checkout failed: {exc!r}", flush=True)
        return ORJSONResponse(
            {"status": "error", "message": "Card payments are not available right now."},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    await donations_repo.create(
        provider="stripe", donor_user_id=user_id, target_user_id=user_id,
        requested_amount_thb=amount_thb, days_requested=0, status="pending",
        message=description, provider_reference=result["session_id"], store_order_id=order_id,
    )
    return ORJSONResponse({"status": "ok", "url": result["url"], "session_id": result["session_id"]})


async def sync_stripe_orders(order_id: int | None = None) -> list[int]:
    """Asks Stripe about card payments for store orders still pending (one order's, or the last two
    days'), and completes the ones it says are paid, as the webhook would. A safety net for a webhook
    that didn't arrive (the service restarting, a network error): returns the orders completed."""
    if not settings.STRIPE_ENABLED:
        return []
    query = (
        "SELECT id, store_order_id, provider_reference FROM donation_transactions "
        "WHERE provider = 'stripe' AND status = 'pending' AND store_order_id IS NOT NULL "
    )
    if order_id is not None:
        rows = await database.fetch_all(query + "AND store_order_id = :order_id", {"order_id": order_id})
    else:
        rows = await database.fetch_all(query + "AND created_at > NOW() - INTERVAL 2 DAY")

    stripe_lib.api_key = settings.STRIPE_SECRET_KEY
    completed = []
    for row in rows:
        session = await asyncio.to_thread(stripe_lib.checkout.Session.retrieve, row["provider_reference"])
        if session.status != "complete" or session.payment_status != "paid":
            continue
        amount = float(session.metadata.get("amount_thb") or session.amount_total / 100)
        await donations_uc.mark_store_order_paid(
            order_id=int(row["store_order_id"]), provider="stripe", reference=session.id, amount_thb=amount,
        )
        await donations_repo.mark_success(
            transaction_id=int(row["id"]), approved_amount_thb=amount, days_granted=0, donor_end=0, reviewed_by=None,
            review_note=f"Store order #{row['store_order_id']} (confirmed with Stripe).", decision_source="stripe_sync",
        )
        completed.append(int(row["store_order_id"]))
    return completed


async def sweep_stripe_orders(interval_seconds: float = 120) -> None:
    """Every couple of minutes, sync_stripe_orders() for everything pending."""
    while True:
        try:
            completed = await sync_stripe_orders()
            if completed:
                print(f"[stripe-sync] completed orders {completed} (their webhook hadn't arrived)", flush=True)
        except Exception as exc:
            print(f"[stripe-sync] failed: {exc!r}", flush=True)
        await asyncio.sleep(interval_seconds)


@router.post("/store/stripe/sync")
async def store_stripe_sync(request: Request, order_id: int = Body(..., embed=True)) -> ORJSONResponse:
    """osu-web asks this when the player comes back from Stripe: completes the order now if it's paid."""
    if await request_user(request) is None:
        return ORJSONResponse({"status": "Unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        completed = await sync_stripe_orders(order_id)
    except Exception as exc:
        print(f"[stripe-sync] order {order_id}: {exc!r}", flush=True)
        return ORJSONResponse({"status": "error"}, status_code=status.HTTP_502_BAD_GATEWAY)
    return ORJSONResponse({"status": "paid" if completed else "unchanged"})
