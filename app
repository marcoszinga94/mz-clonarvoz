#!/usr/bin/env bash
# Lanza la app visual y abre el navegador.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
[[ -x .venv/bin/python ]] || { echo "Falta el entorno. Corre: ./setup.sh"; exit 1; }
PORT="${PORT:-8000}"
if [[ "${1:-}" =~ ^[0-9]+$ ]]; then PORT="$1"; fi
URL="http://127.0.0.1:$PORT"
if [[ "${NO_OPEN:-0}" != "1" ]]; then
  ( sleep 2
    command -v xdg-open >/dev/null && xdg-open "$URL" >/dev/null 2>&1 || true
  ) &
fi
echo "ClonarVoz en $URL  (Ctrl+C para salir)"
exec .venv/bin/python -m uvicorn servidor:app --host 127.0.0.1 --port "$PORT" --log-level warning
