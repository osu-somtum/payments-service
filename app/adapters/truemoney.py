"""TrueMoney Wallet voucher redeem adapter — moved verbatim from bancho.py."""
from __future__ import annotations

import re
import ssl
from typing import Any
from typing import Final

import httpx

_VOUCHER_URL_PREFIX: Final[str] = "https://gift.truemoney.com/campaign/?v="
_VOUCHER_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9]+$")
_REDEEM_URL: Final[str] = "https://gift.truemoney.com/campaign/vouchers/{voucher}/redeem"
_REQUEST_TIMEOUT: Final[float] = 15.0

_BROWSER_HEADERS: Final[dict[str, str]] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "https://gift.truemoney.com",
    "Referer": "https://gift.truemoney.com/campaign/",
    "Content-Type": "application/json",
}


def _tls_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    return ctx


def _normalize_voucher(raw: str) -> str:
    code = raw.strip()
    if code.startswith(_VOUCHER_URL_PREFIX):
        code = code[len(_VOUCHER_URL_PREFIX):]
    return code


async def redeem_voucher(phone_number: str, voucher_code: str) -> dict[str, Any]:
    code = _normalize_voucher(voucher_code)
    if not code:
        return {"status": "FAIL", "reason": "Voucher code cannot be empty."}
    if not _VOUCHER_RE.match(code):
        return {"status": "FAIL", "reason": "Voucher only allows English alphabets or numbers."}
    if not phone_number:
        return {"status": "ERROR", "reason": "Merchant phone number is not configured."}

    payload = {"mobile": phone_number, "voucher_hash": code}
    url = _REDEEM_URL.format(voucher=code)

    try:
        async with httpx.AsyncClient(verify=_tls_context(), timeout=_REQUEST_TIMEOUT) as client:
            response = await client.post(url, json=payload, headers=_BROWSER_HEADERS)
    except httpx.HTTPError as exc:
        return {"status": "ERROR", "reason": f"network error: {exc}"}

    try:
        body = response.json()
    except ValueError:
        return {"status": "ERROR", "reason": f"non-JSON response (HTTP {response.status_code})"}

    status_block = body.get("status") or {}
    code_str = status_block.get("code")
    if code_str == "SUCCESS":
        try:
            amount = int(float(body["data"]["voucher"]["redeemed_amount_baht"]))
        except (KeyError, TypeError, ValueError):
            return {"status": "ERROR", "reason": "Unexpected SUCCESS payload from TrueMoney."}
        return {"status": "SUCCESS", "amount": amount}

    reason = status_block.get("message") or f"TrueMoney rejected voucher (code={code_str})."
    return {"status": "FAIL", "reason": reason}
