# payments-service

A standalone payment microservice for [bancho.py](https://github.com/osuAkatsuki/bancho.py) private servers. Handles TrueMoney, PromptPay (manual), and Stripe (card) donations — completely decoupled from the game server.

## What is this?

`payments-service` extracts all donation/payment logic out of `bancho.py` into its own FastAPI service. This gives you:

- **Isolated secrets** — Stripe keys, webhook secrets, and payment tokens never touch the game server
- **Independent deploys** — update payment logic without restarting bancho.py
- **Easy provider expansion** — add new payment gateways by adding a file in `app/adapters/`

## Supported payment gateways

| Provider | Flow | Notes |
|----------|------|-------|
| TrueMoney (อั่งเปา) | Auto — voucher code → instant grant | Thai players only |
| PromptPay | Manual — slip upload → staff review | Thai players only |
| Stripe | Auto — hosted checkout → webhook grant | International cards |

## How it works

```
Frontend → POST /donate/redeem          (TrueMoney)
        → POST /donate/promptpay/submit  (PromptPay)
        → POST /donate/stripe/checkout   (Stripe → returns redirect URL)

Stripe  → POST /donate/stripe/webhook   (checkout.session.completed → auto-approve)

Admin   → GET  /admin/donations
        → POST /admin/donations/{id}/approve
        → POST /admin/donations/{id}/reject

payment-service → POST session.{domain}/internal/grant_donator  (bancho.py)
```

`grant_donator` is the only call payment-service makes back to bancho.py — to sync in-memory player state (donator bit + `donor_end`). Everything else (DB writes, Stripe calls, Discord webhooks) stays in payment-service.

## Patching bancho.py

### If you use a fork with `session.py` (Somtum-style)

Add this endpoint to `app/api/domains/session.py`:

```python
@router.post("/internal/grant_donator")
async def internal_grant_donator(
    x_internal_token: str | None = Header(default=None),
    target_user_id: int = Body(...),
    days: float = Body(..., gt=0),
) -> Response:
    expected = app.settings.PAYMENT_SERVICE_TOKEN
    if not expected or x_internal_token != expected:
        return ORJSONResponse({"status": "Unauthorized"}, status_code=401)
    try:
        donor_end = await donations_uc.grant_donator(target_user_id, days)
    except Exception as exc:
        return ORJSONResponse({"status": str(exc)}, status_code=400)
    return ORJSONResponse({"status": "success", "donor_end": donor_end})
```

Add to `app/settings.py`:

```python
PAYMENT_SERVICE_TOKEN = (os.environ.get("PAYMENT_SERVICE_TOKEN") or "").strip()
```

### If you use vanilla bancho.py (no session.py)

Add the endpoint to `app/api/v1/api.py` (public API router) or `app/api/domains/osu.py`:

```python
# app/api/v1/api.py  — add near the top with other imports
from fastapi import Header

@router.post("/internal/grant_donator")
async def internal_grant_donator(
    x_internal_token: str | None = Header(default=None),
    target_user_id: int = Body(...),
    days: float = Body(..., gt=0),
) -> Response:
    token = os.environ.get("PAYMENT_SERVICE_TOKEN", "")
    if not token or x_internal_token != token:
        return ORJSONResponse({"status": "Unauthorized"}, status_code=401)
    try:
        from app.usecases import donations as donations_uc  # adjust if needed
        donor_end = await donations_uc.grant_donator(target_user_id, days)
    except Exception as exc:
        return ORJSONResponse({"status": str(exc)}, status_code=400)
    return ORJSONResponse({"status": "success", "donor_end": donor_end})
```

Then set `BANCHO_INTERNAL_URL` to the URL of whichever subdomain that router is served on (e.g. `https://api.yourdomain.com` for `v1/api.py`).

> **Note:** `donations_uc.grant_donator` must exist in your fork. If it doesn't, implement it — it needs to extend `users.donor_end`, set the DONATOR privilege bit, and sync any online in-memory `Player` object.

## Setup

### 1. Install

```bash
poetry install
```

### 2. Configure

```bash
cp .env.example .env
# fill in DB credentials, BANCHO_INTERNAL_TOKEN, BANCHO_INTERNAL_URL
```

### 3. Stripe (optional)

Set `STRIPE_SECRET_KEY` in `.env`. Then add a webhook endpoint in the [Stripe Dashboard](https://dashboard.stripe.com/webhooks):

- URL: `https://payment.yourdomain.com/donate/stripe/webhook`
- Event: `checkout.session.completed`
- Payload type: Snapshot (default)

Copy the signing secret → `STRIPE_WEBHOOK_SECRET` in `.env`.

### 4. Run

```bash
make run   # production
make dev   # with --reload
```

Service runs on port `8001` by default (`APP_PORT` in `.env`).

## Environment variables

See [`.env.example`](.env.example) for the full list with descriptions.

Key variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `DB_HOST/USER/PASS/NAME` | ✅ | Same MySQL instance as bancho.py |
| `BANCHO_INTERNAL_TOKEN` | ✅ | Shared secret — must match `PAYMENT_SERVICE_TOKEN` in bancho.py |
| `BANCHO_INTERNAL_URL` | ✅ | URL of bancho.py's session subdomain, e.g. `https://session.yourdomain.com` |
| `DOMAIN` | ✅ | Your server domain, e.g. `freedomdive.dev` |
| `STRIPE_SECRET_KEY` | ❌ | Enables Stripe checkout |
| `STRIPE_WEBHOOK_SECRET` | ❌ | Required for webhook auto-approval |
| `TRUEMONEY_ENABLED` | ❌ | Master toggle for TrueMoney (default false) |
| `TRUEMONEY_PHONE` | ❌ | Merchant phone for gift.truemoney.com |

## License

[MIT](LICENSE) © 2026 Phapoom Saksri
