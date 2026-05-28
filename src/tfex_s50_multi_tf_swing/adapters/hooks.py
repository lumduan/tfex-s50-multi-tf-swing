"""Pipeline event hooks for the TFEX strategy.

Phase 0 ships only :func:`run_post_refresh_hook`, the entrypoint downstream
phases will call after building a daily report. The hook is a strict no-op
when the master ``db_write_enabled`` flag is false, so importing this
module never opens a network connection by accident.
"""

from __future__ import annotations

import logging

from tfex_s50_multi_tf_swing.adapters.errors import GatewayClientError
from tfex_s50_multi_tf_swing.adapters.gateway_client import GatewayClient
from tfex_s50_multi_tf_swing.adapters.payload import StrategyPayload
from tfex_s50_multi_tf_swing.config.settings import Settings

logger: logging.Logger = logging.getLogger(__name__)


async def run_post_refresh_hook(
    *,
    settings: Settings,
    payload: StrategyPayload,
    client: GatewayClient | None = None,
) -> None:
    """POST the daily report to the gateway.

    Behaviour:

    * No-op when ``settings.db_write_enabled`` is ``False`` (logged at INFO).
    * Otherwise opens a short-lived :class:`GatewayClient` (or uses the
      injected ``client`` — useful for tests) and POSTs ``payload``.
    * :class:`GatewayClientError` is logged at WARNING and swallowed so a
      gateway outage never blocks the upstream pipeline.

    Args:
        settings: Loaded :class:`Settings` instance.
        payload: A validated :class:`StrategyPayload`.
        client: Optional pre-constructed :class:`GatewayClient` (the caller
            is then responsible for its lifecycle). When omitted, a new
            client is built from ``settings`` and closed before return.
    """
    if not settings.db_write_enabled:
        logger.info(
            "post-refresh hook skipped: db_write_enabled=false (strategy_id=%s)",
            payload.strategy_metadata.id,
        )
        return

    if client is not None:
        await _post(client, payload)
        return

    async with GatewayClient(
        base_url=settings.gateway_base_url,
        api_key=settings.gateway_api_key.get_secret_value(),
    ) as new_client:
        await _post(new_client, payload)


async def _post(client: GatewayClient, payload: StrategyPayload) -> None:
    try:
        await client.post_daily_report(payload)
    except GatewayClientError:
        logger.warning(
            "post-refresh hook: gateway daily-report POST failed (strategy_id=%s)",
            payload.strategy_metadata.id,
            exc_info=True,
        )


__all__: list[str] = ["run_post_refresh_hook"]
