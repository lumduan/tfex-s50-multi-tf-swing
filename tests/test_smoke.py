"""Smoke test — confirms the package + adapters subpackage import cleanly."""

from __future__ import annotations

import tfex_s50_multi_tf_swing
import tfex_s50_multi_tf_swing.adapters


def test_package_exposes_version() -> None:
    assert tfex_s50_multi_tf_swing.__version__ == "0.1.0"


def test_adapters_package_importable() -> None:
    assert tfex_s50_multi_tf_swing.adapters.__name__ == "tfex_s50_multi_tf_swing.adapters"
