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
    from tfex_s50_multi_tf_swing.regime.models import RegimeThresholds


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
