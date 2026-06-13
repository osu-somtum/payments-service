"""Persistence helpers for donation_transactions — moved from bancho.py."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from app.database import database


def _amount(value: Any) -> float | None:
    if value is None:
        return None
    return float(value) if isinstance(value, Decimal) else float(value)


def _decode_row(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "provider": row["provider"],
        "status": row["status"],
        "donor_user_id": int(row["donor_user_id"]),
        "donor_name": row["donor_name"],
        "target_user_id": int(row["target_user_id"]),
        "target_name": row["target_name"],
        "requested_amount_thb": _amount(row["requested_amount_thb"]) or 0.0,
        "approved_amount_thb": _amount(row["approved_amount_thb"]),
        "days_requested": _amount(row["days_requested"]) or 0.0,
        "days_granted": _amount(row["days_granted"]),
        "donor_end": row["donor_end"],
        "anonymous": bool(row["anonymous"]),
        "message": row["message"],
        "provider_reference": row["provider_reference"],
        "slip_path": row["slip_path"],
        "slip_token": row["slip_token"],
        "reviewed_by": row["reviewed_by"],
        "reviewed_by_name": row["reviewed_by_name"],
        "reviewed_at": row["reviewed_at"],
        "review_note": row["review_note"],
        "decision_source": row["decision_source"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


_SELECT_JOINED = """
    SELECT dt.*,
           donor.name  AS donor_name,
           target.name AS target_name,
           reviewer.name AS reviewed_by_name
    FROM donation_transactions dt
    INNER JOIN users donor  ON donor.id  = dt.donor_user_id
    INNER JOIN users target ON target.id = dt.target_user_id
    LEFT  JOIN users reviewer ON reviewer.id = dt.reviewed_by
"""


async def create(
    *,
    provider: str,
    donor_user_id: int,
    target_user_id: int,
    requested_amount_thb: float,
    days_requested: float,
    status: str = "pending",
    anonymous: bool = False,
    message: str | None = None,
    provider_reference: str | None = None,
    slip_path: str | None = None,
    slip_token: str | None = None,
) -> int:
    return await database.execute(
        """
        INSERT INTO donation_transactions
            (provider, status, donor_user_id, target_user_id,
             requested_amount_thb, days_requested, anonymous, message,
             provider_reference, slip_path, slip_token)
        VALUES
            (:provider, :status, :donor_user_id, :target_user_id,
             :requested_amount_thb, :days_requested, :anonymous, :message,
             :provider_reference, :slip_path, :slip_token)
        """,
        {
            "provider": provider, "status": status,
            "donor_user_id": donor_user_id, "target_user_id": target_user_id,
            "requested_amount_thb": requested_amount_thb, "days_requested": days_requested,
            "anonymous": 1 if anonymous else 0, "message": message,
            "provider_reference": provider_reference, "slip_path": slip_path,
            "slip_token": slip_token,
        },
    )


async def fetch_one(transaction_id: int) -> dict[str, Any] | None:
    row = await database.fetch_one(
        _SELECT_JOINED + " WHERE dt.id = :id", {"id": transaction_id}
    )
    return _decode_row(row) if row is not None else None


async def fetch_by_slip_token(slip_token: str) -> dict[str, Any] | None:
    row = await database.fetch_one(
        _SELECT_JOINED + " WHERE dt.slip_token = :slip_token", {"slip_token": slip_token}
    )
    return _decode_row(row) if row is not None else None


async def fetch_many(
    *,
    status: str | None = None,
    provider: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    clauses: list[str] = []
    filter_params: dict[str, Any] = {}
    if status:
        clauses.append("dt.status = :status")
        filter_params["status"] = status
    if provider:
        clauses.append("dt.provider = :provider")
        filter_params["provider"] = provider

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    total = await database.fetch_val(
        f"SELECT COUNT(*) FROM donation_transactions dt {where}", filter_params
    )
    page_params = {**filter_params, "limit": max(1, min(limit, 100)), "offset": max(0, offset)}
    rows = await database.fetch_all(
        f"{_SELECT_JOINED} {where} ORDER BY dt.id DESC LIMIT :limit OFFSET :offset",
        page_params,
    )
    return [_decode_row(row) for row in rows], int(total or 0)


async def mark_success(
    *,
    transaction_id: int,
    approved_amount_thb: float,
    days_granted: float,
    donor_end: int,
    reviewed_by: int | None,
    review_note: str | None,
    decision_source: str,
) -> None:
    reviewed_at = datetime.utcnow() if reviewed_by is not None else None
    await database.execute(
        """
        UPDATE donation_transactions
        SET status = 'success',
            approved_amount_thb = :approved_amount_thb,
            days_granted        = :days_granted,
            donor_end           = :donor_end,
            reviewed_by         = :reviewed_by,
            reviewed_at         = COALESCE(:reviewed_at, reviewed_at),
            review_note         = :review_note,
            decision_source     = :decision_source
        WHERE id = :id
        """,
        {
            "id": transaction_id, "approved_amount_thb": approved_amount_thb,
            "days_granted": days_granted, "donor_end": donor_end,
            "reviewed_by": reviewed_by, "reviewed_at": reviewed_at,
            "review_note": review_note, "decision_source": decision_source,
        },
    )


async def mark_failed(
    *,
    transaction_id: int,
    reviewed_by: int | None,
    review_note: str | None,
    decision_source: str,
) -> None:
    reviewed_at = datetime.utcnow() if reviewed_by is not None else None
    await database.execute(
        """
        UPDATE donation_transactions
        SET status          = 'failed',
            reviewed_by     = :reviewed_by,
            reviewed_at     = COALESCE(:reviewed_at, reviewed_at),
            review_note     = :review_note,
            decision_source = :decision_source
        WHERE id = :id
        """,
        {
            "id": transaction_id, "reviewed_by": reviewed_by,
            "reviewed_at": reviewed_at, "review_note": review_note,
            "decision_source": decision_source,
        },
    )
