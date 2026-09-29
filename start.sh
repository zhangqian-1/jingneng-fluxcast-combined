#!/bin/sh
set -eu

exec uv run --no-sync uvicorn api:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
