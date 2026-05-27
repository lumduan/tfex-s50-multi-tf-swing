# Development Workflow

Day-to-day workflow for shipping changes to this strategy. Aligns with the umbrella
pre-push checklist memory item.

## Loop

```
branch  →  implement  →  test  →  quality gate  →  commit  →  push  →  PR
```

## Detailed steps

1. **Branch off `main`**: `git checkout -b feat/<short-slug>` (or `fix/`, `docs/`,
   `chore/`).
2. **Read the relevant `.claude/knowledge/*.md`** before writing code so you do not
   re-invent the design.
3. **Write the test first** where feasible. Tests live in `tests/unit/<subpkg>/` or
   `tests/integration/`.
4. **Implement** with `from __future__ import annotations`, typed signatures,
   Pydantic at boundaries.
5. **Run the local quality gate** — this exactly matches what CI runs:

   ```bash
   uv run ruff check . \
     && uv run ruff format --check . \
     && uv run mypy src tests \
     && uv run pytest
   ```

   Do this **before every `git push`**, no exceptions. Save your collaborators a
   CI failure cycle.

6. **Commit** with [Conventional Commits](https://www.conventionalcommits.org/)
   prefix: `feat(scope):`, `fix(scope):`, `docs(scope):`, `test(scope):`,
   `chore(scope):`, `refactor(scope):`.
7. **Push** and `gh pr create` against `main`.
8. **Watch CI**. If a hook fails, fix the underlying issue — never `--no-verify`.

## What goes in a PR

- One thing, well-tested. Mixed PRs are slow to review.
- A description that says **why**, not just what (the diff says what).
- A "Test plan" checklist that mirrors the verification you actually performed.

## What never goes in a PR

- Secrets, credentials, `.env` files.
- Raw OHLCV data (`data/` is gitignored — keep it that way).
- Large binary blobs (use Parquet / JSON Schema sidecars instead).
- "While I was in here" drive-by refactors. File a separate PR.

## Useful commands

```bash
uv sync --all-groups                              # install everything
uv run pytest -k <pattern> -v                     # subset of tests
uv run pytest --cov=src --cov-report=term-missing # local coverage
uv run mypy src tests                             # type check
uv run ruff check . --fix                         # auto-fix lints
uv run ruff format .                              # auto-format
```
