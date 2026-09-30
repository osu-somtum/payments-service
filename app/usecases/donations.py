"""Business logic for donation transactions.

grant_donator calls bancho.py's /internal/grant_donator endpoint instead of
writing to users directly — bancho.py owns in-memory player state. With
PAYMENTS_BACKEND=osu-web it asks osu-web (its InterOp API) to add osu!supporter.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

import httpx

from app import settings
from app.repositories import donations as donations_repo

DONATION_DECIMAL_MAX = Decimal("99999999.99")


class DonationError(ValueError):
    pass


def calculate_days(amount_thb: float) -> float:
    return round(float(amount_thb) * settings.DONATION_DAYS_PER_THB, 2)


def validate_amount(amount_thb: float | str, *, required_message: str) -> float:
    try:
        amount = Decimal(str(amount_thb).strip())
    except InvalidOperation as exc:
        raise DonationError(required_message) from exc
    if not amount.is_finite():
        raise DonationError(required_message)
    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount <= 0:
        raise DonationError("Donation amount must be greater than zero.")
    if amount > DONATION_DECIMAL_MAX:
        raise DonationError("Donation amount is too large.")
    if Decimal(str(calculate_days(float(amount)))) > DONATION_DECIMAL_MAX:
        raise DonationError("Donation amount is too large.")
    return float(amount)


async def grant_donator(
    target_user_id: int,
    days: float,
    *,
    donor_user_id: int | None = None,
    transaction_id: int | None = None,
) -> int:
    """Extend the player's donator/supporter time; returns when it now ends (unix time)."""
    if days <= 0:
        raise DonationError("days must be greater than zero")
    if settings.IS_OSU_WEB:
        return await _grant_osu_web_supporter(target_user_id, days, donor_user_id, transaction_id)

    # bancho.py: its internal endpoint extends donor_end and syncs in-memory state.
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{settings.BANCHO_INTERNAL_URL}/internal/grant_donator",
            json={"target_user_id": target_user_id, "days": days},
            headers={"X-Internal-Token": settings.BANCHO_INTERNAL_TOKEN},
        )
    if resp.status_code != 200:
        raise DonationError(f"grant_donator failed: {resp.text[:200]}")
    return int(resp.json()["donor_end"])


async def osu_web_interop(path: str, body: dict[str, Any]) -> httpx.Response:
    """POST to osu-web's InterOp API (/_lio/...), signed like its LegacyInterOpAuth expects
    (HMAC-SHA1 of the full URL, with a timestamp, in X-LIO-Signature)."""
    url = f"{settings.OSU_WEB_INTERNAL_URL}/_lio/{path}?timestamp={int(time.time())}"
    signature = hmac.new(settings.OSU_WEB_INTEROP_SECRET.encode(), url.encode(), hashlib.sha1).hexdigest()
    async with httpx.AsyncClient(timeout=30.0) as client:
        return await client.post(url, json=body, headers={"X-LIO-Signature": signature, "Accept": "application/json"})


async def _grant_osu_web_supporter(
    target_user_id: int, days: float, donor_user_id: int | None, transaction_id: int | None,
) -> int:
    """osu-web: add supporter time directly (POST /_lio/tomyum/grant-supporter)."""
    resp = await osu_web_interop("tomyum/grant-supporter", {
        "target_user_id": target_user_id,
        "days": days,
        "donor_user_id": donor_user_id,
        "transaction_id": transaction_id,
    })
    if resp.status_code != 200:
        raise DonationError(f"grant-supporter failed ({resp.status_code}): {resp.text[:200]}")
    return int(resp.json()["donor_end"])


async def mark_store_order_paid(*, order_id: int, provider: str, reference: str, amount_thb: float) -> None:
    """osu-web: a store order was paid; it fulfils it (POST /_lio/tomyum/store-order-paid).
    Safe to repeat: an order already paid only answers."""
    resp = await osu_web_interop("tomyum/store-order-paid", {
        "order_id": order_id,
        "provider": provider,
        "transaction_id": reference,
        "amount_thb": amount_thb,
    })
    if resp.status_code != 200:
        raise DonationError(f"store-order-paid failed ({resp.status_code}): {resp.text[:200]}")


