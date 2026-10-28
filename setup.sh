#!/usr/bin/env bash
# Instalación reproducible en CachyOS / Arch / derivados.
# No descarga wheels CUDA: --torch-backend=cpu evita ~2.5 GB de nvidia-*.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Dependencias del sistema"
if command -v pacman >/dev/null; then
  sudo pacman -S --needed --noconfirm ffmpeg python uv
else
  echo "    (no es Arch: instala ffmpeg, python3.11 y uv a mano)"
fi
command -v ffmpeg >/dev/null || { echo "falta ffmpeg"; exit 1; }

echo "==> Entorno Python 3.11 (torch CPU)"
# Python del sistema es 3.14: casi ninguna librería de audio lo soporta aún.
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python --torch-backend=cpu -r requirements.txt

echo "==> Modelo (se descarga en el primer uso, ~2 GB)"
.venv/bin/python - <<'PY'
from chatterbox.mtl_tts import ChatterboxMultilingualTTS
print("    descargando pesos...")
ChatterboxMultilingualTTS.from_pretrained(device="cpu")
print("    ok")
PY

chmod +x voz.py voz app
echo
echo "Listo. Siguiente paso:"
echo "  ./voz.py prep toma.wav -o voz/mi_voz.wav"
echo "  ./voz.py say \"Hola, esta es mi voz clonada.\""
