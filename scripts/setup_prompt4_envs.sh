#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UV="$ROOT/.venv/bin/uv"
if [[ ! -x "$UV" ]]; then
  "$ROOT/.venv/bin/python" -m pip install uv
fi
"$UV" python install 3.10.21 --install-dir /tmp/patchpilot-p4-python
PY310=/tmp/patchpilot-p4-python/cpython-3.10.21-linux-x86_64-gnu/bin/python3.10
TOOLS=(pytest==9.1.1 mypy==2.3.1 ruff==0.16.8)
install_case() {
  local name="$1" python="$2" dependency="$3"
  local env="/tmp/patchpilot-p4-$name"
  "$UV" venv --clear --python "$python" "$env"
  UV_LINK_MODE=copy "$UV" pip install --python "$env/bin/python" "$dependency" "${TOOLS[@]}"
}
install_case sqlalchemy-old python3 "SQLAlchemy==1.4.54"
install_case sqlalchemy-new python3 "SQLAlchemy==2.0.44"
install_case httpx-old python3 "httpx==0.27.2"
install_case httpx-new python3 "httpx==0.28.1"
install_case openai-old python3 "openai==0.28.1"
install_case openai-new python3 "openai==1.109.1"
install_case celery-old "$PY310" "celery==4.4.7"
install_case celery-new python3 "celery==5.5.3"
if [[ ! -x /tmp/patchpilot-pydantic2-venv/bin/python ]]; then
  "$UV" venv --python python3 /tmp/patchpilot-pydantic2-venv
  UV_LINK_MODE=copy "$UV" pip install --python /tmp/patchpilot-pydantic2-venv/bin/python     "pydantic==2.13.5" "${TOOLS[@]}"
fi
