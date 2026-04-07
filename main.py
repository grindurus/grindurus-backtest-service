"""
Application entrypoint.

    uvicorn app.main:app --reload
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import backtest, webhooks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-30s %(levelname)-8s %(message)s",
)

app = FastAPI(
    title="Backtest API",
    summary="Payment gate for paid algorithmic-strategy backtests",
    version="0.1.0",
    docs_url="/docs",
)

# CORS — lock this down in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(backtest.router)
app.include_router(webhooks.router)


@app.get("/health", tags=["infra"])
async def health() -> dict:
    return {"status": "ok"}