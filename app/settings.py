"""payment-service configuration — loaded from environment / .env."""
from __future__ import annotations

import os
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()

APP_HOST = os.environ.get("APP_HOST", "0.0.0.0")
APP_PORT = int(os.environ.get("APP_PORT", "8001"))

# Shared MySQL instance (bancho.py's DB — same tables, payment-service is read/write)
DB_HOST = os.environ["DB_HOST"]
DB_PORT = int(os.environ["DB_PORT"])
DB_USER = os.environ["DB_USER"]
DB_PASS = quote(os.environ["DB_PASS"])
DB_NAME = os.environ["DB_NAME"]
DB_DSN = f"mysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Secret used to call bancho.py's /internal/* endpoints.
# Must match PAYMENT_SERVICE_TOKEN in bancho.py's env.
BANCHO_INTERNAL_TOKEN = os.environ["BANCHO_INTERNAL_TOKEN"]
BANCHO_INTERNAL_URL = os.environ["BANCHO_INTERNAL_URL"]  # e.g. http://bancho:8000

# Service-to-service auth: frontend → payment-service session validation uses
# the shared MySQL sessions table directly (no extra HTTP hop).
# Inbound requests from the Discord bot use this bearer token.
BOT_API_TOKEN = os.environ.get("BOT_API_TOKEN", "")

DOMAIN = os.environ["DOMAIN"]

# TrueMoney
TRUEMONEY_ENABLED = (os.environ.get("TRUEMONEY_ENABLED") or "false").lower() in {"1", "true", "yes"}
TRUEMONEY_PHONE = (os.environ.get("TRUEMONEY_PHONE") or "").strip()

# Donation rate
DONATION_DAYS_PER_THB = float(os.environ.get("DONATION_DAYS_PER_THB") or 1.8)
PROMPTPAY_SLIP_MAX_BYTES = int(os.environ.get("PROMPTPAY_SLIP_MAX_BYTES") or 5 * 1024 * 1024)

# Discord webhooks (optional)
DISCORD_DONATION_WEBHOOK = (os.environ.get("DISCORD_DONATION_WEBHOOK") or "").strip()
DISCORD_AUDIT_LOG_WEBHOOK = (os.environ.get("DISCORD_AUDIT_LOG_WEBHOOK") or "").strip()

# Stripe (scaffold — add STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET when ready)
STRIPE_SECRET_KEY = (os.environ.get("STRIPE_SECRET_KEY") or "").strip()
STRIPE_WEBHOOK_SECRET = (os.environ.get("STRIPE_WEBHOOK_SECRET") or "").strip()
STRIPE_ENABLED = bool(STRIPE_SECRET_KEY)
# Currency Stripe charges in. "thb" = charge in Thai Baht directly.
# "usd" = convert THB → USD at checkout using STRIPE_THB_TO_USD_RATE.
STRIPE_CURRENCY = (os.environ.get("STRIPE_CURRENCY") or "thb").lower()
# Static THB→USD rate used when STRIPE_CURRENCY=usd. Update as needed.
# Example: 1 THB = 0.028 USD (as of 2026)
STRIPE_THB_TO_USD_RATE = float(os.environ.get("STRIPE_THB_TO_USD_RATE") or 0.028)
