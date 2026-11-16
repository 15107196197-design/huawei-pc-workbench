#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  if command -v uv >/dev/null 2>&1; then
    uv sync
  else
    python3 -m venv .venv
    .venv/bin/python -m pip install fastapi uvicorn httpx pydantic pillow python-multipart beautifulsoup4 pypdf reportlab pyyaml
  fi
fi
exec .venv/bin/python -m uvicorn huawei_agent.app:app --host "${STUDIO_HOST:-127.0.0.1}" --port "${STUDIO_PORT:-8787}"
