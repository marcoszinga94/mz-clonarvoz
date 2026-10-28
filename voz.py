#!/usr/bin/env python3
"""
ClonarVoz — pipeline local de clonación de voz para redes sociales.

Uso rápido:
    ./voz.py prep  toma.wav -o refs/mi-voz.wav
    ./voz.py say   "Hola, esto es mi voz clonada." -o salida/demo.mp3
    ./voz.py batch guiones/ejemplo.json
    ./voz.py post  salida/demo.wav -o salida/demo.mp3

Motor: Chatterbox Multilingual (Resemble AI, licencia MIT, pesos abiertos).
Corre en CPU; no requiere GPU.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_REF = ROOT / "refs" / "mi-voz.wav"
SALIDA = ROOT / "salida"

# Caracteres por segundo aproximados en habla natural (es).
# Se usan solo para detectar alucinaciones/truncamientos, no para sincronizar nada.
CPS_MIN, CPS_MAX = 6.0, 30.0


# --------------------------------------------------------------------------- #
# Utilidades de audio (ffmpeg)
# --------------------------------------------------------------------------- #

def ffmpeg(args: list[str]) -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg no está instalado: sudo pacman -S ffmpeg")
    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args])
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg falló con código {p.returncode}")


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True,
    ).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def probe_stats(path: Path) -> dict:
    """Duración, sample rate, canales y nivel medio/pico."""
    info = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=sample_rate,channels,codec_name", "-of", "json", str(path)],
        capture_output=True, text=True,
    ).stdout
    streams = json.loads(info or "{}").get("streams", [{}])
    s = streams[0] if streams else {}
    vol = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect",
         "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    mean = re.search(r"mean_volume: (-?[\d.]+) dB", vol)
    peak = re.search(r"max_volume: (-?[\d.]+) dB", vol)
    return {
        "dur": round(probe_duration(path), 3),
        "sr": s.get("sample_rate"),
        "ch": s.get("channels"),
        "mean_db": float(mean.group(1)) if mean else None,
        "peak_db": float(peak.group(1)) if peak else None,
    }


# --------------------------------------------------------------------------- #
# prep: limpiar y normalizar el clip de referencia
# --------------------------------------------------------------------------- #

def preparar_audio(src: Path, dst: Path, max_s: float | None = 12.0) -> dict:
    """Limpia y normaliza un clip. Lanza ValueError/RuntimeError si falla."""
    src, dst = Path(src), Path(dst)
    if not src.exists():
        raise ValueError(f"no existe el audio de entrada: {src}")
    if dst.parent.exists() and not dst.parent.is_dir():
        raise ValueError(f"{dst.parent} es un archivo, no una carpeta")
    dst.parent.mkdir(parents=True, exist_ok=True)

    # Cadena: quita retumbe/ruido de fondo, normaliza a -18 LUFS,
    # recorta silencios de los extremos y limita a `max_s` segundos.
    af = (
        "highpass=f=80,"
        "afftdn=nr=12:nf=-30,"
        "loudnorm=I=-18:TP=-3:LRA=11,"
        "aresample=24000,"
        "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.1,"
        "areverse,"
        "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.1,"
        "areverse"
    )
    if max_s:
        af += f",atrim=0:{max_s}"
    ffmpeg(["-i", str(src), "-af", af, "-ac", "1", "-ar", "24000",
            "-c:a", "pcm_s16le", str(dst)])
    return probe_stats(dst)


MAX_REF = 60.0


def preparar_referencia(src: Path, dst: Path, max_s: float = MAX_REF) -> dict:
    """Limpia la toma entera y la usa como referencia (sin recortar tramos).

    Chatterbox toma los primeros 6 s para los tokens de estilo y los primeros
    10 s para el decoder, pero el embedding del hablante promedia *toda* la
    referencia. Por eso conviene conservar la toma completa: más audio, timbre
    más estable. El tope evita referencias absurdamente largas.
    """
    dst = Path(dst)
    original = round(probe_duration(src), 2)
    st = preparar_audio(src, dst, max_s)
    return {"total": original, "dur": round(st["dur"], 2), "stats": st}


def cmd_prep(a: argparse.Namespace) -> None:
    dst = Path(a.output)
    info = preparar_referencia(Path(a.input), dst, a.max or MAX_REF)
    st = info["stats"]

    print(f"✓ referencia lista: {dst}")
    print(f"  usa {st['dur']}s de {info['total']}s de audio")
    print(f"  {st['sr']} Hz · {st['ch']} canal · "
          f"medio {st['mean_db']} dB · pico {st['peak_db']} dB")

    if st["dur"] < 3:
        print("  ⚠ menos de 3 s: el clon va a sonar inestable. Graba 10 s o más.")
    if st["peak_db"] is not None and st["peak_db"] > -1:
        print("  ⚠ pico muy alto, probablemente el audio original saturaba.")


# --------------------------------------------------------------------------- #
# Variedades de español
# --------------------------------------------------------------------------- #

PACKS = {
    # variante interna: (repo HF, archivo t3 dentro del repo)
    "latam": ("ResembleAI/Chatterbox-Multilingual-es-mx-latam", "t3_es_mx_latam.safetensors"),
    "espana": ("ResembleAI/Chatterbox-Multilingual-es-es", "t3_es_es.safetensors"),
}
# "argentina" usa el pack LatAm: el acento rioplatense lo aporta la referencia.
VARIANTES = {
    "latam": "latam", "argentina": "latam",
    "espana": "espana", "neutro": None, "": None,
}


def pack_listo(clave: str) -> bool:
    d = ROOT / "models" / f"cb-{clave}"
    return (d / "t3_mtl23ls_v2.safetensors").exists() and (d / "s3gen.pt").exists()

VOSEO = {
    "tú": "vos", "tienes": "tenés", "puedes": "podés", "quieres": "querés",
    "eres": "sos", "sabes": "sabés", "haces": "hacés", "dices": "decís",
    "vienes": "venís", "debes": "debés", "sales": "salís", "vives": "vivís",
}
# Solo pares del mismo género: cambiar el género rompe el artículo.
LEXICO_AR = {
    "móvil": "celular", "móviles": "celulares", "coche": "auto",
    "coches": "autos", "patata": "papa", "patatas": "papas",
    "zumo": "jugo", "zumos": "jugos", "conducir": "manejar",
    "aparcar": "estacionar", "billete": "boleto", "billetes": "boletos",
    "nevera": "heladera", "pereza": "fiaca",
}


def _conservar_caja(original: str, nuevo: str) -> str:
    return nuevo[:1].upper() + nuevo[1:] if original[:1].isupper() else nuevo


def regionalizar(texto: str, variante: str = "neutro") -> str:
    """Ajusta el texto a la variedad elegida (hoy solo el español argentino).

    No toca el audio: el acento lo pone la referencia. Esto cambia voseo y
    vocabulario para que el texto suene natural en esa región.
    """
    if variante != "argentina":
        return texto

    def cambio(m: re.Match) -> str:
        palabra = m.group(0)
        base = palabra.lower()
        nuevo = VOSEO.get(base) or LEXICO_AR.get(base)
        return _conservar_caja(palabra, nuevo) if nuevo else palabra

    return re.sub(r"\b[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+\b", cambio, texto)


# --------------------------------------------------------------------------- #
# Motor TTS
# --------------------------------------------------------------------------- #

def _dir_pack(clave: str) -> Path:
    """Arma un checkpoint cargable mezclando el pack con los assets compartidos."""
    from huggingface_hub import snapshot_download

    repo, t3 = PACKS[clave]
    base = Path(snapshot_download("ResembleAI/chatterbox",
                                  allow_patterns=["ve.pt", "conds.pt"]))
    pack = Path(snapshot_download(repo, allow_patterns=[
        t3, "s3gen_v3.pt", "grapheme_mtl_merged_expanded_v1.json"]))

    destino = ROOT / "models" / f"cb-{clave}"
    destino.mkdir(parents=True, exist_ok=True)
    enlaces = {
        "ve.pt": base / "ve.pt",
        "conds.pt": base / "conds.pt",
        "t3_mtl23ls_v2.safetensors": pack / t3,
        "s3gen.pt": pack / "s3gen_v3.pt",
        "grapheme_mtl_merged_expanded_v1.json": pack / "grapheme_mtl_merged_expanded_v1.json",
    }
    for nombre, origen in enlaces.items():
        enlace = destino / nombre
        if not enlace.exists():
            enlace.symlink_to(origen.resolve())
    return destino


class Motor:
    def __init__(self, threads: int | None = None, variante: str = "neutro"):
        import torch
        self.torch = torch
        self._conds = None
        self.variante = variante
        if threads:
            torch.set_num_threads(threads)

        t0 = time.time()
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        pack = VARIANTES.get(variante)
        if pack and pack_listo(pack):
            self.model = ChatterboxMultilingualTTS.from_local(_dir_pack(pack), "cpu")
        else:
            if pack:
                print(f"[motor] pack {pack} no instalado: uso el modelo base "
                      f"(./voz packs {pack} para bajarlo)", file=sys.stderr)
            self.model = ChatterboxMultilingualTTS.from_pretrained(device="cpu")
        self.sr = self.model.sr
        print(f"[motor] chatterbox {variante} cargado en {time.time()-t0:.1f}s",
              file=sys.stderr)

    def frase(self, texto: str, ref: Path | None, lang: str,
              exag: float, cfg: float, seed: int):
        import numpy as np
        self.torch.manual_seed(seed)
        random.seed(seed)
        np.random.seed(seed & 0xFFFFFFFF)
        extra = {}
        if ref:
            # Preparar la referencia cuesta con audios largos: se cachea por
            # archivo, fecha y expresividad.
            clave = (str(ref), ref.stat().st_mtime, exag)
            if clave != self._conds:
                self.model.prepare_conditionals(str(ref), exaggeration=exag)
                self._conds = clave
        else:
            self._conds = None
            extra["audio_prompt_path"] = None

        wav = self.model.generate(texto, language_id=lang,
                                  exaggeration=exag, cfg_weight=cfg, **extra)
        return wav.squeeze(0)


def partir_frases(texto: str, max_chars: int = 180) -> list[str]:
    """Corta por frases y luego por comas para no exceder el contexto del modelo."""
    texto = re.sub(r"\s+", " ", texto).strip()
    trozos: list[str] = []
    for parrafo in re.split(r"(?<=[.!?…])\s+", texto):
        if len(parrafo) <= max_chars:
            trozos.append(parrafo)
            continue
        buf = ""
        for parte in re.split(r"(?<=[,;:])\s+", parrafo):
            if len(buf) + len(parte) <= max_chars:
                buf = f"{buf} {parte}".strip()
            else:
                if buf:
                    trozos.append(buf)
                buf = parte
        if buf:
            trozos.append(buf)
    return [t for t in trozos if t]


def sintetizar(motor: Motor, texto: str, ref: Path | None, lang: str,
               exag: float, cfg: float, seed: int, progreso=None,
               variante: str = "neutro") -> tuple["object", list[str], list[float]]:
    """Genera por frases y concatena. Devuelve (wav, frases, duraciones)."""
    torch = motor.torch
    frases = partir_frases(regionalizar(texto, variante))
    partes, duraciones = [], []

    for i, frase in enumerate(frases):
        if progreso:
            progreso(i, len(frases), frase)
        esperado = len(frase) / 15.0  # ~15 car/s de habla
        for intento in range(3):
            wav = motor.frase(frase, ref, lang, exag, cfg, seed + i * 17 + intento)
            dur = wav.shape[-1] / motor.sr
            raro = dur > max(8.0, esperado * 3) or dur < esperado * 0.35
            if not raro:
                break
            print(f"  ↻ reintento {intento+1} ({dur:.1f}s vs {esperado:.1f}s esperados)",
                  file=sys.stderr)
        else:
            print(f"  ⚠ frase problemática, se usa igual: {frase[:60]!r}", file=sys.stderr)

        if partes:
            partes.append(torch.zeros(int(0.18 * motor.sr)))
            duraciones[-1] += 0.18  # la pausa cierra la frase anterior; así los
                                    # tiempos siguen alineados con `frases`
        partes.append(wav)
        duraciones.append(dur)
        print(f"  · {dur:5.2f}s  {frase[:70]}", file=sys.stderr)

    return torch.cat(partes), frases, duraciones


# --------------------------------------------------------------------------- #
# record: grabar la referencia con el micrófono
# --------------------------------------------------------------------------- #

FRASE_GUIA = (
    "Mira, esto es algo que aprendí después de mucho prueba y error. "
    "No hace falta tener un estudio para sonar bien. "
    "¿Quieres que te cuente cómo lo hice?"
)


def cmd_record(a: argparse.Namespace) -> None:
    if shutil.which("arecord") is None:
        sys.exit("falta arecord: sudo pacman -S alsa-utils")
    tmp = ROOT / "refs" / "_toma.wav"
    tmp.parent.mkdir(parents=True, exist_ok=True)

    print("\nVas a grabar 12 s. Lee esto en tono conversacional, sin prisa:\n")
    print(f'  "{FRASE_GUIA}"\n')
    print("Silencio alrededor, micro a 15–20 cm, sin música.")
    for s in (3, 2, 1):
        print(f"  {s}...", end="", flush=True)
        time.sleep(1)
    print(" ¡grabando!\n", flush=True)

    orden = ["arecord", "-q", "-f", "S16_LE", "-r", "48000", "-c", "1",
             "-t", "wav", str(tmp)]
    if a.secs:
        orden += ["-d", str(a.secs)]
    else:
        print("  (sin límite: pulsa Ctrl+C para terminar)\n")
    subprocess.run(orden)

    if not tmp.exists() or probe_duration(tmp) < 1:
        sys.exit("no se grabó nada: revisa el micro con  arecord -l  y  alsamixer")
    print(f"  grabados {probe_duration(tmp):.1f}s")
    info = preparar_referencia(tmp, Path(a.output))
    tmp.unlink(missing_ok=True)

    print(f"✓ referencia lista: {a.output}")
    print(f"  usa {info['dur']}s de {info['total']}s grabados")


# --------------------------------------------------------------------------- #
# post: loudness y formato para redes
# --------------------------------------------------------------------------- #

def postprocesar(src: Path, dst: Path, lufs: float = -14.0) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    ext = dst.suffix.lower()
    af = f"loudnorm=I={lufs}:TP=-1.5:LRA=9,aresample=48000"
    if ext == ".mp3":
        ffmpeg(["-i", str(src), "-af", af, "-ac", "1", "-ar", "48000",
                "-c:a", "libmp3lame", "-b:a", "192k", "-write_xing", "0", str(dst)])
    elif ext in (".m4a", ".aac"):
        ffmpeg(["-i", str(src), "-af", af, "-ac", "1", "-ar", "48000",
                "-c:a", "aac", "-b:a", "192k", str(dst)])
    else:
        ffmpeg(["-i", str(src), "-af", af, "-ac", "1", "-ar", "48000",
                "-c:a", "pcm_s16le", str(dst)])


# --------------------------------------------------------------------------- #
# Subtítulos (SRT) a partir de los tiempos reales de cada frase
# --------------------------------------------------------------------------- #

def escribir_srt(dst: Path, frases: list[str], duraciones: list[float]) -> None:
    def ts(t: float) -> str:
        h, r = divmod(t, 3600)
        m, s = divmod(r, 60)
        return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")

    lineas, t, idx = [], 0.0, 1
    for frase, dur in zip(frases, duraciones):
        palabras = frase.split()
        # máximo ~9 palabras por cue, repartiendo el tiempo por longitud
        n = max(1, -(-len(palabras) // 9))
        tam = -(-len(palabras) // n)
        for k in range(0, len(palabras), tam):
            grupo = " ".join(palabras[k:k + tam])
            peso = len(grupo) / max(1, len(frase))
            d = dur * peso
            lineas += [str(idx), f"{ts(t)} --> {ts(t + d)}", grupo, ""]
            t += d
            idx += 1
    dst.write_text("\n".join(lineas), encoding="utf-8")


# --------------------------------------------------------------------------- #
# guion: generar un guion base
# --------------------------------------------------------------------------- #

def cmd_guion(a: argparse.Namespace) -> None:
    import guiones
    r = guiones.generar(a.tema, a.objetivo, a.segundos, a.variante)
    if a.output:
        items = [{"id": f"clip-{i+1:02d}", "texto": t} for i, t in enumerate(r["lineas"])]
        Path(a.output).parent.mkdir(parents=True, exist_ok=True)
        Path(a.output).write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✓ {a.output} · {r['palabras']} palabras · ~{r['duracion_estimada']}s")
    else:
        print("\n".join(r["lineas"]))
        print(f"\n({r['palabras']} palabras · ~{r['duracion_estimada']}s)")



# --------------------------------------------------------------------------- #
# transcribir: Whisper base (faster-whisper, int8 en CPU)
# --------------------------------------------------------------------------- #

_WHISPER = None


def cargar_whisper(modelo: str = "base", hilos: int = 6):
    global _WHISPER
    if _WHISPER is None or _WHISPER[0] != modelo:
        from faster_whisper import WhisperModel
        _WHISPER = (modelo, WhisperModel(modelo, device="cpu", compute_type="int8",
                                         cpu_threads=hilos))
    return _WHISPER[1]


def transcribir(ruta: Path, modelo: str = "base", idioma: str | None = "es",
                hilos: int = 6, progreso=None) -> dict:
    """Transcribe un audio y devuelve frases con tiempos.

    Usa faster-whisper (mismas pesas que Whisper, CTranslate2 en int8):
    en este equipo va ~6x más rápido que tiempo real con el modelo base.
    """
    ruta = Path(ruta)
    if not ruta.exists():
        raise ValueError(f"no existe el audio: {ruta}")
    motor = cargar_whisper(modelo, hilos)
    segmentos, info = motor.transcribe(
        str(ruta),
        language=idioma or None,
        beam_size=1,
        vad_filter=True,
        condition_on_previous_text=False,
    )

    total = float(info.duration or 0.0)
    crudos = []
    for seg in segmentos:
        crudos.append({"inicio": round(seg.start, 2), "fin": round(seg.end, 2),
                       "texto": seg.text.strip()})
        if progreso and total:
            progreso(min(seg.end / total, 1.0), total)

    texto = re.sub(r"\s+", " ", " ".join(c["texto"] for c in crudos)).strip()
    lineas = []
    for l in re.split(r"(?<=[.!?…])\s+", texto):
        l = l.strip()
        if l:
            lineas.append(l[0].upper() + l[1:])
    return {
        "texto": texto,
        "lineas": lineas or ([texto] if texto else []),
        "segmentos": crudos,
        "idioma": info.language,
        "dur": round(total, 2),
        "modelo": modelo,
    }


def escribir_srt_segmentos(dst: Path, segmentos: list[dict]) -> None:
    def ts(t: float) -> str:
        h, r = divmod(t, 3600)
        m, s = divmod(r, 60)
        return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")

    lineas = []
    for i, seg in enumerate(segmentos, 1):
        lineas += [str(i), f"{ts(seg['inicio'])} --> {ts(seg['fin'])}",
                   seg["texto"], ""]
    dst.write_text("\n".join(lineas), encoding="utf-8")


def cmd_packs(a: argparse.Namespace) -> None:
    claves = [a.clave] if a.clave else ["latam", "espana"]
    for clave in claves:
        if clave not in PACKS:
            sys.exit(f"pack desconocido: {clave} (usa latam o espana)")
        print(f"descargando pack {clave} (~3,5 GB)…")
        d = _dir_pack(clave)
        print(f"✓ {clave} listo en {d}")


def cmd_transcribir(a: argparse.Namespace) -> None:
    destino = Path(a.output) if a.output else None
    if destino and destino.suffix.lower() == ".srt":
        r = transcribir(Path(a.input), a.modelo, None if a.lang == "auto" else a.lang,
                        a.threads)
        escribir_srt_segmentos(destino, r["segmentos"])
        print(f"✓ {destino} · {len(r['segmentos'])} líneas · {r['dur']}s")
        return

    print("[whisper] cargando modelo base…", file=sys.stderr)
    r = transcribir(Path(a.input), a.modelo, None if a.lang == "auto" else a.lang,
                    a.threads)
    if destino:
        if destino.suffix.lower() == ".json":
            items = [{"id": f"clip-{i+1:02d}", "texto": t} for i, t in enumerate(r["lineas"])]
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text("\n".join(r["lineas"]), encoding="utf-8")
        print(f"✓ {destino} · {len(r['lineas'])} frases · {r['dur']}s · idioma {r['idioma']}")
    else:
        print("\n".join(r["lineas"]))
        print(f"\n({r['dur']}s · idioma {r['idioma']} · modelo {r['modelo']})",
              file=sys.stderr)


# --------------------------------------------------------------------------- #
# say / batch
# --------------------------------------------------------------------------- #

def preparar_ref(ruta: Path | None) -> Path | None:
    if ruta is None:
        return None
    p = Path(ruta).expanduser()
    if not p.exists():
        sys.exit(f"no existe el clip de referencia: {p}\nCréalo con: ./voz record  (o ./voz prep toma.wav)")
    return p


def cmd_say(a: argparse.Namespace) -> None:
    ref = preparar_ref(a.voice)
    salida = Path(a.output)
    salida.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    motor = Motor(a.threads, a.variante)
    wav, frases, durs = sintetizar(motor, a.text, ref, a.lang, a.exag, a.cfg, a.seed,
                                   variante=a.variante)

    import torchaudio as ta
    tmp = salida.with_suffix(".wav") if salida.suffix.lower() != ".wav" else salida
    ta.save(str(tmp), wav.unsqueeze(0), motor.sr)
    if tmp != salida:
        postprocesar(tmp, salida, a.lufs)
        if a.keep_wav:
            print(f"✓ wav: {tmp}")
        else:
            tmp.unlink(missing_ok=True)

    if a.srt:
        escribir_srt(salida.with_suffix(".srt"), frases, durs)
    dur = wav.shape[-1] / motor.sr
    print(f"✓ {salida}  ({dur:.1f}s de audio en {time.time()-t0:.0f}s)")


def cmd_batch(a: argparse.Namespace) -> None:
    ref = preparar_ref(a.voice)
    guion = json.loads(Path(a.guion).read_text(encoding="utf-8"))
    items = guion if isinstance(guion, list) else guion.get("items", guion.get("clips", []))
    if not items:
        sys.exit("el guion no tiene elementos: usa [{\"id\": ..., \"texto\": ...}]")

    outdir = Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    motor = Motor(a.threads, a.variante)
    manifiesto = []

    import torchaudio as ta
    for i, it in enumerate(items, 1):
        texto = it.get("texto") or it.get("text") or ""
        if not texto.strip():
            continue
        cid = str(it.get("id") or f"{i:02d}")
        lang = it.get("lang", a.lang)
        print(f"[{i}/{len(items)}] {cid}", file=sys.stderr)
        wav, frases, durs = sintetizar(motor, texto, ref, lang, a.exag, a.cfg,
                                       it.get("seed", a.seed + i),
                                       variante=a.variante)
        wavpath = outdir / f"{cid}.wav"
        ta.save(str(wavpath), wav.unsqueeze(0), motor.sr)
        mp3 = outdir / f"{cid}.mp3"
        postprocesar(wavpath, mp3, a.lufs)
        escribir_srt(outdir / f"{cid}.srt", frases, durs)
        if not a.keep_wav:
            wavpath.unlink()
        manifiesto.append({
            "id": cid, "archivo": str(mp3), "texto": texto,
            "lang": lang, "dur": round(wav.shape[-1] / motor.sr, 2),
        })

    (outdir / "manifiesto.json").write_text(
        json.dumps(manifiesto, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ {len(manifiesto)} clips en {outdir}/")


def cmd_post(a: argparse.Namespace) -> None:
    postprocesar(Path(a.input), Path(a.output), a.lufs)
    st = probe_stats(Path(a.output))
    print(f"✓ {a.output} · {st['dur']}s · {st['sr']} Hz · {a.lufs} LUFS")


# --------------------------------------------------------------------------- #

def main() -> None:
    p = argparse.ArgumentParser(description="ClonarVoz — TTS local con clonación de voz")
    p.add_argument("--threads", type=int, default=6,
                   help="hilos de CPU (def. 6 = núcleos físicos; 12 va más lento)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("prep", help="limpiar y normalizar el clip de referencia")
    sp.add_argument("input")
    sp.add_argument("-o", "--output", default=str(DEFAULT_REF))
    sp.add_argument("--max", type=float, default=MAX_REF,
                    help=f"segundos máximos (def. {MAX_REF:.0f}; 0 = sin límite)")
    sp.set_defaults(func=cmd_prep)

    sr = sub.add_parser("record", help="grabar el clip de referencia con el micrófono")
    sr.add_argument("-o", "--output", default=str(DEFAULT_REF))
    sr.add_argument("--secs", type=int, default=12,
                    help="segundos a grabar (def. 12; 0 = hasta Ctrl+C)")
    sr.add_argument("--max", type=float, default=12.0)
    sr.set_defaults(func=cmd_record)

    spk = sub.add_parser("packs", help="descargar packs de español (LatAm / España)")
    spk.add_argument("clave", nargs="?", choices=["latam", "espana"],
                     help="sin argumento baja los dos")
    spk.set_defaults(func=cmd_packs)

    stx = sub.add_parser("transcribir", help="transcribir un audio con Whisper base")
    stx.add_argument("input")
    stx.add_argument("-o", "--output", help=".txt, .json (guion para batch) o .srt")
    stx.add_argument("--modelo", default="base", help="base · small · medium (def. base)")
    stx.add_argument("--lang", default="es", help="idioma o 'auto'")
    stx.set_defaults(func=cmd_transcribir)

    sg = sub.add_parser("guion", help="generar un guion base a partir de un tema")
    sg.add_argument("tema")
    sg.add_argument("--objetivo", choices=["educar", "vender", "entretener", "historia"], default="educar")
    sg.add_argument("--segundos", type=int, choices=[15, 30, 60], default=30)
    sg.add_argument("--variante", type=int, default=0, help="otra versión del mismo tema")
    sg.add_argument("-o", "--output", help="guardar como guion JSON para batch")
    sg.set_defaults(func=cmd_guion)

    ss = sub.add_parser("say", help="generar un clip")
    ss.add_argument("text")
    ss.add_argument("-o", "--output", default=str(SALIDA / "clip.mp3"))
    ss.add_argument("--voice", default=str(DEFAULT_REF), help="clip de referencia")
    ss.add_argument("--lang", default="es")
    ss.add_argument("--exag", type=float, default=0.5, help="expresividad 0–1 (def. 0.5)")
    ss.add_argument("--cfg", type=float, default=0.5, help="apego al texto 0–1 (def. 0.5)")
    ss.add_argument("--seed", type=int, default=42)
    ss.add_argument("--variante", choices=["neutro", "latam", "argentina", "espana"],
                    default="neutro")
    ss.add_argument("--lufs", type=float, default=-14.0)
    ss.add_argument("--srt", action="store_true", help="generar subtítulos .srt")
    ss.add_argument("--keep-wav", action="store_true")
    ss.set_defaults(func=cmd_say)

    sb = sub.add_parser("batch", help="generar varios clips desde un JSON")
    sb.add_argument("guion")
    sb.add_argument("--outdir", default=str(SALIDA))
    sb.add_argument("--voice", default=str(DEFAULT_REF))
    sb.add_argument("--lang", default="es")
    sb.add_argument("--exag", type=float, default=0.5)
    sb.add_argument("--cfg", type=float, default=0.5)
    sb.add_argument("--seed", type=int, default=42)
    sb.add_argument("--variante", choices=["neutro", "latam", "argentina", "espana"],
                    default="neutro")
    sb.add_argument("--lufs", type=float, default=-14.0)
    sb.add_argument("--keep-wav", action="store_true")
    sb.set_defaults(func=cmd_batch)

    sp2 = sub.add_parser("post", help="normalizar un audio a -14 LUFS para redes")
    sp2.add_argument("input")
    sp2.add_argument("-o", "--output")
    sp2.add_argument("--lufs", type=float, default=-14.0)
    sp2.set_defaults(func=cmd_post)

    a = p.parse_args()
    if a.cmd == "post" and not a.output:
        a.output = str(Path(a.input).with_suffix(".mp3"))
    try:
        a.func(a)
    except (ValueError, RuntimeError) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
