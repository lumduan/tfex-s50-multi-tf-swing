"""Application settings loaded from the environment.

All variables use the ``TFEX_S50_MULTI_TF_SWING_`` prefix (umbrella naming
rule). Secrets are wrapped in :class:`pydantic.SecretStr` so they cannot
be accidentally logged via ``%r``.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Self, cast

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from tfex_s50_multi_tf_swing.backtest.costs import CostModel
    from tfex_s50_multi_tf_swing.backtest.models import WalkForwardConfig
    from tfex_s50_multi_tf_swing.bias.models import BiasConfig
    from tfex_s50_multi_tf_swing.execution.models import ExecutionConfig
    from tfex_s50_multi_tf_swing.ml.models import MLFilterConfig
    from tfex_s50_multi_tf_swing.regime.models import RegimeThresholds
    from tfex_s50_multi_tf_swing.risk.models import RiskConfig
    from tfex_s50_multi_tf_swing.signals.models import SignalConfig, StrategyId


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
    signal_or_window: int = Field(default=60, ge=1)
    signal_require_structure_shift: bool = True
    signal_swing_window: int = Field(default=4, ge=2)

    # Risk mitigation — active strategy pool + entry regime gate (config-driven, reversible).
    # ``enabled_strategies`` is the comma-separated set of strategy ids the detect map activates
    # (default ``B`` — ORB-only core; Strategy C, the 31.13R-drawdown driver, and the
    # negative-expectancy Strategy A are disabled-by-default but re-enablable with no code edit,
    # e.g. ``A,B,C``). ``signal_allowed_regimes`` is the comma-separated 1H-regime allow-set the
    # gate permits entries in (default ``trend_up`` only). Both are validated at load.
    enabled_strategies: str = "B"
    signal_allowed_regimes: str = "trend_up"

    # Phase 5 — execution-engine knobs. Bounds mirror ``execution.ExecutionConfig``.
    # ``execution_k_atr_stop`` default widened 1.5 → 2.0 (risk mitigation: wider noise buffer).
    execution_k_atr_stop: float = Field(default=2.0, gt=0.0)
    execution_partial_tp_r: float = Field(default=1.0, gt=0.0)
    execution_partial_fraction: float = Field(default=0.5, ge=0.0, le=1.0)
    execution_breakeven_buffer: float = Field(default=0.0, ge=0.0)
    execution_trail_atr_mult: float = Field(default=1.5, gt=0.0)
    execution_time_stop_bars: int = Field(default=8, ge=1)
    execution_max_spread_mult: float = Field(default=3.0, gt=0.0)

    # Phase 6 — ML probability filter. Default OFF: an unset env reproduces Phase-5
    # behaviour byte-for-byte. Bounds mirror ``ml.models.MLFilterConfig``; thresholds
    # are in [0, 1]. ``ml_model_dir`` points at the (gitignored) artifact directory.
    ml_filter_enabled: bool = False
    ml_model_dir: Path = Path("./data/models")
    ml_threshold_continuation: float = Field(default=0.55, ge=0.0, le=1.0)
    ml_threshold_fake_breakout: float = Field(default=0.50, ge=0.0, le=1.0)
    ml_seed: int = Field(default=42, ge=0)

    # Phase 7 — risk engine. Bounds mirror ``risk.models.RiskConfig``; an unset env reproduces the
    # documented risk-engine spec, so the defaults are a no-op. ``risk_deployment_stage`` is typed
    # ``str`` here (validated against the Literal when ``risk_config()`` builds ``RiskConfig``).
    risk_per_trade_pct: float = Field(default=0.005, gt=0.0, le=1.0)
    risk_daily_loss_limit_r: float = Field(default=2.0, gt=0.0)
    risk_max_consecutive_losses: int = Field(default=3, ge=1)
    risk_max_trades_per_day: int = Field(default=6, ge=1)
    risk_per_window_loss_limit_r: float = Field(default=-5.0, lt=0.0)
    risk_high_vol_percentile: float = Field(default=0.70, ge=0.0, le=1.0)
    risk_high_vol_size_factor: float = Field(default=0.5, ge=0.0, le=1.0)
    risk_panic_no_trade: bool = True
    risk_kill_switch_engaged: bool = False
    risk_spread_anomaly_mult: float = Field(default=5.0, gt=0.0)
    risk_latency_budget_ms: float = Field(default=500.0, gt=0.0)
    risk_max_error_rate: float = Field(default=0.10, ge=0.0, le=1.0)
    risk_deployment_stage: str = "paper"
    risk_micro_live_max_contracts: int = Field(default=1, ge=0)
    risk_validated_max_contracts: int = Field(default=2, ge=0)
    risk_scale_max_contracts: int = Field(default=4, ge=0)
    risk_validated_min_months_live: float = Field(default=6.0, ge=0.0)
    risk_scale_min_months_live: float = Field(default=12.0, ge=0.0)

    # Phase 8 — walk-forward harness. Bounds mirror ``backtest.models.WalkForwardConfig``; an unset
    # env reproduces the documented defaults. ``walk_forward_mode`` is typed ``str`` here (validated
    # against the ``WindowMode`` Literal when ``walk_forward_config()`` builds the model).
    walk_forward_mode: str = "anchored"
    walk_forward_train_span_days: int = Field(default=1095, ge=1)
    walk_forward_test_span_days: int = Field(default=365, ge=1)
    walk_forward_step_days: int = Field(default=365, ge=1)
    walk_forward_start_equity: Decimal = Field(default=Decimal("200000"), gt=0)
    walk_forward_seed: int = Field(default=42, ge=0)
    walk_forward_refit_ml: bool = False

    # Phase 8 — cost model. Bounds mirror ``backtest.costs.CostModel``; THB fees are Decimal.
    cost_commission_per_contract: Decimal = Field(default=Decimal("160"), ge=0)
    cost_clearing_fee_per_contract: Decimal = Field(default=Decimal("1"), ge=0)
    cost_slippage_atr_mult: float = Field(default=0.05, ge=0.0)
    cost_illiquid_session_mult: float = Field(default=2.0, ge=1.0)
    cost_tick_size: Decimal = Field(default=Decimal("0.1"), gt=0)
    cost_spread_ticks: float = Field(default=1.0, ge=0.0)
    # Roll-over penalty when a 1H position is held across a quarterly contract expiry.
    cost_rollover_commission_per_contract: Decimal = Field(default=Decimal("160"), ge=0)
    cost_rollover_spread_points: Decimal = Field(default=Decimal("2.0"), ge=0)

    def signal_config(self) -> SignalConfig:
        """Build a :class:`SignalConfig` from the configured signal fields (lazy import).

        ``signal_allowed_regimes`` (a comma-separated string, validated at load) is parsed into the
        ``allowed_regimes`` frozenset the entry gate (``signals.gate.apply_regime_gate``) consumes.
        """
        from tfex_s50_multi_tf_swing.regime.models import Regime
        from tfex_s50_multi_tf_swing.signals.models import SignalConfig

        allowed_regimes = frozenset(
            cast(Regime, token.strip())
            for token in self.signal_allowed_regimes.split(",")
            if token.strip()
        )
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
            allowed_regimes=allowed_regimes,
        )

    def enabled_strategy_ids(self) -> frozenset[StrategyId]:
        """Parse ``enabled_strategies`` (validated at load) into the active strategy-id set.

        Used by ``signals.gate.build_detect_map`` to select the active pool. Default ``{"B"}``
        (ORB-only core); re-enabling C / A is a pure env change (``TFEX_S50_MULTI_TF_SWING_
        ENABLED_STRATEGIES=A,B,C``), never a code edit.
        """
        from tfex_s50_multi_tf_swing.signals.models import StrategyId

        return frozenset(
            cast(StrategyId, token.strip().upper())
            for token in self.enabled_strategies.split(",")
            if token.strip()
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

    def risk_config(self) -> RiskConfig:
        """Build a :class:`RiskConfig` from the configured ``risk_*`` fields (lazy import).

        Imported lazily so :mod:`config.settings` stays a light leaf module and does not pull the
        risk/regime/signals graph in at import time. ``risk_deployment_stage`` is validated against
        the :data:`DeploymentStage` literal here (an unknown stage fails loud at construction).
        """
        from tfex_s50_multi_tf_swing.risk.models import DeploymentStage, RiskConfig

        return RiskConfig(
            risk_per_trade_pct=self.risk_per_trade_pct,
            daily_loss_limit_r=self.risk_daily_loss_limit_r,
            max_consecutive_losses=self.risk_max_consecutive_losses,
            max_trades_per_day=self.risk_max_trades_per_day,
            per_window_loss_limit_r=self.risk_per_window_loss_limit_r,
            high_vol_percentile=self.risk_high_vol_percentile,
            high_vol_size_factor=self.risk_high_vol_size_factor,
            panic_no_trade=self.risk_panic_no_trade,
            kill_switch_engaged=self.risk_kill_switch_engaged,
            spread_anomaly_mult=self.risk_spread_anomaly_mult,
            latency_budget_ms=self.risk_latency_budget_ms,
            max_error_rate=self.risk_max_error_rate,
            deployment_stage=cast(DeploymentStage, self.risk_deployment_stage),
            micro_live_max_contracts=self.risk_micro_live_max_contracts,
            validated_max_contracts=self.risk_validated_max_contracts,
            scale_max_contracts=self.risk_scale_max_contracts,
            validated_min_months_live=self.risk_validated_min_months_live,
            scale_min_months_live=self.risk_scale_min_months_live,
        )

    def walk_forward_config(self) -> WalkForwardConfig:
        """Build a :class:`WalkForwardConfig` from the configured ``walk_forward_*`` fields.

        Imported lazily so :mod:`config.settings` stays a light leaf module. ``walk_forward_mode``
        is validated against the :data:`WindowMode` literal here (an unknown mode fails loud).
        """
        from tfex_s50_multi_tf_swing.backtest.models import WalkForwardConfig, WindowMode

        return WalkForwardConfig(
            mode=cast(WindowMode, self.walk_forward_mode),
            train_span_days=self.walk_forward_train_span_days,
            test_span_days=self.walk_forward_test_span_days,
            step_days=self.walk_forward_step_days,
            start_equity=self.walk_forward_start_equity,
            seed=self.walk_forward_seed,
            refit_ml=self.walk_forward_refit_ml,
        )

    def cost_model(self) -> CostModel:
        """Build a :class:`CostModel` from the configured ``cost_*`` fields (lazy import)."""
        from tfex_s50_multi_tf_swing.backtest.costs import CostModel

        return CostModel(
            commission_per_contract=self.cost_commission_per_contract,
            clearing_fee_per_contract=self.cost_clearing_fee_per_contract,
            slippage_atr_mult=self.cost_slippage_atr_mult,
            illiquid_session_mult=self.cost_illiquid_session_mult,
            tick_size=self.cost_tick_size,
            spread_ticks=self.cost_spread_ticks,
            rollover_commission_per_contract=self.cost_rollover_commission_per_contract,
            rollover_spread_points=self.cost_rollover_spread_points,
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

    @field_validator("enabled_strategies")
    @classmethod
    def _validate_enabled_strategies(cls, value: str) -> str:
        """Reject an unknown strategy id at load time (the set must be ⊆ ``STRATEGY_IDS``)."""
        from tfex_s50_multi_tf_swing.signals.models import STRATEGY_IDS

        tokens = [token.strip().upper() for token in value.split(",") if token.strip()]
        invalid = sorted({token for token in tokens if token not in STRATEGY_IDS})
        if invalid:
            raise ValueError(
                f"enabled_strategies has unknown ids {invalid}; expected ⊆ {list(STRATEGY_IDS)}"
            )
        return value

    @field_validator("signal_allowed_regimes")
    @classmethod
    def _validate_signal_allowed_regimes(cls, value: str) -> str:
        """Reject an unknown regime at load time (the allow-set must be ⊆ ``REGIMES``)."""
        from tfex_s50_multi_tf_swing.regime.models import REGIMES

        tokens = [token.strip() for token in value.split(",") if token.strip()]
        invalid = sorted({token for token in tokens if token not in REGIMES})
        if invalid:
            raise ValueError(
                f"signal_allowed_regimes has unknown regimes {invalid}; expected ⊆ {list(REGIMES)}"
            )
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
