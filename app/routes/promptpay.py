"""PromptPay slip submit and serve routes."""
from __future__ import annotations

import io
import secrets
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, ORJSONResponse
from PIL import Image
from starlette import status
from starlette.requests import Request

from app import settings
from app.auth import resolve_session_user
from app.repositories import donations as donations_repo
from app.usecases import donations as donations_uc
from app.webhooks import format_transaction, notify_submission

router = APIRouter()

DONATION_SLIPS_PATH = Path(".data/assets/donations/slips")

_CONTACT_ADMIN_MSG = (
    "ระบบเติมเงินขัดข้อง กรุณาติดต่อแอดมินเพื่อขอความช่วยเหลือ "
    "(payment system error — please contact an administrator)."
)


@router.get("/donate/promptpay/slip/{slip_token}", response_model=None)
async def donate_promptpay_slip(slip_token: str) -> FileResponse | ORJSONResponse:
    transaction = await donations_repo.fetch_by_slip_token(slip_token)
    if transaction is None or not transaction["slip_path"]:
        return ORJSONResponse({"status": "not_found"}, status_code=status.HTTP_404_NOT_FOUND)
    slip_path = Path(str(transaction["slip_path"]))
    if not slip_path.exists() or not slip_path.is_file():
        return ORJSONResponse({"status": "not_found"}, status_code=status.HTTP_404_NOT_FOUND)
    return FileResponse(slip_path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.post("/donate/promptpay/submit")
async def donate_promptpay_submit(request: Request) -> ORJSONResponse:
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
        form = await request.form()
    except Exception:
        return ORJSONResponse({"status": "Invalid multipart form data."}, status_code=status.HTTP_400_BAD_REQUEST)

    amount_raw = str(form.get("requested_amount_thb") or form.get("amount_thb") or "").strip()
    try:
        requested_amount = donations_uc.validate_amount(amount_raw, required_message="Donation amount is required.")
    except donations_uc.DonationError as exc:
        return ORJSONResponse({"status": str(exc)}, status_code=status.HTTP_400_BAD_REQUEST)

    target_raw = str(form.get("target_user_id") or "").strip()
    try:
        target_id = donor_id if not target_raw else int(target_raw)
    except ValueError:
        return ORJSONResponse({"status": "Invalid target user id."}, status_code=status.HTTP_400_BAD_REQUEST)

    from app.database import database
    target_row = await database.fetch_one("SELECT id, name FROM users WHERE id = :id", {"id": target_id})
    if target_row is None:
        return ORJSONResponse({"status": "Target user not found."}, status_code=status.HTTP_404_NOT_FOUND)

    anonymous = str(form.get("anonymous") or "").strip().lower() in {"1", "true", "yes"}
    if target_id == donor_id:
        anonymous = False

    message_raw = form.get("message")
    message = str(message_raw).strip() if message_raw is not None else None
    if message == "":
        message = None
    if message is not None and len(message) > 280:
        return ORJSONResponse({"status": "Message must be at most 280 characters."}, status_code=status.HTTP_400_BAD_REQUEST)

    from starlette.datastructures import UploadFile as _StarletteUploadFile
    upload = form.get("slip")
    if not isinstance(upload, _StarletteUploadFile):
        return ORJSONResponse({"status": "Payment slip image is required."}, status_code=status.HTTP_400_BAD_REQUEST)

    slip_data = await upload.read()
    await upload.close()
    if not slip_data:
        return ORJSONResponse({"status": "Payment slip image is required."}, status_code=status.HTTP_400_BAD_REQUEST)
    if len(slip_data) > settings.PROMPTPAY_SLIP_MAX_BYTES:
        return ORJSONResponse(
            {"status": f"Payment slip image is too large. Limit is {settings.PROMPTPAY_SLIP_MAX_BYTES} bytes."},
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )

    try:
        Image.open(io.BytesIO(slip_data)).verify()
        image = Image.open(io.BytesIO(slip_data))
        image.thumbnail((1800, 1800))
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=92, optimize=True)
        stored_slip = out.getvalue()
    except Exception:
        return ORJSONResponse({"status": "Payment slip must be a valid image."}, status_code=status.HTTP_400_BAD_REQUEST)

    DONATION_SLIPS_PATH.mkdir(parents=True, exist_ok=True)
    slip_token = secrets.token_urlsafe(32)
    slip_path = DONATION_SLIPS_PATH / f"{slip_token}.jpg"
    slip_path.write_bytes(stored_slip)

    days_requested = donations_uc.calculate_days(requested_amount)
    transaction_id = await donations_repo.create(
        provider="promptpay", donor_user_id=donor_id, target_user_id=target_id,
        requested_amount_thb=requested_amount, days_requested=days_requested,
        anonymous=anonymous, message=message,
        slip_path=str(slip_path), slip_token=slip_token,
    )

    transaction = await donations_repo.fetch_one(transaction_id)
    if transaction is None:
        return ORJSONResponse({"status": _CONTACT_ADMIN_MSG}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    try:
        await notify_submission(transaction)
    except Exception:
        pass

    return ORJSONResponse(
        {"status": "pending", "message": "PromptPay slip submitted for manual review.",
         "transaction": format_transaction(transaction), "transaction_id": transaction_id},
        status_code=status.HTTP_201_CREATED,
    )
