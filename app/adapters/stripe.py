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


async def create_store_checkout(
    *,
    amount_thb: float,
    charge_currency: str | None = None,
    charge_amount: float | None = None,
    order_id: int,
    user_id: int,
    description: str,
    success_url: str,
    cancel_url: str,
) -> dict[str, Any]:
    """A Checkout session for an osu-web store order (PAYMENTS_BACKEND=osu-web): the order's total,
    named after what's in it; its id travels in the metadata to the webhook. osu-web says what the
    player was shown (charge_currency/charge_amount: baht in Thailand, US$ elsewhere); without it,
    STRIPE_CURRENCY as for donations."""
    stripe.api_key = settings.STRIPE_SECRET_KEY

    if charge_currency is not None and charge_amount is not None:
        currency = charge_currency
        unit_amount = int(round(charge_amount * 100))  # satang / cents
    elif settings.STRIPE_CURRENCY == "usd":
        currency = "usd"
        unit_amount = int(round(amount_thb * settings.STRIPE_THB_TO_USD_RATE * 100))
    else:
        currency = "thb"
        unit_amount = int(round(amount_thb * 100))

    session = stripe.checkout.Session.create(
        mode="payment",
        currency=currency,
        line_items=[
            {
                "quantity": 1,
                "price_data": {
                    "currency": currency,
                    "unit_amount": unit_amount,
                    "product_data": {"name": (description or f"Store order #{order_id}")[:250]},
                },
            }
        ],
        client_reference_id=str(order_id),
        metadata={
            "store_order_id": str(order_id),
            "donor_user_id": str(user_id),
            "target_user_id": str(user_id),
            "amount_thb": str(amount_thb),
        },
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return {"session_id": session.id, "url": session.url}
