"""Application settings loaded from the environment.

All variables use the ``TFEX_S50_MULTI_TF_SWING_`` prefix (umbrella naming
rule). Secrets are wrapped in :class:`pydantic.SecretStr` so they cannot
be accidentally logged via ``%r``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from tfex_s50_multi_tf_swing.bias.models import BiasConfig
    from tfex_s50_multi_tf_swing.execution.models import ExecutionConfig
    from tfex_s50_multi_tf_swing.ml.models import MLFilterConfig
    from tfex_s50_multi_tf_swing.regime.models import RegimeThresholds
    from tfex_s50_multi_tf_swing.signals.models import SignalConfig


class Settings(BaseSettings):
    """Strategy runtime configuration.

    The ``db_write_enabled`` flag is the master gate for every adapter
    write path — when ``False`` the gateway client is not constructed and
    :func:`tfex_s50_multi_tf_swing.adapters.hooks.run_post_refresh_hook`
    returns immediately.
    """

    model_config = SettingsConfigDict(
        env_prefix="TFEX_S50_MULTI_TF_SWING_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    public_mode: bool = True
    db_write_enabled: bool = False
    gateway_base_url: str = "http://quant-api-gateway:8000"
    gateway_api_key: SecretStr = SecretStr("")
    pg_dsn: str | None = None

    # Phase 1 — data infrastructure.
    data_dir: Path = Path("./data")
    tvkit_auth_token: SecretStr | None = None
    data_fetch_concurrency: int = Field(default=4, ge=1, le=32)
    roll_offset_days: int = Field(default=5, ge=0, le=30)

    # Phase 4 — market data engine (feature-market-data-engine).
    ohlcv_source: str = Field(
        default="mirror",
        description=(
            "OHLCV acquisition source for the owner-side refresh. 'mirror' "
            "(default) — fetch tvkit and persist the local Parquet store + the "
            "09 TimescaleDB mirror, the unchanged Phase-1 behaviour. 'engine' — "
            "read RAW per-dated-contract bars from the shared "
            "quant-marketdata-engine read API (gateway-proxied) and build the "
            "back-adjusted continuous locally; no tvkit cookie required. The 09 "
            "mirror is demoted to a derived local cache on this path. See "
            "feature-market-data-engine Phase 4."
        ),
    )
    market_data_engine_base_url: str | None = Field(
        default=None,
        description=(
            "Base URL of the Market Data Engine read API as proxied by the "
            "gateway, e.g. "
            "http://quant-api-gateway:8000/api/v2/engines/market-data in-cluster "
            "or http://localhost:8080/api/v2/engines/market-data for host-local "
            "dev. Required when ohlcv_source='engine'; ignored otherwise."
        ),
    )
    market_data_engine_api_key: SecretStr | None = Field(
        default=None,
        description=(
            "Shared secret presented as the X-API-Key header to the Market Data "
            "Engine read API. Optional — the engine only enforces it when its "
            "own MARKETDATA_ENGINE_API_KEY is set. Never logged."
        ),
    )

    # Phase 3 — regime-detection thresholds. Bounds mirror
    # ``regime.models.RegimeThresholds``; an out-of-range override fails at load.
    regime_panic_rv: float = Field(default=0.95, gt=0.0, le=1.0)
    regime_panic_volume_z: float = Field(default=3.0, gt=0.0)
    regime_range_low_rv: float = Field(default=0.30, ge=0.0, le=1.0)
    regime_range_high_rv: float = Field(default=0.70, ge=0.0, le=1.0)
    regime_trend_persist_min: float = Field(default=0.30, ge=0.0, le=1.0)

    # Phase 4 — HTF bias-engine deadbands. Noise bands a gate must exceed before it
    # votes directionally; defaults to a strict sign test. Bounds mirror ``bias.BiasConfig``.
    bias_slope_deadband: float = Field(default=0.0, ge=0.0)
    bias_vwap_deadband: float = Field(default=0.0, ge=0.0)

    # Phase 5 — setup-detection (signal) gate thresholds. Bounds mirror ``signals.SignalConfig``;
    # defaults reproduce the documented strategy-design behaviour, so an unset env is a no-op.
    signal_pullback_band: float = Field(default=1.0, ge=0.0)
    signal_atr_contraction_max: float = Field(default=1.0, gt=0.0)
    signal_volume_contraction_max: float = Field(default=0.5)
    signal_squeeze_max: float = Field(default=1.0, gt=0.0)
    signal_atr_compression_max: float = Field(default=1.0, gt=0.0)
    signal_volume_expansion_min: float = Field(default=1.0)
    signal_or_window: int = Field(default=15, ge=1)
    signal_require_structure_shift: bool = True
    signal_swing_window: int = Field(default=12, ge=2)

    # Phase 5 — execution-engine knobs. Bounds mirror ``execution.ExecutionConfig``.
    execution_k_atr_stop: float = Field(default=1.5, gt=0.0)
    execution_partial_tp_r: float = Field(default=1.0, gt=0.0)
    execution_partial_fraction: float = Field(default=0.5, ge=0.0, le=1.0)
    execution_breakeven_buffer: float = Field(default=0.0, ge=0.0)
    execution_trail_atr_mult: float = Field(default=1.5, gt=0.0)
    execution_time_stop_bars: int = Field(default=24, ge=1)
    execution_max_spread_mult: float = Field(default=3.0, gt=0.0)

    # Phase 6 — ML probability filter. Default OFF: an unset env reproduces Phase-5
    # behaviour byte-for-byte. Bounds mirror ``ml.models.MLFilterConfig``; thresholds
    # are in [0, 1]. ``ml_model_dir`` points at the (gitignored) artifact directory.
    ml_filter_enabled: bool = False
    ml_model_dir: Path = Path("./data/models")
    ml_threshold_continuation: float = Field(default=0.55, ge=0.0, le=1.0)
    ml_threshold_fake_breakout: float = Field(default=0.50, ge=0.0, le=1.0)
    ml_seed: int = Field(default=42, ge=0)

    def signal_config(self) -> SignalConfig:
        """Build a :class:`SignalConfig` from the configured signal fields (lazy import)."""
        from tfex_s50_multi_tf_swing.signals.models import SignalConfig

        return SignalConfig(
            pullback_band=self.signal_pullback_band,
            atr_contraction_max=self.signal_atr_contraction_max,
            volume_contraction_max=self.signal_volume_contraction_max,
            squeeze_max=self.signal_squeeze_max,
            atr_compression_max=self.signal_atr_compression_max,
            volume_expansion_min=self.signal_volume_expansion_min,
            or_window=self.signal_or_window,
            require_structure_shift=self.signal_require_structure_shift,
            swing_window=self.signal_swing_window,
        )

    def execution_config(self) -> ExecutionConfig:
        """Build an :class:`ExecutionConfig` from the configured execution fields (lazy import)."""
        from tfex_s50_multi_tf_swing.execution.models import ExecutionConfig

        return ExecutionConfig(
            k_atr_stop=self.execution_k_atr_stop,
            partial_tp_r=self.execution_partial_tp_r,
            partial_fraction=self.execution_partial_fraction,
            breakeven_buffer=self.execution_breakeven_buffer,
            trail_atr_mult=self.execution_trail_atr_mult,
            time_stop_bars=self.execution_time_stop_bars,
            max_spread_mult=self.execution_max_spread_mult,
        )

    def ml_filter_config(self) -> MLFilterConfig:
        """Build an :class:`MLFilterConfig` from the configured ``ml_*`` fields (lazy import).

        Imported lazily so :mod:`config.settings` stays a light leaf module and does not pull
        the ML graph (numpy / lightgbm) in at import time. With ``ml_filter_enabled`` unset the
        returned config is disabled and the filter is a no-op.
        """
        from tfex_s50_multi_tf_swing.ml.models import MLFilterConfig

        return MLFilterConfig(
            enabled=self.ml_filter_enabled,
            model_dir=self.ml_model_dir,
            threshold_continuation=self.ml_threshold_continuation,
            threshold_fake_breakout=self.ml_threshold_fake_breakout,
            seed=self.ml_seed,
        )

    def bias_config(self) -> BiasConfig:
        """Build a :class:`BiasConfig` from the configured bias deadband fields.

        Imported lazily so :mod:`config.settings` stays a light leaf module and does not
        pull the feature/regime/bias graph in at import time. ``neutral_regimes`` keeps its
        documented default (the two no-trade regimes).
        """
        from tfex_s50_multi_tf_swing.bias.models import BiasConfig

        return BiasConfig(
            slope_deadband=self.bias_slope_deadband,
            vwap_deadband=self.bias_vwap_deadband,
        )

    def regime_thresholds(self) -> RegimeThresholds:
        """Build a :class:`RegimeThresholds` from the configured regime fields.

        Imported lazily so :mod:`config.settings` stays a light leaf module and
        does not pull the feature/regime graph in at import time.
        """
        from tfex_s50_multi_tf_swing.regime.models import RegimeThresholds

        return RegimeThresholds(
            panic_rv=self.regime_panic_rv,
            panic_volume_z=self.regime_panic_volume_z,
            range_low_rv=self.regime_range_low_rv,
            range_high_rv=self.regime_range_high_rv,
            trend_persist_min=self.regime_trend_persist_min,
        )

    @field_validator("ohlcv_source")
    @classmethod
    def _validate_ohlcv_source(cls, value: str) -> str:
        """Reject an unknown OHLCV source at load time."""
        allowed: set[str] = {"mirror", "engine"}
        if value not in allowed:
            raise ValueError(f"ohlcv_source must be one of {sorted(allowed)!r}, got {value!r}")
        return value

    @model_validator(mode="after")
    def _require_engine_url_for_engine_source(self) -> Self:
        """Fail fast if ``ohlcv_source='engine'`` without a Market Data Engine URL."""
        if self.ohlcv_source == "engine" and not self.market_data_engine_base_url:
            raise ValueError(
                "TFEX_S50_MULTI_TF_SWING_MARKET_DATA_ENGINE_BASE_URL is required "
                "when TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE='engine' (e.g. "
                "http://quant-api-gateway:8000/api/v2/engines/market-data "
                "in-cluster or http://localhost:8080/api/v2/engines/market-data "
                "for host-local dev)."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance.

    Call :func:`get_settings.cache_clear` from tests after mutating
    environment variables to force a reload.
    """
    return Settings()
