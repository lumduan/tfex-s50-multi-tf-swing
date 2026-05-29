"""Parquet store for OHLCV bars and validation reports.

Layout (rooted at ``Settings.data_dir``):

* ``raw/<contract>/<timeframe>.parquet``        — per-quarterly-contract raw OHLCV
* ``cleaned/<contract>/<timeframe>.parquet``    — Phase 1 validator output
* ``continuous/<timeframe>.parquet``            — back-adjusted continuous series
* ``continuous_reference/<timeframe>.parquet``  — TradingView ``S501!`` cross-check
* ``validation/<YYYY-MM-DD>.json``              — daily aggregate report

All Parquet files use an explicit PyArrow schema so dtypes survive round-trip:

* ``time``                — ``TIMESTAMP[us, UTC]``
* OHLC + ``volume``       — ``DECIMAL128(18, 4)`` (raw + continuous)
* ``open_interest``       — ``DECIMAL128(18, 4)`` (nullable, raw only)
* ``adjustment_factor``   — ``DECIMAL128(18, 8)`` (continuous only)
* ``contract`` / ``contract_at_time`` / ``timeframe`` — ``string``

The store is I/O-only: it does not validate domain rules — that is the
:mod:`tfex_s50_multi_tf_swing.data.validator`'s job. The store does verify the
on-disk schema matches its constants and raises :class:`StoreError` on
mismatch.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq

from tfex_s50_multi_tf_swing.data.errors import StoreError
from tfex_s50_multi_tf_swing.data.models import (
    TIMEFRAMES,
    Timeframe,
    ValidationReport,
)

logger: logging.Logger = logging.getLogger(__name__)


_PRICE_TYPE: pa.DataType = pa.decimal128(18, 4)
_FACTOR_TYPE: pa.DataType = pa.decimal128(18, 8)
_TIME_TYPE: pa.DataType = pa.timestamp("us", tz="UTC")

RAW_SCHEMA: pa.Schema = pa.schema(
    [
        ("time", _TIME_TYPE),
        ("contract", pa.string()),
        ("timeframe", pa.string()),
        ("open", _PRICE_TYPE),
        ("high", _PRICE_TYPE),
        ("low", _PRICE_TYPE),
        ("close", _PRICE_TYPE),
        ("volume", _PRICE_TYPE),
        ("open_interest", _PRICE_TYPE),
    ]
)

CONTINUOUS_SCHEMA: pa.Schema = pa.schema(
    [
        ("time", _TIME_TYPE),
        ("timeframe", pa.string()),
        ("open", _PRICE_TYPE),
        ("high", _PRICE_TYPE),
        ("low", _PRICE_TYPE),
        ("close", _PRICE_TYPE),
        ("volume", _PRICE_TYPE),
        ("contract_at_time", pa.string()),
        ("adjustment_factor", _FACTOR_TYPE),
    ]
)

REFERENCE_SCHEMA: pa.Schema = pa.schema(
    [
        ("time", _TIME_TYPE),
        ("timeframe", pa.string()),
        ("open", _PRICE_TYPE),
        ("high", _PRICE_TYPE),
        ("low", _PRICE_TYPE),
        ("close", _PRICE_TYPE),
        ("volume", _PRICE_TYPE),
    ]
)


def _check_timeframe(tf: str) -> Timeframe:
    if tf not in TIMEFRAMES:
        raise StoreError(f"unknown timeframe {tf!r}; expected one of {TIMEFRAMES!r}")
    return tf


def _ensure_polars_frame(df: object, where: str) -> pl.DataFrame:
    if not isinstance(df, pl.DataFrame):
        raise StoreError(f"{where} expected polars.DataFrame, got {type(df).__name__}")
    return df


class ParquetStore:
    """File-system Parquet store for the data layer.

    The store owns the directory layout — every read/write resolves a
    relative path against ``base_dir`` and creates subdirectories on demand.
    A single store instance is process-safe but not multi-process safe; the
    refresh orchestrator runs writes sequentially per file.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base: Path = base_dir
        self._base.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    @property
    def base_dir(self) -> Path:
        return self._base

    def raw_path(self, contract: str, timeframe: str) -> Path:
        tf = _check_timeframe(timeframe)
        return self._base / "raw" / contract / f"{tf}.parquet"

    def cleaned_path(self, contract: str, timeframe: str) -> Path:
        tf = _check_timeframe(timeframe)
        return self._base / "cleaned" / contract / f"{tf}.parquet"

    def continuous_path(self, timeframe: str) -> Path:
        tf = _check_timeframe(timeframe)
        return self._base / "continuous" / f"{tf}.parquet"

    def reference_path(self, timeframe: str) -> Path:
        tf = _check_timeframe(timeframe)
        return self._base / "continuous_reference" / f"{tf}.parquet"

    def validation_path(self, as_of: date) -> Path:
        return self._base / "validation" / f"{as_of.isoformat()}.json"

    # ------------------------------------------------------------------
    # Raw OHLCV
    # ------------------------------------------------------------------

    def write_raw(
        self,
        contract: str,
        timeframe: str,
        df: pl.DataFrame,
    ) -> Path:
        """Write a per-contract raw frame; returns the on-disk path.

        ``df`` must contain (at least) the columns of :data:`RAW_SCHEMA`. The
        store coerces dtypes, sorts by ``time``, and de-duplicates on
        ``time`` before writing — re-running with the same source data is a
        no-op in content.
        """
        df = _ensure_polars_frame(df, "write_raw")
        tf = _check_timeframe(timeframe)
        prepared = _coerce_to_schema(df, RAW_SCHEMA, contract=contract, timeframe=tf)
        path = self.raw_path(contract, tf)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(prepared, path, compression="zstd")  # type: ignore[no-untyped-call]
        logger.info(
            "store: wrote raw OHLCV contract=%s tf=%s rows=%d path=%s",
            contract,
            tf,
            prepared.num_rows,
            path,
        )
        return path

    def read_raw(self, contract: str, timeframe: str) -> pl.DataFrame:
        path = self.raw_path(contract, timeframe)
        if not path.exists():
            raise StoreError(f"raw OHLCV not found at {path}")
        return _read_parquet(path, RAW_SCHEMA)

    def read_raw_if_exists(self, contract: str, timeframe: str) -> pl.DataFrame | None:
        path = self.raw_path(contract, timeframe)
        if not path.exists():
            return None
        return _read_parquet(path, RAW_SCHEMA)

    # ------------------------------------------------------------------
    # Continuous OHLCV
    # ------------------------------------------------------------------

    def write_continuous(self, timeframe: str, df: pl.DataFrame) -> Path:
        df = _ensure_polars_frame(df, "write_continuous")
        tf = _check_timeframe(timeframe)
        prepared = _coerce_to_schema(df, CONTINUOUS_SCHEMA, timeframe=tf)
        path = self.continuous_path(tf)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(prepared, path, compression="zstd")  # type: ignore[no-untyped-call]
        logger.info(
            "store: wrote continuous OHLCV tf=%s rows=%d path=%s",
            tf,
            prepared.num_rows,
            path,
        )
        return path

    def read_continuous(self, timeframe: str) -> pl.DataFrame:
        path = self.continuous_path(timeframe)
        if not path.exists():
            raise StoreError(f"continuous OHLCV not found at {path}")
        return _read_parquet(path, CONTINUOUS_SCHEMA)

    # ------------------------------------------------------------------
    # Continuous reference (TradingView S501!)
    # ------------------------------------------------------------------

    def write_reference(self, timeframe: str, df: pl.DataFrame) -> Path:
        df = _ensure_polars_frame(df, "write_reference")
        tf = _check_timeframe(timeframe)
        prepared = _coerce_to_schema(df, REFERENCE_SCHEMA, timeframe=tf)
        path = self.reference_path(tf)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(prepared, path, compression="zstd")  # type: ignore[no-untyped-call]
        logger.info(
            "store: wrote S501! reference tf=%s rows=%d path=%s",
            tf,
            prepared.num_rows,
            path,
        )
        return path

    def read_reference(self, timeframe: str) -> pl.DataFrame:
        path = self.reference_path(timeframe)
        if not path.exists():
            raise StoreError(f"continuous reference not found at {path}")
        return _read_parquet(path, REFERENCE_SCHEMA)

    # ------------------------------------------------------------------
    # Validation report
    # ------------------------------------------------------------------

    def write_validation_report(self, report: ValidationReport) -> Path:
        as_of_date: date = report.as_of.date()
        path = self.validation_path(as_of_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                report.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        logger.info(
            "store: wrote validation report as_of=%s path=%s",
            as_of_date.isoformat(),
            path,
        )
        return path

    def read_validation_report(self, as_of: date) -> ValidationReport:
        path = self.validation_path(as_of)
        if not path.exists():
            raise StoreError(f"validation report not found at {path}")
        return ValidationReport.model_validate_json(path.read_text(encoding="utf-8"))


def _read_parquet(path: Path, expected: pa.Schema) -> pl.DataFrame:
    table: pa.Table = pq.read_table(path)  # type: ignore[no-untyped-call]
    expected_names: set[str] = set(expected.names)
    actual_names: set[str] = set(table.schema.names)
    if expected_names != actual_names:
        raise StoreError(
            f"on-disk schema mismatch at {path}: "
            f"expected columns {sorted(expected_names)}, "
            f"got {sorted(actual_names)}"
        )
    return pl.from_arrow(table)  # type: ignore[return-value]


def _coerce_to_schema(
    df: pl.DataFrame,
    schema: pa.Schema,
    *,
    contract: str | None = None,
    timeframe: str | None = None,
) -> pa.Table:
    """Coerce a Polars frame into the target Arrow schema.

    Adds the ``contract`` / ``timeframe`` columns when present in the target
    schema and missing from the frame. Sorts by ``time`` and drops duplicates
    on (``time``[, ``contract``]). Casts Decimal columns with explicit
    precision/scale so on-disk dtype is stable.
    """
    expected_names: list[str] = list(schema.names)
    work = df.clone()

    if "contract" in expected_names and "contract" not in work.columns:
        if contract is None:
            raise StoreError("contract column missing and no contract argument given")
        work = work.with_columns(pl.lit(contract).alias("contract"))
    if "timeframe" in expected_names and "timeframe" not in work.columns:
        if timeframe is None:
            raise StoreError("timeframe column missing and no timeframe argument given")
        work = work.with_columns(pl.lit(timeframe).alias("timeframe"))

    if "open_interest" in expected_names and "open_interest" not in work.columns:
        work = work.with_columns(pl.lit(None).cast(pl.Decimal(18, 4)).alias("open_interest"))

    missing: list[str] = [c for c in expected_names if c not in work.columns]
    if missing:
        raise StoreError(f"frame is missing required columns: {missing}")

    work = work.select(expected_names)
    if "time" in work.columns:
        work = work.sort("time")
    dedup_keys: list[str] = ["time"]
    if "contract" in work.columns:
        dedup_keys.append("contract")
    if "timeframe" in work.columns:
        dedup_keys.append("timeframe")
    work = work.unique(subset=dedup_keys, keep="last").sort("time")

    arrow_table: pa.Table = work.to_arrow()

    # Cast each column to the exact target type so Decimal precision is fixed.
    casted_arrays: list[pa.Array | pa.ChunkedArray] = []
    for field in schema:
        col = arrow_table.column(field.name)
        if col.type == field.type:
            casted_arrays.append(col)
            continue
        try:
            casted_arrays.append(col.cast(field.type))
        except (pa.ArrowInvalid, pa.ArrowNotImplementedError) as exc:
            raise StoreError(
                f"cannot cast column {field.name!r} from {col.type} to {field.type}: {exc}"
            ) from exc
    return pa.Table.from_arrays(casted_arrays, schema=schema)


__all__: list[str] = [
    "CONTINUOUS_SCHEMA",
    "ParquetStore",
    "RAW_SCHEMA",
    "REFERENCE_SCHEMA",
]
