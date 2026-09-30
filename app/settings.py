"""payment-service configuration — loaded from environment / .env."""
from __future__ import annotations

import os
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()


def _flag(name: str, default: str) -> bool:
    return (os.environ.get(name) or default).lower() in {"1", "true", "yes"}


APP_HOST = os.environ.get("APP_HOST", "0.0.0.0")
APP_PORT = int(os.environ.get("APP_PORT", "8001"))

# Which game server this runs with:
# - "bancho": bancho.py — its sessions and users tables, donator granted by bancho.py.
# - "osu-web": TomYum + osu-web — osu-web sends the signed-in user, users are osu-web's
#   (phpbb_users), and osu!supporter is granted by osu-web.
BACKEND = (os.environ.get("PAYMENTS_BACKEND") or "bancho").strip().lower()
if BACKEND not in {"bancho", "osu-web"}:
    raise ValueError(f"PAYMENTS_BACKEND must be 'bancho' or 'osu-web', not {BACKEND!r}")
IS_OSU_WEB = BACKEND == "osu-web"

# MySQL: bancho.py's database, or (osu-web) this service's own database for donation_transactions.
DB_HOST = os.environ["DB_HOST"]
DB_PORT = int(os.environ["DB_PORT"])
DB_USER = os.environ["DB_USER"]
DB_PASS = quote(os.environ["DB_PASS"])
DB_NAME = os.environ["DB_NAME"]
DB_DSN = f"mysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# bancho: the secret and URL for bancho.py's /internal/* endpoints.
# Must match PAYMENT_SERVICE_TOKEN in bancho.py's env.
BANCHO_INTERNAL_TOKEN = os.environ.get("BANCHO_INTERNAL_TOKEN", "")
BANCHO_INTERNAL_URL = os.environ.get("BANCHO_INTERNAL_URL", "")  # e.g. http://bancho:8000
if not IS_OSU_WEB and not (BANCHO_INTERNAL_TOKEN and BANCHO_INTERNAL_URL):
    raise ValueError("BANCHO_INTERNAL_TOKEN and BANCHO_INTERNAL_URL are required with PAYMENTS_BACKEND=bancho")

# osu-web: where it's reached from here, and the secret shared with it (osu-web's
# SHARED_INTEROP_SECRET). osu-web signs the requests it forwards with it (X-Internal-Token, and
# X-User-Id for the signed-in player), and this service signs its supporter grants to osu-web's
# InterOp API the way osu-web expects (X-LIO-Signature).
OSU_WEB_INTERNAL_URL = os.environ.get("OSU_WEB_INTERNAL_URL", "").rstrip("/")  # e.g. http://osu-web:8080
OSU_WEB_INTEROP_SECRET = os.environ.get("OSU_WEB_INTEROP_SECRET", "")
# Where osu-web's users are, as seen from DB_NAME (another database on the same server).
OSU_WEB_DB_NAME = os.environ.get("OSU_WEB_DB_NAME", "osu")
if IS_OSU_WEB and not (OSU_WEB_INTERNAL_URL and OSU_WEB_INTEROP_SECRET):
    raise ValueError("OSU_WEB_INTERNAL_URL and OSU_WEB_INTEROP_SECRET are required with PAYMENTS_BACKEND=osu-web")

# Service-to-service auth: frontend → payment-service session validation uses
# the shared MySQL sessions table directly (no extra HTTP hop).
# Inbound requests from the Discord bot use this bearer token.
BOT_API_TOKEN = os.environ.get("BOT_API_TOKEN", "")

DOMAIN = os.environ["DOMAIN"]
# The page Stripe returns players to after checkout (paid or cancelled).
SUPPORT_URL = (os.environ.get("SUPPORT_URL") or f"https://{DOMAIN}/support").strip()

# TrueMoney
TRUEMONEY_ENABLED = _flag("TRUEMONEY_ENABLED", "false")
TRUEMONEY_PHONE = (os.environ.get("TRUEMONEY_PHONE") or "").strip()

# PromptPay (manual slip review). On by default, as before; PROMPTPAY_ENABLED=false removes its routes.
PROMPTPAY_ENABLED = _flag("PROMPTPAY_ENABLED", "true")
if IS_OSU_WEB and PROMPTPAY_ENABLED:
    raise ValueError("PromptPay isn't supported with PAYMENTS_BACKEND=osu-web yet: set PROMPTPAY_ENABLED=false")

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
