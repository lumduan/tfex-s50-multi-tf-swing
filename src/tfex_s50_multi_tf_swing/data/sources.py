"""OHLCV source selection — the ``TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE`` flag.

:func:`build_ohlcv_fetcher` returns the
:class:`~tfex_s50_multi_tf_swing.data.refresh.FetcherProtocol` selected by
``settings.ohlcv_source``:

- ``"mirror"`` (default) — :class:`~tfex_s50_multi_tf_swing.data.fetcher.OhlcvFetcher`,
  the unchanged Phase-1 path that fetches tvkit and persists the local Parquet
  store + the 09 TimescaleDB mirror. Requires the tvkit cookie.
- ``"engine"`` — :class:`~tfex_s50_multi_tf_swing.data.engine_fetcher.EngineOhlcvFetcher`,
  which reads RAW per-dated-contract bars from the shared Market Data Engine
  read API (gateway-proxied) and never touches tvkit.

Both satisfy ``FetcherProtocol`` and return the identical raw-frame shape, so
``refresh_all`` and every downstream consumer are agnostic to the source.
Default is unchanged behaviour; rollback = leave the flag unset / ``mirror``.
This is Phase 4 of ``feature-market-data-engine``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import SecretStr

from tfex_s50_multi_tf_swing.config.settings import Settings

if TYPE_CHECKING:
    from tfex_s50_multi_tf_swing.data.refresh import FetcherProtocol


def build_ohlcv_fetcher(settings: Settings) -> FetcherProtocol:
    """Return the OHLCV fetcher selected by ``settings.ohlcv_source``.

    Args:
        settings: Application settings carrying the ``ohlcv_source`` flag (and,
            for ``"engine"``, the Market Data Engine base URL / key).

    Returns:
        A ``FetcherProtocol``: the legacy tvkit ``OhlcvFetcher`` for ``"mirror"``
        (default), or ``EngineOhlcvFetcher`` for ``"engine"``.
    """
    # Imported lazily so the mirror path carries no engine-client import cost,
    # and the engine path constructs no tvkit fetcher.
    if settings.ohlcv_source == "engine":
        from tfex_s50_multi_tf_swing.data.engine_fetcher import EngineOhlcvFetcher

        api_key: str | None = (
            settings.market_data_engine_api_key.get_secret_value()
            if settings.market_data_engine_api_key is not None
            else None
        )
        return EngineOhlcvFetcher(
            base_url=settings.market_data_engine_base_url or "",
            api_key=api_key,
            concurrency=settings.data_fetch_concurrency,
        )

    from tfex_s50_multi_tf_swing.data.fetcher import OhlcvFetcher

    return OhlcvFetcher(
        auth_token=_resolve_auth(settings.tvkit_auth_token),
        concurrency=settings.data_fetch_concurrency,
    )


def _resolve_auth(token: SecretStr | None) -> SecretStr | None:
    """Treat an empty tvkit token as absent (anonymous tvkit session)."""
    if token is None:
        return None
    if not token.get_secret_value():
        return None
    return token


__all__: list[str] = ["build_ohlcv_fetcher"]