async def approve_transaction(
    *,
    transaction_id: int,
    actor_id: int | None,
    actual_amount_thb: float | None,
    review_note: str | None,
    decision_source: str,
) -> dict[str, Any]:
    transaction = await donations_repo.fetch_one(transaction_id)
    if transaction is None:
        raise DonationError("Donation transaction not found.")
    if transaction["status"] != "pending":
        raise DonationError("Donation transaction has already been reviewed.")

    amount = validate_amount(
        actual_amount_thb if actual_amount_thb is not None else transaction["requested_amount_thb"],
        required_message="Approved amount is required.",
    )
    days = calculate_days(amount)
    donor_end = await grant_donator(
        int(transaction["target_user_id"]),
        days,
        donor_user_id=int(transaction["donor_user_id"]),
        transaction_id=transaction_id,
    )

    await donations_repo.mark_success(
        transaction_id=transaction_id,
        approved_amount_thb=amount,
        days_granted=days,
        donor_end=donor_end,
        reviewed_by=actor_id,
        review_note=review_note,
        decision_source=decision_source,
    )
    updated = await donations_repo.fetch_one(transaction_id)
    if updated is None:
        raise DonationError("Donation transaction disappeared after approval.")
    await _record_success_activity(updated)
    return updated


async def _record_success_activity(transaction: dict[str, Any]) -> None:
    # bancho.py's player_activity feed; osu-web records supporter gifts and purchases itself.
    if settings.IS_OSU_WEB:
        return
    donor_id = int(transaction["donor_user_id"])
    target_id = int(transaction["target_user_id"])
    is_self = donor_id == target_id
    anonymous = bool(transaction["anonymous"]) and not is_self
    base = {
        "amount_thb": transaction["approved_amount_thb"],
        "days_granted": transaction["days_granted"],
        "donor_end": transaction["donor_end"],
        "message": transaction["message"],
        "provider": transaction["provider"],
        "transaction_id": transaction["id"],
    }
    from app.database import database
    try:
        await database.execute(
            "INSERT INTO player_activity (user_id, kind, payload, is_public, created_at) "
            "VALUES (:uid, :kind, :payload, :public, NOW())",
            {
                "uid": donor_id,
                "kind": "donate_self" if is_self else "donate_other",
                "payload": __import__("json").dumps({**base, "target_user_id": target_id, "target_name": transaction["target_name"], "anonymous": anonymous}),
                "public": 0 if anonymous else 1,
            },
        )
    except Exception:
        pass
    if not is_self:
        try:
            await database.execute(
                "INSERT INTO player_activity (user_id, kind, payload, is_public, created_at) "
                "VALUES (:uid, :kind, :payload, :public, NOW())",
                {
                    "uid": target_id,
                    "kind": "received_donation",
                    "payload": __import__("json").dumps({**base, "donor_user_id": None if anonymous else donor_id, "donor_name": None if anonymous else transaction["donor_name"], "anonymous": anonymous}),
                    "public": 1,
                },
            )
        except Exception:
            pass


async def reject_transaction(
    *,
    transaction_id: int,
    actor_id: int | None,
    review_note: str | None,
    decision_source: str,
) -> dict[str, Any]:
    transaction = await donations_repo.fetch_one(transaction_id)
    if transaction is None:
        raise DonationError("Donation transaction not found.")
    if transaction["status"] != "pending":
        raise DonationError("Donation transaction has already been reviewed.")

    await donations_repo.mark_failed(
        transaction_id=transaction_id,
        reviewed_by=actor_id,
        review_note=review_note,
        decision_source=decision_source,
    )
    updated = await donations_repo.fetch_one(transaction_id)
    if updated is None:
        raise DonationError("Donation transaction disappeared after rejection.")
    return updated
