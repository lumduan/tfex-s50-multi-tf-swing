"""Write-back adapters for ``quant-api-gateway``.

Public surface:

* :class:`tfex_s50_multi_tf_swing.adapters.payload.StrategyPayload` —
  validated Pydantic model for the gateway ingestion contract.
* :class:`tfex_s50_multi_tf_swing.adapters.gateway_client.GatewayClient` —
  async httpx wrapper with retry-on-5xx semantics.
* :func:`tfex_s50_multi_tf_swing.adapters.hooks.run_post_refresh_hook` —
  pipeline entrypoint, no-op when ``db_write_enabled`` is false.
* :class:`tfex_s50_multi_tf_swing.adapters.errors.TfexS50Error` and
  subclasses.
"""

from __future__ import annotations
