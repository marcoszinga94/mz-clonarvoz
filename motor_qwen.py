"""Motor Qwen3-TTS 0.6B: clonación con 3 s de audio, 10 idiomas (Apache-2.0).

Corre en un proceso aparte (.venv-qwen) para no compartir torch/transformers con
la app. El modelo se carga una vez y se reutiliza.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import torch
import torchaudio as ta

ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / ".venv-qwen" / "bin" / "python"
WORKER = ROOT / "motores" / "qwen_worker.py"

IDIOMAS = {"es": "Spanish", "en": "English", "pt": "Portuguese", "fr": "French",
           "de": "German", "it": "Italian", "ja": "Japanese", "ko": "Korean",
           "zh": "Chinese", "ru": "Russian"}


def disponible() -> bool:
    return PYTHON.exists() and WORKER.exists()


class MotorQwen:
    nombre = "qwen"
    umbral_voz = 0.87

    def __init__(self, threads: int | None = None, variante: str = "neutro"):
        self.torch = torch
        self.sr = 24000
        self._n = 0
        self._ve = None
        self._perfil = None
        self._textos: dict[tuple[str, float], str] = {}
        self.proc = subprocess.Popen(
            [str(PYTHON), str(WORKER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
        )
        self._esperar_listo()

    # ------------------------------------------------------------------ worker

    def _leer(self) -> dict:
        while True:
            linea = self.proc.stdout.readline()
            if not linea:
                raise RuntimeError("el worker de Qwen se cerró")
            linea = linea.strip()
            if not linea.startswith("{"):
                continue
            try:
                d = json.loads(linea)
            except ValueError:
                continue
            if "ready" in d or "id" in d:
                return d

    def _esperar_listo(self, timeout: int = 900) -> None:
        import time
        inicio = time.time()
        while time.time() - inicio < timeout:
            linea = self.proc.stdout.readline()
            if not linea:
                raise RuntimeError("el worker de Qwen no arrancó")
            if '"ready"' in linea:
                return
        raise RuntimeError("el worker de Qwen tardó demasiado en cargar")

    def _pedir(self, texto: str, ref: Path, lang: str) -> Path:
        self._n += 1
        salida = Path(tempfile.mkstemp(suffix=".wav", dir="/tmp")[1])
        pedido = {
            "id": self._n,
            "text": texto,
            "language": IDIOMAS.get(lang, "Spanish"),
            "ref": str(ref),
            "ref_text": self._texto_ref(ref, lang),
            "out": str(salida),
        }
        self.proc.stdin.write(json.dumps(pedido) + "\n")
        self.proc.stdin.flush()
        while True:
            d = self._leer()
            if d.get("id") != self._n:
                continue
            if not d.get("ok"):
                raise RuntimeError(d.get("error") or "Qwen falló")
            self.sr = int(d.get("sr", self.sr))
            return salida

    def _texto_ref(self, ref: Path, lang: str) -> str:
        clave = (str(ref), ref.stat().st_mtime)
        if clave in self._textos:
            return self._textos[clave]
        import voz
        r = voz.transcribir(ref, "base", lang if lang in IDIOMAS else "es")
        self._textos[clave] = r["texto"]
        return r["texto"]

    # ------------------------------------------------------------------- motor

    def frase(self, texto: str, ref: Path | None, lang: str, exag: float = 0,
              cfg: float = 0, seed: int = 0, **kwargs):
        if ref is None:
            raise ValueError("Qwen3-TTS necesita una referencia para clonar")
        ruta = self._pedir(texto, Path(ref), lang)
        wav, sr = ta.load(str(ruta))
        ruta.unlink(missing_ok=True)
        if sr != self.sr:
            wav = ta.functional.resample(wav, sr, self.sr)
        return wav.mean(0)

    def _voice_encoder(self):
        if self._ve is None:
            from chatterbox.models.voice_encoder.voice_encoder import VoiceEncoder
            ve = VoiceEncoder()
            ckpt = ROOT / "models" / "cb-latam" / "ve.pt"
            ve.load_state_dict(torch.load(ckpt, map_location="cpu", weights_only=True))
            ve.eval()
            self._ve = ve
        return self._ve

    def _emb(self, ruta: Path):
        import librosa
        w, _ = librosa.load(str(ruta), sr=16000, mono=True)
        return self._voice_encoder().embeds_from_wavs([w], sample_rate=16000).mean(axis=0)

    def _f0(self, ruta: Path) -> float:
        import numpy as np
        import librosa
        w, _ = librosa.load(str(ruta), sr=16000, mono=True)
        w = w[: 16000 * 10]
        f0, _, _ = librosa.pyin(w, fmin=60, fmax=400, sr=16000, frame_length=1024)
        f0 = f0[np.isfinite(f0)]
        return float(np.median(f0)) if len(f0) else 0.0

    def perfil(self, ref: Path):
        clave = (str(ref), ref.stat().st_mtime)
        if self._perfil and self._perfil[0] == clave:
            return self._perfil[1]
        perfil = (self._emb(ref), self._f0(ref))
        self._perfil = (clave, perfil)
        return perfil

    def puntuar(self, wav, ref: Path):
        import numpy as np
        e_ref, f_ref = self.perfil(ref)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            ruta = Path(tmp.name)
        ta.save(str(ruta), wav.unsqueeze(0), self.sr)
        try:
            e_toma = self._emb(ruta)
            sim = float(np.dot(e_ref, e_toma) /
                        (np.linalg.norm(e_ref) * np.linalg.norm(e_toma)))
            f0 = self._f0(ruta)
        finally:
            ruta.unlink(missing_ok=True)
        return round(sim - 0.002 * abs(f0 - f_ref), 3), round(sim, 3), round(f0, 1)

    def cerrar(self) -> None:
        try:
            self.proc.stdin.write('{"cmd":"exit"}\n')
            self.proc.stdin.flush()
        except Exception:  # noqa: BLE001
            pass
