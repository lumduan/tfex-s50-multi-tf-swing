"""Tests for ``tfex_s50_multi_tf_swing.adapters.hooks``."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from tfex_s50_multi_tf_swing.adapters.errors import GatewayClientError
from tfex_s50_multi_tf_swing.adapters.gateway_client import GatewayClient
from tfex_s50_multi_tf_swing.adapters.hooks import run_post_refresh_hook
from tfex_s50_multi_tf_swing.adapters.payload import (
    StrategyPayload,
    build_ingestion_payload,
)
from tfex_s50_multi_tf_swing.config.settings import Settings


def _settings(*, db_write_enabled: bool) -> Settings:
    return Settings(
        public_mode=True,
        db_write_enabled=db_write_enabled,
        gateway_base_url="http://gateway",
        gateway_api_key=SecretStr("k"),
    )


def _payload() -> StrategyPayload:
    return build_ingestion_payload(
        strategy_id="tfex-s50-multi-tf-swing",
        last_updated=datetime(2026, 5, 28, tzinfo=UTC),
        daily_pnl=Decimal("0"),
        equity_curve=[("2026-05-28", Decimal("100000"))],
        max_drawdown=Decimal("0"),
        sharpe_ratio=Decimal("0"),
        total_value=Decimal("100000"),
        cash_balance=Decimal("100000"),
        positions_count=0,
        margin_usage=Decimal("0"),
    )


class _RecordingClient:
    """Stand-in for :class:`GatewayClient` that records each invocation."""

    def __init__(self, *, raise_exc: BaseException | None = None) -> None:
        self.posts: list[StrategyPayload] = []
        self._raise = raise_exc

    async def post_daily_report(self, payload: StrategyPayload) -> None:
        self.posts.append(payload)
        if self._raise is not None:
            raise self._raise


async def test_hook_is_noop_when_db_write_disabled() -> None:
    client = _RecordingClient()
    await run_post_refresh_hook(
        settings=_settings(db_write_enabled=False),
        payload=_payload(),
        client=client,  # type: ignore[arg-type]
    )
    assert client.posts == []


async def test_hook_posts_when_client_injected_and_enabled() -> None:
    client = _RecordingClient()
    await run_post_refresh_hook(
        settings=_settings(db_write_enabled=True),
        payload=_payload(),
        client=client,  # type: ignore[arg-type]
    )
    assert len(client.posts) == 1
    assert client.posts[0].strategy_metadata.id == "tfex-s50-multi-tf-swing"


async def test_hook_swallows_gateway_client_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failing = _RecordingClient(raise_exc=GatewayClientError("simulated"))
    with caplog.at_level("WARNING"):
        await run_post_refresh_hook(
            settings=_settings(db_write_enabled=True),
            payload=_payload(),
            client=failing,  # type: ignore[arg-type]
        )
    assert any("gateway daily-report POST failed" in r.message for r in caplog.records)


async def test_hook_builds_real_client_when_none_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no client is injected the hook constructs its own
    :class:`GatewayClient` from settings — verify it's wired up with the API
    key and posts the payload exactly once.
    """
    received: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["api_key"] = request.headers.get("X-API-Key")
        received["path"] = request.url.path
        return httpx.Response(201, json={"ok": True})

    transport = httpx.MockTransport(handler)

    def factory(**kwargs: Any) -> GatewayClient:
        return GatewayClient(**kwargs, transport=transport)

    monkeypatch.setattr("tfex_s50_multi_tf_swing.adapters.hooks.GatewayClient", factory)

    await run_post_refresh_hook(
        settings=_settings(db_write_enabled=True),
        payload=_payload(),
    )

    assert received["api_key"] == "k"
    assert received["path"] == "/api/v1/ingest/daily-report"
