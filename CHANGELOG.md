# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed (risk mitigation — drawdown control)
- **Strategy pool is config-driven.** New `TFEX_S50_MULTI_TF_SWING_ENABLED_STRATEGIES`
  (default `B`, ORB-only core) selects the active strategies via
  `signals.gate.build_detect_map`. Strategy C (the 31.13R-drawdown driver) and the
  negative-expectancy Strategy A are disabled by default but re-enablable with no code edit.
- **Entry regime gate.** New `signals.gate.apply_regime_gate` demotes fired bars whose 1H
  regime is outside `SignalConfig.allowed_regimes` (default `trend_up`, via
  `TFEX_S50_MULTI_TF_SWING_SIGNAL_ALLOWED_REGIMES`) to a clean No-Trade.
- **Wider ATR stop:** `ExecutionConfig.k_atr_stop` default `1.5 → 2.0`.
- **Stricter sizing:** `RiskConfig.risk_per_trade_pct` default `0.01 → 0.005` (0.5%; 1% is the
  documented aggressive option). Sizing was already equity-based, `Decimal`, and floors sub-1
  contracts to 0.
- **Per-window circuit breaker:** new `RiskConfig.per_window_loss_limit_r` (default `-5R`); once a
  walk-forward window's cumulative net R breaches it, the harness suppresses all further entries
  that window (`WindowResult.circuit_breaker_tripped`).

### Added
- Initial template scaffold: `src/`, `tests/`, `docs/`, `.claude/`, `.github/`.
- `pyproject.toml` with `ruff`, `mypy`, `pytest`, `pytest-asyncio`, `pytest-cov`, `bandit`, `pip-audit`.
- Multi-stage `Dockerfile` (uv-native, Python 3.11-slim).
- CI workflow (lint, format check, type check, test with coverage) on Python 3.11 and 3.12.
- Docker publish workflow targeting GHCR.
- Weekly security scan workflow (`bandit` + `pip-audit`).
- AI-agent enablement: `.claude/knowledge/project-skill.md`, `.claude/playbooks/feature-development.md`, `.claude/prompts/Prompt-Engineer.prompt.md`.
- Issue templates (bug, feature), PR template, `FUNDING.yml`.

[Unreleased]: https://github.com/OWNER/REPO/compare/HEAD...HEAD
