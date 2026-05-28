"""Application settings loaded from the environment.

All variables use the ``TFEX_S50_MULTI_TF_SWING_`` prefix (umbrella naming
rule). Secrets are wrapped in :class:`pydantic.SecretStr` so they cannot
be accidentally logged via ``%r``.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance.

    Call :func:`get_settings.cache_clear` from tests after mutating
    environment variables to force a reload.
    """
    return Settings()
