"""Application settings loaded from the environment.

All variables use the ``TFEX_S50_MULTI_TF_SWING_`` prefix (umbrella naming
rule). Secrets are wrapped in :class:`pydantic.SecretStr` so they cannot
be accidentally logged via ``%r``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import Field, SecretStr
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance.

    Call :func:`get_settings.cache_clear` from tests after mutating
    environment variables to force a reload.
    """
    return Settings()
