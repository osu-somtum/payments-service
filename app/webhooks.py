"""Shared Discord webhook helpers for donation notifications."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from app import settings


def _donation_slip_url(slip_token: str | None) -> str | None:
    if not slip_token:
        return None
    return f"https://payment.{settings.DOMAIN}/donate/promptpay/slip/{slip_token}"


def format_transaction(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "provider": row["provider"],
        "status": row["status"],
        "donor_user_id": row["donor_user_id"],
        "donor_name": row["donor_name"],
        "target_user_id": row["target_user_id"],
        "target_name": row["target_name"],
        "requested_amount_thb": row["requested_amount_thb"],
        "approved_amount_thb": row["approved_amount_thb"],
        "days_requested": row["days_requested"],
        "days_granted": row["days_granted"],
        "donor_end": row["donor_end"],
        "anonymous": row["anonymous"],
        "message": row["message"],
        "provider_reference": row["provider_reference"],
        "slip_url": _donation_slip_url(row["slip_token"]),
        "reviewed_by": row["reviewed_by"],
        "reviewed_by_name": row["reviewed_by_name"],
        "reviewed_at": row["reviewed_at"],
        "review_note": row["review_note"],
        "decision_source": row["decision_source"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def _post_webhook(url: str, embeds: list[dict[str, Any]]) -> None:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(url, json={"embeds": embeds})
    except Exception:
        pass


async def notify_submission(transaction: dict[str, Any]) -> None:
    if not settings.DISCORD_DONATION_WEBHOOK:
        return
    slip_url = _donation_slip_url(transaction.get("slip_token"))
    embed: dict[str, Any] = {
        "title": "PromptPay Donation Pending Review",
        "color": 0x00AEEF,
        "timestamp": datetime.utcnow().isoformat(),
        "fields": [
            {"name": "Request ID", "value": str(transaction["id"]), "inline": True},
            {"name": "Donor", "value": f"{transaction['donor_name']} (#{transaction['donor_user_id']})", "inline": True},
            {"name": "Recipient", "value": f"{transaction['target_name']} (#{transaction['target_user_id']})", "inline": True},
            {"name": "Amount", "value": f"{transaction['requested_amount_thb']:.2f} THB", "inline": True},
            {"name": "Days", "value": f"{transaction['days_requested']:.2f}", "inline": True},
            {
                "name": "Discord Commands",
                "value": (
                    f"`/staff-donation-approve request_id:{transaction['id']}`\n"
                    f"`/staff-donation-reject request_id:{transaction['id']} reason:<reason>`"
                ),
                "inline": False,
            },
        ],
    }
    if transaction.get("message"):
        embed["fields"].append({"name": "Message", "value": str(transaction["message"])[:1024], "inline": False})
    if slip_url:
        embed["image"] = {"url": slip_url}
    await _post_webhook(settings.DISCORD_DONATION_WEBHOOK, [embed])


async def notify_review(transaction: dict[str, Any], *, action: str, actor_name: str | None) -> None:
    url = settings.DISCORD_DONATION_WEBHOOK or settings.DISCORD_AUDIT_LOG_WEBHOOK
    if not url:
        return
    color = 0x22C55E if action == "approved" else 0xEF4444
    fields: list[dict[str, Any]] = [
        {"name": "Request ID", "value": str(transaction["id"]), "inline": True},
        {"name": "Provider", "value": str(transaction["provider"]), "inline": True},
        {"name": "Status", "value": str(transaction["status"]), "inline": True},
        {"name": "Donor", "value": f"{transaction['donor_name']} (#{transaction['donor_user_id']})", "inline": True},
        {"name": "Recipient", "value": f"{transaction['target_name']} (#{transaction['target_user_id']})", "inline": True},
    ]
    if transaction.get("approved_amount_thb") is not None:
        fields.append({"name": "Approved Amount", "value": f"{transaction['approved_amount_thb']:.2f} THB", "inline": True})
    if transaction.get("days_granted") is not None:
        fields.append({"name": "Days Granted", "value": f"{transaction['days_granted']:.2f}", "inline": True})
    if actor_name:
        fields.append({"name": "Reviewed By", "value": actor_name, "inline": True})
    if transaction.get("review_note"):
        fields.append({"name": "Review Note", "value": str(transaction["review_note"])[:1024], "inline": False})
    await _post_webhook(url, [{"title": f"Donation {action.title()}", "color": color, "timestamp": datetime.utcnow().isoformat(), "fields": fields}])
