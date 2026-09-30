"""FastAPI app entry point for payment-service."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from app import settings
from app.database import database
from app.routes import admin, promptpay, store, stripe, truemoney


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await database.connect()
    # osu-web store orders: complete card payments whose webhook didn't arrive.
    sweep = asyncio.create_task(store.sweep_stripe_orders()) if settings.IS_OSU_WEB and settings.STRIPE_ENABLED else None
    yield
    if sweep is not None:
        sweep.cancel()
    await database.disconnect()


app = FastAPI(
    title="payment-service",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

app.include_router(truemoney.router)
if settings.PROMPTPAY_ENABLED:
    app.include_router(promptpay.router)
app.include_router(stripe.router)
if settings.IS_OSU_WEB:
    app.include_router(store.router)
app.include_router(admin.router)


@app.get("/health")
async def health() -> ORJSONResponse:
    return ORJSONResponse({"status": "ok"})
