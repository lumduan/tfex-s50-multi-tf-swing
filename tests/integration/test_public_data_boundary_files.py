"""Public-data boundary: raw OHLCV must never appear in ``results/static/``.

The strategy ships pre-computed, public-safe artefacts under ``results/static/``
(tracked in git). Raw OHLCV columns (``open/high/low/close/volume/open_interest``)
and long raw price arrays must NEVER cross this boundary — only derived,
aggregate, non-reconstructable views may. This is the tfex analogue of csm-set's
``test_public_data_boundary_files`` and enforces the boundary documented in
``CLAUDE.md`` (Public data boundary) as the project grows.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_STATIC_DIR: Path = Path(__file__).resolve().parents[2] / "results" / "static"

# OHLCV column names that must not appear as object keys in public JSON.
_FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {"open", "high", "low", "close", "volume", "open_interest", "adj_close", "adjusted_close"}
)

# A JSON list of more than this many numbers looks like a raw price/volume series.
_MAX_NUMERIC_ARRAY: int = 400


def _forbidden_keys_in(obj: Any) -> list[str]:
    """Return forbidden OHLCV keys found anywhere in a decoded JSON structure."""
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(key, str) and key.lower() in _FORBIDDEN_KEYS:
                found.append(key)
            found.extend(_forbidden_keys_in(value))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_forbidden_keys_in(item))
    return found


def _long_numeric_arrays_in(obj: Any) -> list[int]:
    """Return lengths of any oversized all-numeric arrays (raw-series heuristic)."""
    sizes: list[int] = []
    if isinstance(obj, dict):
        for value in obj.values():
            sizes.extend(_long_numeric_arrays_in(value))
    elif isinstance(obj, list):
        if len(obj) > _MAX_NUMERIC_ARRAY and all(
            isinstance(x, (int, float)) and not isinstance(x, bool) for x in obj
        ):
            sizes.append(len(obj))
        for item in obj:
            sizes.extend(_long_numeric_arrays_in(item))
    return sizes


def _public_json_files() -> list[Path]:
    if not _STATIC_DIR.exists():
        return []
    return [p for p in _STATIC_DIR.rglob("*.json") if p.is_file()]


def test_no_raw_ohlcv_keys_in_public_json() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _public_json_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        keys = _forbidden_keys_in(data)
        if keys:
            offenders[str(path)] = sorted(set(keys))
    assert not offenders, f"raw OHLCV keys leaked into public JSON: {offenders}"


def test_no_long_numeric_arrays_in_public_json() -> None:
    offenders: dict[str, list[int]] = {}
    for path in _public_json_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        sizes = _long_numeric_arrays_in(data)
        if sizes:
            offenders[str(path)] = sizes
    assert not offenders, f"oversized raw numeric arrays leaked into public JSON: {offenders}"


# ---------------------------------------------------------------------------
# Negative self-tests — the detectors actually catch leaks.
# ---------------------------------------------------------------------------


def test_detector_catches_forbidden_key() -> None:
    payload = {"report": {"series": [{"date": "2026-03-02", "close": "812.9"}]}}
    assert _forbidden_keys_in(payload) == ["close"]


def test_detector_catches_long_numeric_array() -> None:
    payload = {"prices": list(range(_MAX_NUMERIC_ARRAY + 1))}
    assert _long_numeric_arrays_in(payload) == [_MAX_NUMERIC_ARRAY + 1]


def test_detector_passes_clean_payload() -> None:
    payload = {"summary": {"sharpe": 1.2, "max_drawdown": "0.05", "trades": 3}}
    assert _forbidden_keys_in(payload) == []
    assert _long_numeric_arrays_in(payload) == []


# ---------------------------------------------------------------------------
# Phase 8 — the walk-forward report serialiser is public-safe by construction.
# ---------------------------------------------------------------------------


def test_walk_forward_report_is_public_safe() -> None:
    """The Phase-8 ``results/static/backtest`` artifact carries no OHLCV / raw price arrays."""
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    import polars as pl
    from scripts.run_walk_forward import _report_to_dict

    from tfex_s50_multi_tf_swing.backtest.costs import CostModel
    from tfex_s50_multi_tf_swing.backtest.models import WalkForwardConfig
    from tfex_s50_multi_tf_swing.backtest.walk_forward import run_walk_forward
    from tfex_s50_multi_tf_swing.execution.models import ExecutionConfig
    from tfex_s50_multi_tf_swing.risk.models import RiskConfig
    from tfex_s50_multi_tf_swing.signals.models import SetupSignal

    start = datetime(2026, 1, 5, 3, 0, tzinfo=UTC)
    bars = pl.DataFrame(
        {
            "time": [start + timedelta(hours=i) for i in range(720)],
            "open": [100.0 + 0.5 * i for i in range(720)],
            "high": [101.0 + 0.5 * i for i in range(720)],
            "low": [99.0 + 0.5 * i for i in range(720)],
            "close": [100.0 + 0.5 * i for i in range(720)],
            "atr": [2.0] * 720,
        },
        schema={
            "time": pl.Datetime("us", "UTC"),
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "atr": pl.Float64,
        },
    )

    def detect(df: pl.DataFrame) -> list[SetupSignal]:
        if df.height < 5:
            return []
        row = df.row(0, named=True)
        return [
            SetupSignal(
                strategy_id="A",
                time=row["time"],
                direction="long",
                trigger_price=Decimal(str(row["close"])),
                stop_reference=Decimal(str(row["close"] - 2.0)),
                regime="trend_up",
            )
        ]

    report = run_walk_forward(
        inputs=bars,
        raw_bars=bars,
        detect={"A": detect},
        wf_config=WalkForwardConfig(train_span_days=10, test_span_days=5, step_days=5),
        exec_config=ExecutionConfig(),
        risk_config=RiskConfig(deployment_stage="micro_live"),
        cost_model=CostModel(),
    )
    payload = _report_to_dict(report)
    assert _forbidden_keys_in(payload) == []
    assert _long_numeric_arrays_in(payload) == []
