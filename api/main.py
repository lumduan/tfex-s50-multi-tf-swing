"""Minimal FastAPI entrypoint for the TFEX strategy service.

Phase 0 exposes only ``GET /health`` so Docker, the gateway catalog, and
load balancers can confirm the container is alive. The rest of the HTTP
surface (signals, backtest, portfolio, jobs) lands in later phases as the
underlying engines are implemented.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from tfex_s50_multi_tf_swing import __version__

app: FastAPI = FastAPI(
    title="TFEX S50 Multi-TF Swing",
    description="Headless data engine for the TFEX S50 multi-timeframe swing strategy.",
    version=__version__,
)


@app.get("/health")
async def health() -> dict[str, Any]:
    """Container liveness probe."""
    return {"status": "ok", "service": "tfex-s50-multi-tf-swing", "version": __version__}
