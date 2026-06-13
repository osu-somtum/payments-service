"""FastAPI app entry point for payment-service."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from app.database import database
from app.routes import admin, promptpay, stripe, truemoney


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await database.connect()
    yield
    await database.disconnect()


app = FastAPI(
    title="payment-service",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

app.include_router(truemoney.router)
app.include_router(promptpay.router)
app.include_router(stripe.router)
app.include_router(admin.router)


@app.get("/health")
async def health() -> ORJSONResponse:
    return ORJSONResponse({"status": "ok"})
