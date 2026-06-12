"""Settings tests for the Phase 5.1 execution path (execution_mode / account / broker).

Every constructor uses ``_env_file=None`` so the suite is isolated from the developer's
local ``.env`` (which sets ``PUBLIC_MODE=false``) and matches the CI environment (no ``.env``).
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from tfex_s50_multi_tf_swing.config.settings import Settings


class TestExecutionSettings:
    def test_default_off_constructs_without_extra_env(self) -> None:
        """execution_mode defaults to 'off' and requires no gateway/account env."""
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.execution_mode == "off"
        assert s.execution_account is None
        assert s.execution_broker == "sim"

    def test_mode_whitelist_rejects_unknown(self) -> None:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, execution_mode="paper")  # type: ignore[call-arg]

    def test_broker_whitelist_rejects_unknown(self) -> None:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, execution_broker="kraken")  # type: ignore[call-arg]

    def test_sim_mode_valid_with_gateway_env(self) -> None:
        s = Settings(
            _env_file=None,  # type: ignore[call-arg]
            execution_mode="sim",
            gateway_base_url="http://gateway:8000",
            gateway_api_key=SecretStr("internal-key"),
            execution_account="SIM-1",
        )
        assert s.execution_mode == "sim"
        assert s.execution_account == "SIM-1"

    def test_sim_allowed_under_default_public_mode(self) -> None:
        # public_mode defaults True; sim must remain allowed (only 'live' is forbidden).
        s = Settings(
            _env_file=None,  # type: ignore[call-arg]
            execution_mode="sim",
            gateway_base_url="http://gateway:8000",
            gateway_api_key=SecretStr("k"),
            execution_account="SIM-1",
        )
        assert s.public_mode is True
        assert s.execution_mode == "sim"

    def test_sim_missing_gateway_url_rejects(self) -> None:
        with pytest.raises(ValidationError, match="GATEWAY_BASE_URL"):
            Settings(
                _env_file=None,  # type: ignore[call-arg]
                execution_mode="sim",
                gateway_base_url="",
                gateway_api_key=SecretStr("k"),
                execution_account="SIM-1",
            )

    def test_sim_missing_gateway_key_rejects(self) -> None:
        # The default gateway_api_key is SecretStr("") — an empty secret = "missing".
        with pytest.raises(ValidationError, match="GATEWAY_API_KEY"):
            Settings(
                _env_file=None,  # type: ignore[call-arg]
                execution_mode="sim",
                gateway_base_url="http://gateway:8000",
                gateway_api_key=SecretStr(""),
                execution_account="SIM-1",
            )

    def test_sim_missing_account_rejects(self) -> None:
        with pytest.raises(ValidationError, match="EXECUTION_ACCOUNT"):
            Settings(
                _env_file=None,  # type: ignore[call-arg]
                execution_mode="sim",
                gateway_base_url="http://gateway:8000",
                gateway_api_key=SecretStr("k"),
            )

    def test_live_in_public_mode_rejected(self) -> None:
        # public_mode defaults True → live forbidden even with full env + real broker.
        with pytest.raises(ValidationError, match="forbidden when"):
            Settings(
                _env_file=None,  # type: ignore[call-arg]
                execution_mode="live",
                execution_broker="liberator",
                gateway_base_url="http://gateway:8000",
                gateway_api_key=SecretStr("k"),
                execution_account="ACC-1",
            )

    def test_live_with_sim_broker_rejected(self) -> None:
        with pytest.raises(ValidationError, match="EXECUTION_BROKER"):
            Settings(
                _env_file=None,  # type: ignore[call-arg]
                public_mode=False,
                execution_mode="live",
                execution_broker="sim",
                gateway_base_url="http://gateway:8000",
                gateway_api_key=SecretStr("k"),
                execution_account="ACC-1",
            )

    def test_live_valid_with_real_broker_private_mode(self) -> None:
        s = Settings(
            _env_file=None,  # type: ignore[call-arg]
            public_mode=False,
            execution_mode="live",
            execution_broker="settrade",
            gateway_base_url="http://gateway:8000",
            gateway_api_key=SecretStr("k"),
            execution_account="ACC-1",
        )
        assert s.execution_mode == "live"
        assert s.execution_broker == "settrade"
