"""TFEX S50 multi-timeframe swing-intraday quant trading system.

Headless data engine following the umbrella ingestion contract:
:func:`tfex_s50_multi_tf_swing.adapters.hooks.run_post_refresh_hook` posts a
daily report to ``quant-api-gateway`` (``POST /api/v1/ingest/daily-report``).
"""

from __future__ import annotations

__version__: str = "0.1.0"
