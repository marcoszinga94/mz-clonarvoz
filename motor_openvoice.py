"""Motor alternativo: MeloTTS (texto → voz) + OpenVoice V2 (timbre del clon).

- MeloTTS (MIT) pone el español y la prosodia; corre rápido en CPU.
- OpenVoice V2 (MIT) transfiere el timbre de la referencia ("tone color").

Devuelve un tensor mono al sampling rate del conversor (22 050 Hz), igual que
`voz.Motor`, así que `voz.sintetizar` los trata igual: mismo corte por frase,
mismas pausas y mismo posproceso a −14 LUFS.
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parent
MELO = ROOT / "models" / "melotts-es"
OPENVOICE = ROOT / "models" / "openvoice-v2"
TMP = ROOT / "salida"


def disponible() -> bool:
    """True si están los pesos de MeloTTS y de OpenVoice."""
    return all(p.exists() for p in (
        MELO / "checkpoint.pth",
        MELO / "config.json",
        OPENVOICE / "converter" / "checkpoint.pth",
        OPENVOICE / "converter" / "config.json",
        OPENVOICE / "base_speakers" / "ses" / "es.pth",
    ))


class MotorOpenVoice:
    nombre = "openvoice"
    idiomas = ("es",)  # MeloTTS solo está instalado en español
    # El embedding del conversor vive en otra escala que el de Chatterbox:
    # la misma voz da ~0,79, así que el umbral baja para no repetir de más.
    umbral_voz = 0.70

    def __init__(self, threads: int | None = None, variante: str = "neutro"):
        self.torch = torch
        self.variante = variante
        if threads:
            torch.set_num_threads(threads)
        if not disponible():
            raise RuntimeError("faltan los pesos de OpenVoice o MeloTTS")

        t0 = time.time()
        self.tts = self._cargar_melo()
        self.spk = int(self.tts.hps.data.spk2id["ES"])

        from openvoice.api import ToneColorConverter

        self.conv = ToneColorConverter(
            str(OPENVOICE / "converter" / "config.json"), device="cpu"
        )
        # `load_ckpt` usa weights_only por defecto (True en torch 2.6) y este
        # checkpoint no lo soporta; lo cargamos igual que la librería.
        estado = torch.load(str(OPENVOICE / "converter" / "checkpoint.pth"),
                            map_location="cpu", weights_only=False)
        self.conv.model.load_state_dict(estado["model"], strict=False)
        self.conv.watermark_model = None  # ahorra CPU: el MP3 final ya se publica con disclosure
        self.sr = int(self.conv.hps.data.sampling_rate)
        self.se_src = torch.load(
            OPENVOICE / "base_speakers" / "ses" / "es.pth", map_location="cpu"
        )
        self._perfil = None
        print(f"[motor] openvoice cargado en {time.time()-t0:.1f}s", file=sys.stderr)

    @staticmethod
    def _cargar_melo():
        """MeloTTS con sus pesos locales (sus URLs de S3 devuelven 403)."""
        import melo.api as melo_api
        import melo.download_utils as du
        from melo.utils import get_hparams_from_file

        cfg = get_hparams_from_file(str(MELO / "config.json"))

        def config_local(*a, **k):
            return cfg

        def modelo_local(*a, **k):
            # El .pth trae el objeto de hparams, no solo tensores.
            return torch.load(str(MELO / "checkpoint.pth"), map_location="cpu",
                              weights_only=False)

        # melo.api ya importó los nombres: hay que pisarlos en su módulo.
        for modulo in (du, melo_api):
            modulo.load_or_download_config = config_local
            modulo.load_or_download_model = modelo_local
        return melo_api.TTS(language="ES", device="cpu")

    def _se(self, ruta: Path):
        """Embedding crudo del hablante, con la forma que espera el conversor."""
        return self.conv.extract_se([str(ruta)])

    def perfil(self, ref: Path):
        """Embedding y tono de la referencia, cacheados por archivo."""
        ref = Path(ref)
        clave = (str(ref), ref.stat().st_mtime)
        if self._perfil and self._perfil[0] == clave:
            return self._perfil[1]
        import voz

        se = self._se(ref)
        perfil = (se, se.detach().cpu().numpy().reshape(-1), voz._f0_mediana(ref))
        self._perfil = (clave, perfil)
        return perfil

    def puntuar(self, wav, ref: Path) -> tuple[float, float, float]:
        """Qué tan parecida es una toma a la referencia: (score, sim, f0)."""
        import tempfile

        import torchaudio as ta

        import voz

        _se_ref, e_ref, f_ref = self.perfil(ref)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            ruta = Path(tmp.name)
        ta.save(str(ruta), wav.unsqueeze(0), self.sr)
        try:
            e = self._se(ruta).detach().cpu().numpy().reshape(-1)
            f0 = voz._f0_mediana(ruta)
        finally:
            ruta.unlink(missing_ok=True)
        sim = voz._cos(e_ref, e)
        return round(sim - 0.002 * abs(f0 - f_ref), 3), round(sim, 3), round(f0, 1)

    def _objetivo(self, ref: Path | None):
        """Embedding de la referencia para el conversor."""
        if not ref:
            return None
        return self.perfil(ref)[0]

    def frase(self, texto: str, ref: Path | None, lang: str,
              exag: float, cfg: float, seed: int, tau: float = 0.15):
        if lang not in self.idiomas:
            raise ValueError(
                "OpenVoice solo está instalado en español; usá Chatterbox para otros idiomas"
            )
        self.torch.manual_seed(seed)
        TMP.mkdir(exist_ok=True)
        marca = uuid.uuid4().hex[:8]
        entrada = TMP / f".ov-{marca}-base.wav"
        salida = TMP / f".ov-{marca}-clon.wav"
        try:
            self.tts.tts_to_file(texto, self.spk, str(entrada), speed=1.0)
            destino = entrada
            objetivo = self._objetivo(ref)
            if objetivo is not None:
                self.conv.convert(str(entrada), self.se_src, objetivo, str(salida), tau=tau)
                destino = salida

            # MeloTTS entrega 44,1 kHz y el conversor 22,05 kHz: se fuerza `sr`
            # en ambos casos o el clip sale a media velocidad.
            import librosa

            audio, _ = librosa.load(str(destino), sr=self.sr, mono=True)
            return torch.from_numpy(audio.astype("float32"))
        finally:
            entrada.unlink(missing_ok=True)
            salida.unlink(missing_ok=True)
