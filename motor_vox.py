"""Motor VoxCPM2 (OpenBMB, Apache-2.0): clonación en 30 idiomas a 48 kHz.

Corre en `.venv-vox` mediante un worker persistente, igual que Qwen.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import torch
import torchaudio as ta

ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / ".venv-vox" / "bin" / "python"
WORKER = ROOT / "motores" / "vox_worker.py"
MODELO = ROOT / "models" / "voxcpm2"


def disponible() -> bool:
    return (PYTHON.exists() and WORKER.exists()
            and (MODELO / "model.safetensors").exists())


class MotorVox:
    nombre = "voxcpm2"
    umbral_voz = 0.87
    sr = 48000

    def __init__(self, threads: int | None = None, variante: str = "neutro"):
        self.torch = torch
        self._n = 0
        self._ve = None
        self._perfil = None
        self.proc = subprocess.Popen(
            [str(PYTHON), str(WORKER), "--dir", str(MODELO)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
            cwd=str(ROOT),
        )
        self._esperar_listo()

    def _esperar_listo(self, timeout: int = 900) -> None:
        import time
        inicio = time.time()
        while time.time() - inicio < timeout:
            linea = self.proc.stdout.readline()
            if not linea:
                raise RuntimeError("el worker de VoxCPM no arrancó")
            if '"ready"' in linea:
                try:
                    self.sr = int(json.loads(linea).get("sr", self.sr))
                except ValueError:
                    pass
                return
        raise RuntimeError("VoxCPM tardó demasiado en cargar")

    def frase(self, texto: str, ref: Path | None, lang: str, exag: float = 0,
              cfg: float = 0, seed: int = 0, **kwargs):
        if ref is None:
            raise ValueError("VoxCPM necesita una referencia para clonar")
        self._n += 1
        salida = Path(tempfile.mkstemp(suffix=".wav", dir="/tmp")[1])
        self.proc.stdin.write(json.dumps({
            "id": self._n, "text": texto, "ref": str(ref), "out": str(salida),
        }) + "\n")
        self.proc.stdin.flush()
        while True:
            linea = self.proc.stdout.readline()
            if not linea:
                raise RuntimeError("el worker de VoxCPM se cerró")
            try:
                d = json.loads(linea)
            except ValueError:
                continue
            if d.get("id") != self._n:
                continue
            if not d.get("ok"):
                raise RuntimeError(d.get("error") or "VoxCPM falló")
            break
        wav, sr = ta.load(str(salida))
        salida.unlink(missing_ok=True)
        if sr != self.sr:
            wav = ta.functional.resample(wav, sr, self.sr)
        return wav.mean(0)

    def _voice_encoder(self):
        if self._ve is None:
            from chatterbox.models.voice_encoder.voice_encoder import VoiceEncoder
            ve = VoiceEncoder()
            ve.load_state_dict(torch.load(ROOT / "models" / "cb-latam" / "ve.pt",
                                          map_location="cpu", weights_only=True))
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
        w, _ = librosa.load(str(ruta), sr=16000, mono=True)[0:16000 * 10]
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
