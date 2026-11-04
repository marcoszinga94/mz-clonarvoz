"""Descarga e instalación de modelos desde la interfaz.

Cada modelo declara en `modelos.py` cómo se instala:
  auto   → lo hace la app (pesos y, si hace falta, un entorno aparte)
  hf     → requiere aceptar la licencia en Hugging Face y un token
  manual → necesita compilar el repo del modelo; se muestra el comando
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _log(progreso, fraccion: float, texto: str) -> None:
    if progreso:
        progreso(fraccion, texto)


def _correr(orden: list[str], progreso, fraccion: float, texto: str) -> None:
    _log(progreso, fraccion, texto)
    p = subprocess.run(orden, cwd=ROOT, capture_output=True, text=True)
    if p.returncode != 0:
        cola = (p.stderr or p.stdout or "").strip().splitlines()[-3:]
        raise RuntimeError(" · ".join(cola) or f"falló: {' '.join(orden[:3])}")


def _pesos(repo: str, destino: Path | None = None) -> None:
    from huggingface_hub import snapshot_download
    snapshot_download(repo, local_dir=str(destino) if destino else None)


def instalar(modelo_id: str, progreso=None) -> dict:
    """Instala o descarga un modelo. Lanza RuntimeError si no se puede."""
    if modelo_id == "qwen17":
        _log(progreso, 0.05, "descargando Qwen3-TTS 1.7B (~4,5 GB)")
        _pesos("Qwen/Qwen3-TTS-12Hz-1.7B-Base")
        _log(progreso, 1.0, "listo")
        return {"ok": True, "detalle": "Qwen3-TTS 1.7B descargado"}

    if modelo_id == "voxcpm2":
        venv = ROOT / ".venv-vox"
        if not venv.exists():
            _correr(["uv", "venv", "--python", "3.11", str(venv)], progreso,
                    0.05, "creando entorno de VoxCPM")
        if not (venv / "bin" / "python").exists():
            raise RuntimeError("no se pudo crear el entorno de VoxCPM")
        if not (venv / "bin" / "voxcpm").exists():
            _correr(["uv", "pip", "install", "--python", str(venv / "bin" / "python"),
                     "--torch-backend=cpu", "voxcpm"], progreso,
                    0.15, "instalando voxcpm (puede tardar)")
        _log(progreso, 0.55, "descargando pesos de VoxCPM2 (~5 GB)")
        _pesos("openbmb/VoxCPM2", ROOT / "models" / "voxcpm2")
        _log(progreso, 1.0, "listo")
        return {"ok": True, "detalle": "VoxCPM2 instalado"}

    if modelo_id == "pocket":
        raise RuntimeError("requiere aceptar la licencia en huggingface.co/kyutai/pocket-tts "
                           "y correr 'hf auth login'")

    raise RuntimeError("este modelo necesita instalación manual (ver README)")
