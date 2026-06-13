"""Business logic for donation transactions.

grant_donator calls bancho.py's /internal/grant_donator endpoint instead of
writing to users directly — bancho.py owns in-memory player state.
"""
from __future__ import annotations

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


async def grant_donator(target_user_id: int, days: float) -> int:
    """Call bancho.py's internal endpoint to extend donor_end and sync in-memory state."""
    if days <= 0:
        raise DonationError("days must be greater than zero")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{settings.BANCHO_INTERNAL_URL}/internal/grant_donator",
            json={"target_user_id": target_user_id, "days": days},
            headers={"X-Internal-Token": settings.BANCHO_INTERNAL_TOKEN},
        )
    if resp.status_code != 200:
        raise DonationError(f"grant_donator failed: {resp.text[:200]}")
    return int(resp.json()["donor_end"])


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
    donor_end = await grant_donator(int(transaction["target_user_id"]), days)

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
