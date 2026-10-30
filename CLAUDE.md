# Backend Showcase

Public pet project of Vlad Skopenko: a REST API backend with CI/CD across three environments,
containers, observability and infrastructure as code, running for $0. The roadmap is in README.md.

## Who does what

- Vlad owns the repository and builds the infrastructure himself: CI/CD, git hooks, Docker,
  Prometheus, Grafana, the logging stack, n8n and Terraform. For these, Claude explains, reviews and
  points to documentation, and writes the files only when Vlad explicitly asks.
- Application code follows `.claude/rules/workflow.md`: spec, failing tests, code, review, live check.

## Rules

Always loaded from `.claude/rules/`:
- `collaboration.md`: language, tone, how to answer and when to act
- `safety.md`: git, files, secrets, broken environments
- `workflow.md`: spec first, tests first, reviews, verification

Loaded only for files under `backend/`:
- `backend.md`: SQLAlchemy, Alembic, configuration, errors, LLM features

Hard guardrails live in `.claude/settings.json`: git state changes, deletions and migrations always
ask first, and secret files are never read.

Personal notes that should stay out of git go to `CLAUDE.local.md`.

## Commands

Run from `backend/`:

- Install: `uv sync`
- Run: `uv run uvicorn app.main:app --port 8000`
- Test: `uv run pytest`
- Lint: `uv run ruff check . && uv run ruff format --check .`
- Type-check: `uv run mypy src tests`
