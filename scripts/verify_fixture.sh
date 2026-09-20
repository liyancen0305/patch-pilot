#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FIXTURE="$ROOT/fixtures/pydantic_v1_app"
PYTHON="${PATCHPILOT_PYTHON:-$ROOT/.venv/bin/python}"

cd "$FIXTURE"
export PYTHONPATH=src
"$PYTHON" -m pytest -q
"$PYTHON" -m mypy src tests
"$PYTHON" -m ruff check src tests
PYTHONPATH=src "$PYTHON" -c 'import shop; assert shop.User and shop.Order'
