"""Stripe adapter — dynamic pricing via inline price_data."""
from __future__ import annotations

from typing import Any

import stripe

from app import settings


async def create_checkout_session(
    *,
    amount_thb: float,
    donor_user_id: int,
    target_user_id: int,
    target_name: str,
    success_url: str,
    cancel_url: str,
) -> dict[str, Any]:
    stripe.api_key = settings.STRIPE_SECRET_KEY

    currency = settings.STRIPE_CURRENCY
    if currency == "usd":
        charge_amount = int(round(amount_thb * settings.STRIPE_THB_TO_USD_RATE * 100))  # cents
    else:
        charge_amount = int(round(amount_thb * 100))  # satang

    session = stripe.checkout.Session.create(
        mode="payment",
        currency=currency,
        line_items=[
            {
                "quantity": 1,
                "price_data": {
                    "currency": currency,
                    "unit_amount": charge_amount,
                    "product_data": {
                        "name": "Premium Membership",
                        "description": (
                            f"Premium membership for {target_name}. "
                            f"Grants {round(amount_thb * settings.DONATION_DAYS_PER_THB, 2)} days."
                        ),
                    },
                },
            }
        ],
        metadata={
            "donor_user_id": str(donor_user_id),
            "target_user_id": str(target_user_id),
            "amount_thb": str(amount_thb),
        },
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return {"session_id": session.id, "url": session.url}


def construct_webhook_event(payload: bytes, sig_header: str) -> Any:
    return stripe.Webhook.construct_event(
        payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
    )
