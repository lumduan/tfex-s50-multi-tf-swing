"""Tests for ``tfex_s50_multi_tf_swing.data.sources.build_ohlcv_fetcher``."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from tfex_s50_multi_tf_swing.config.settings import Settings, get_settings
from tfex_s50_multi_tf_swing.data.engine_fetcher import EngineOhlcvFetcher
from tfex_s50_multi_tf_swing.data.fetcher import OhlcvFetcher
from tfex_s50_multi_tf_swing.data.sources import build_ohlcv_fetcher

_ENGINE_URL = "http://quant-api-gateway:8000/api/v2/engines/market-data"


# ---------------------------------------------------------------------------
# Settings validators
# ---------------------------------------------------------------------------


def test_default_source_is_mirror() -> None:
    assert Settings().ohlcv_source == "mirror"


def test_invalid_source_rejected() -> None:
    with pytest.raises(ValidationError, match="ohlcv_source"):
        Settings(ohlcv_source="bogus")


def test_engine_source_requires_base_url() -> None:
    with pytest.raises(ValidationError, match="MARKET_DATA_ENGINE_BASE_URL"):
        Settings(ohlcv_source="engine")


def test_engine_source_with_base_url_is_valid() -> None:
    settings = Settings(ohlcv_source="engine", market_data_engine_base_url=_ENGINE_URL)
    assert settings.ohlcv_source == "engine"


# ---------------------------------------------------------------------------
# Factory selection
# ---------------------------------------------------------------------------


def test_mirror_builds_tvkit_fetcher() -> None:
    fetcher = build_ohlcv_fetcher(Settings(ohlcv_source="mirror"))
    assert isinstance(fetcher, OhlcvFetcher)


def test_default_builds_tvkit_fetcher() -> None:
    fetcher = build_ohlcv_fetcher(Settings())
    assert isinstance(fetcher, OhlcvFetcher)


def test_engine_builds_engine_fetcher() -> None:
    settings = Settings(
        ohlcv_source="engine",
        market_data_engine_base_url=_ENGINE_URL,
        market_data_engine_api_key=SecretStr("secret"),
    )
    fetcher = build_ohlcv_fetcher(settings)
    assert isinstance(fetcher, EngineOhlcvFetcher)


def test_engine_without_api_key_is_allowed() -> None:
    settings = Settings(ohlcv_source="engine", market_data_engine_base_url=_ENGINE_URL)
    fetcher = build_ohlcv_fetcher(settings)
    assert isinstance(fetcher, EngineOhlcvFetcher)


def test_mirror_with_token_builds_fetcher() -> None:
    settings = Settings(ohlcv_source="mirror", tvkit_auth_token=SecretStr("cookie-blob"))
    assert isinstance(build_ohlcv_fetcher(settings), OhlcvFetcher)


def test_mirror_with_empty_token_builds_fetcher() -> None:
    settings = Settings(ohlcv_source="mirror", tvkit_auth_token=SecretStr(""))
    assert isinstance(build_ohlcv_fetcher(settings), OhlcvFetcher)


# ---------------------------------------------------------------------------
# Env-driven selection via get_settings (cache_clear pattern)
# ---------------------------------------------------------------------------


def test_env_engine_source_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE", "engine")
    monkeypatch.setenv("TFEX_S50_MULTI_TF_SWING_MARKET_DATA_ENGINE_BASE_URL", _ENGINE_URL)
    get_settings.cache_clear()
    try:
        fetcher = build_ohlcv_fetcher(get_settings())
        assert isinstance(fetcher, EngineOhlcvFetcher)
    finally:
        get_settings.cache_clear()
