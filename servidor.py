#!/usr/bin/env python3
"""
Servidor local de ClonarVoz.

    ./app            → abre http://127.0.0.1:8000 en el navegador

Todo corre en esta máquina: ni el audio ni el texto salen de aquí.
"""

from __future__ import annotations

import json
import queue
from collections import OrderedDict
import re
import shutil
import tempfile
import threading
import time
import unicodedata
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

import guiones
import motor_openvoice
import voz

ROOT = Path(__file__).resolve().parent
REFS = ROOT / "refs"
OUT = ROOT / "salida"
WEB = ROOT / "web"
REFS.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)

HILOS = 6
MAX_CHARS = 6000
TOMAS = 3  # cuántas grabaciones se conservan por nombre

ESTADO = {"motor": "cargando", "detalle": "cargando el modelo", "error": None}
TRABAJOS: dict[str, dict] = {}
COLA: queue.Queue[str] = queue.Queue()
COLA_LOCK = threading.Lock()
ESTADO_DIR = ROOT / ".estado"
ESTADO_DIR.mkdir(exist_ok=True)
COLA_FILE = ESTADO_DIR / "cola.json"
AJUSTES_FILE = ESTADO_DIR / "ajustes.json"
HISTORIAL_FILE = ESTADO_DIR / "trabajos.json"
HISTORIAL_MAX = 20


def _leer_json(ruta: Path, por_defecto):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return por_defecto


def _escribir_json(ruta: Path, datos) -> None:
    tmp = ruta.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(ruta)
    except OSError:
        pass


def cargar_ajustes() -> dict:
    d = _leer_json(AJUSTES_FILE, {})
    return {"motor": d.get("motor", "chatterbox"), "ref": d.get("ref"),
            "fidelidad": int(d.get("fidelidad", 2))}


def guardar_ajustes(datos: dict) -> dict:
    actual = cargar_ajustes()
    if datos.get("motor") in ("chatterbox", "openvoice"):
        actual["motor"] = datos["motor"]
    if datos.get("fidelidad") in (1, 2, 3, 4):
        actual["fidelidad"] = int(datos["fidelidad"])
    if "ref" in datos:
        nombre = Path(str(datos["ref"] or "")).name
        actual["ref"] = nombre if (REFS / nombre).exists() else None
    _escribir_json(AJUSTES_FILE, actual)
    return actual


def registrar_historial(job: dict) -> None:
    """Guarda los trabajos terminados para que sobrevivan al reinicio."""
    if job.get("tipo") in ("transcripcion", "calibracion", "evaluacion"):
        return
    historial = _leer_json(HISTORIAL_FILE, [])
    compacto = {k: v for k, v in job.items()
                if k in ("id", "estado", "motor", "ref", "creado", "fin",
                         "segundos", "resultados", "n_items", "error", "tipo")}
    historial = [h for h in historial if h.get("id") != job.get("id")]
    historial.append(compacto)
    historial = sorted(historial, key=lambda h: h.get("fin") or h.get("creado") or 0)[-HISTORIAL_MAX:]
    _escribir_json(HISTORIAL_FILE, historial)
COLA_TX: queue.Queue[str] = queue.Queue()
_DUR_CACHE: dict[str, tuple[float, float]] = {}


# --------------------------------------------------------------------------- #
# Estados y utilidades
# --------------------------------------------------------------------------- #

def slug(texto: str, limite: int = 40) -> str:
    s = unicodedata.normalize("NFKD", texto)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return (s[:limite] or "clip").strip("-")


def duracion(p: Path) -> float:
    key, mtime = str(p), p.stat().st_mtime
    c = _DUR_CACHE.get(key)
    if c and c[0] == mtime:
        return c[1]
    d = voz.probe_duration(p)
    _DUR_CACHE[key] = (mtime, d)
    return d


def historial() -> list[dict]:
    clips = sorted(OUT.glob("*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)[:40]
    salida = []
    for p in clips:
        meta = {}
        side = p.with_suffix(".json")
        if side.exists():
            try:
                meta = json.loads(side.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                meta = {}
        salida.append({
            "nombre": p.stem,
            "titulo": meta.get("titulo") or p.stem,
            "mp3": f"/files/salida/{p.name}",
            "srt": f"/files/salida/{p.stem}.srt" if p.with_suffix(".srt").exists() else None,
            "dur": round(duracion(p), 2),
            "motor": meta.get("motor") or "chatterbox",
            "variante": meta.get("variante") or "neutro",
            "mtime": p.stat().st_mtime,
        })
    return salida


def meta_ref(ruta: Path) -> dict:
    side = ruta.with_suffix(".json")
    if side.exists():
        try:
            return json.loads(side.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def guardar_meta(ruta: Path, **datos) -> None:
    ruta = Path(ruta)
    meta = meta_ref(ruta)
    meta.update(datos)
    ruta.with_suffix(".json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def refs_disponibles() -> list[dict]:
    archivos = [
        p for p in REFS.glob("*.wav")
        if not p.name.startswith(("_", ".")) and not p.stem.endswith("-completa")
    ]
    archivos.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {"nombre": p.name, "dur": round(duracion(p), 2),
         "url": f"/files/refs/{p.name}", "mtime": p.stat().st_mtime,
         "analisis": meta_ref(p).get("analisis"),
         "exag": meta_ref(p).get("exag"),
         "tau": meta_ref(p).get("tau"),
         "nota": meta_ref(p).get("nota")}
        for p in archivos
    ]


def rotar_tomas(destino: Path) -> None:
    """Deja la toma nueva en `destino` y conserva las TOMAS-1 anteriores."""
    destino = Path(destino)
    viejo = destino.with_name(f"{destino.stem}-{TOMAS}.wav")
    viejo.unlink(missing_ok=True)
    viejo.with_suffix(".json").unlink(missing_ok=True)
    for i in range(TOMAS - 1, 0, -1):
        origen = destino if i == 1 else destino.with_name(f"{destino.stem}-{i}.wav")
        if origen.exists():
            fin = destino.with_name(f"{destino.stem}-{i + 1}.wav")
            origen.rename(fin)
            if origen.with_suffix(".json").exists():
                origen.with_suffix(".json").rename(fin.with_suffix(".json"))


# --------------------------------------------------------------------------- #
# Worker: una sola generación a la vez (la CPU es el recurso escaso)
# --------------------------------------------------------------------------- #

MOTORES: "OrderedDict[str, object]" = OrderedDict()

# Motores de clonación disponibles. "chatterbox" es el default histórico;
# "openvoice" es MeloTTS + OpenVoice V2 (solo español, más liviano en CPU).
MOTORES_DISPONIBLES = {
    "chatterbox": lambda: True,
    "openvoice": lambda: motor_openvoice.disponible(),
}


def clave_motor(variante: str) -> str:
    if variante in ("latam", "argentina"):
        return "latam" if voz.pack_listo("latam") else "neutro"
    if variante == "espana":
        return "espana" if voz.pack_listo("espana") else "neutro"
    return "neutro"


def obtener_motor(variante: str, nombre: str = "chatterbox"):
    """Carga (y cachea) el modelo pedido. Máximo 2 en memoria."""
    if nombre not in MOTORES_DISPONIBLES:
        raise ValueError(f"motor desconocido: {nombre}")

    if nombre == "openvoice":
        clave = "openvoice:es"      # MeloTTS solo tiene español instalado
        if clave in MOTORES:
            MOTORES.move_to_end(clave)
            return MOTORES[clave]
        motor = motor_openvoice.MotorOpenVoice(HILOS)
    else:
        clave = f"chatterbox:{clave_motor(variante)}"
        if clave in MOTORES:
            MOTORES.move_to_end(clave)
            return MOTORES[clave]
        motor = voz.Motor(HILOS, clave_motor(variante))

    MOTORES[clave] = motor
    while len(MOTORES) > 2:
        MOTORES.popitem(last=False)
    return motor


def guardar_cola() -> None:
    """Guarda los trabajos pendientes para sobrevivir a un reinicio."""
    with COLA_LOCK:
        activos = []
        for j in list(TRABAJOS.values()):
            if j.get("estado") not in ("en_cola", "generando"):
                continue
            if j.get("tipo") == "transcripcion" or j.get("cancelar"):
                continue  # temporal en /tmp o ya cancelado
            activos.append({k: v for k, v in j.items()
                            if k not in ("ruta", "parciales", "resultados")})
        tmp = COLA_FILE.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(activos, ensure_ascii=False), encoding="utf-8")
            tmp.replace(COLA_FILE)
        except OSError:
            pass


def cargar_cola() -> None:
    if not COLA_FILE.exists():
        return
    try:
        datos = json.loads(COLA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for d in datos:
        jid = d.get("id")
        if not jid or jid in TRABAJOS:
            continue
        d.update(estado="en_cola", detalle="reanudado tras reinicio", progreso=0.0,
                 parciales=[], resultados=[], cancelar=False, error=None)
        d.setdefault("creado", time.time())
        TRABAJOS[jid] = d
        COLA.put(jid)


def _procesar(job: dict) -> None:
    import torchaudio as ta

    if job.get("cancelar"):
        job.update(estado="cancelado", detalle="cancelado antes de empezar")
        return

    ref = REFS / job["ref"] if job.get("ref") else None
    if ref is not None and not ref.exists():
        raise ValueError(f"la referencia {job['ref']} ya no existe")

    for viejo in OUT.glob(".parcial-*.wav"):
        if time.time() - viejo.stat().st_mtime > 1800:
            viejo.unlink(missing_ok=True)

    items = job["items"]
    n = len(items)
    variante = job.get("variante", "neutro")
    motor_nombre = job.get("motor", "chatterbox")
    # Cargar un modelo tarda ~1 min: se informa en vez de dejar el trabajo "en cola".
    clave = "openvoice:es" if motor_nombre == "openvoice" else f"chatterbox:{clave_motor(variante)}"
    if clave not in MOTORES:
        job["estado"] = "generando"
        job["detalle"] = ("cargando OpenVoice (solo la primera vez)"
                          if motor_nombre == "openvoice"
                          else "cargando el pack de español (solo la primera vez)")
    motor = obtener_motor(variante, motor_nombre)
    job["estado"] = "generando"

    for k, it in enumerate(items):
        def cb(i: int, total: int, frase: str, k: int = k) -> None:
            job["progreso"] = round((k + i / max(total, 1)) / n, 3)
            job["detalle"] = f"clip {k + 1} de {n} · frase {min(i + 1, total)} de {total}"

        def cb_trozo(i: int, total: int, wav, frase: str, k: int = k) -> None:
            archivo = OUT / f".parcial-{job['id']}-{k}-{i}.wav"
            ta.save(str(archivo), wav.unsqueeze(0), motor.sr)
            job["parciales"].append({
                "n": len(job["parciales"]) + 1,
                "url": f"/files/salida/{archivo.name}",
                "dur": round(wav.shape[-1] / motor.sr, 2),
                "texto": frase[:90],
            })

        try:
            wav, frases, durs = voz.sintetizar(
                motor, it["texto"], ref, job["lang"], job["exag"], job["cfg"],
                job["seed"] + k * 101, progreso=cb, variante=variante,
                pausas=job.get("pausas"), cortar_comas=job.get("cortar_comas", False),
                recortar=job.get("recortar_silencio", True),
                silencio_max_ms=job.get("silencio_max_ms", 350),
                al_trozo=cb_trozo, cancelado=lambda: bool(job.get("cancelar")),
                fidelidad=max(1, min(int(job.get("fidelidad", 1)), 4)),
                extra={"tau": float(job.get("tau", 0.15))} if motor_nombre == "openvoice" else None,
            )
        except voz.Cancelado:
            for p in OUT.glob(f".parcial-{job['id']}-*.wav"):
                p.unlink(missing_ok=True)
            job.update(estado="cancelado", detalle="cancelado por el usuario", parciales=[])
            return

        base = f"{slug(it['nombre'])}-{uuid.uuid4().hex[:4]}"
        wav_path = OUT / f"{base}.wav"
        ta.save(str(wav_path), wav.unsqueeze(0), motor.sr)

        mp3 = OUT / f"{base}.mp3"
        voz.postprocesar(wav_path, mp3, job["lufs"])
        wav_path.unlink(missing_ok=True)

        srt = OUT / f"{base}.srt"
        voz.escribir_srt(srt, frases, durs)

        (OUT / f"{base}.json").write_text(json.dumps({
            "titulo": it["nombre"],
            "texto": it["texto"],
            "lang": job["lang"],
            "variante": job.get("variante", "neutro"),
            "motor": job.get("motor", "chatterbox"),
            "exag": job["exag"],
            "cfg": job["cfg"],
            "seed": job["seed"] + k * 101,
            "ref": job.get("ref"),
            "pausas": voz.normalizar_pausas(job.get("pausas")),
            "cortar_comas": job.get("cortar_comas", False),
            "recortar_silencio": job.get("recortar_silencio", True),
            "silencio_max_ms": job.get("silencio_max_ms", 350),
            "tau": job.get("tau"),
            "creado": time.time(),
        }, ensure_ascii=False), encoding="utf-8")

        job["resultados"].append({
            "nombre": base,
            "titulo": it["nombre"],
            "mp3": f"/files/salida/{mp3.name}",
            "srt": f"/files/salida/{srt.name}",
            "dur": round(wav.shape[-1] / motor.sr, 2),
        })
        job["progreso"] = round((k + 1) / n, 3)

    for p in OUT.glob(f".parcial-{job['id']}-*.wav"):
        p.unlink(missing_ok=True)


def _calibrar(job: dict) -> None:
    ref = REFS / job["ref"]
    if not ref.exists():
        raise ValueError(f"la referencia {job['ref']} ya no existe")
    motor_nombre = job.get("motor", "chatterbox")
    motor = obtener_motor(job.get("variante", "neutro"), motor_nombre)
    job.update(estado="generando", detalle="probando ajustes")

    def cb(i: int, total: int, texto: str) -> None:
        if job.get("cancelar"):
            raise voz.Cancelado()
        job["progreso"] = round(i / max(total, 1), 3)
        job["detalle"] = f"{texto} ({i + 1} de {total})"

    try:
        if motor_nombre == "openvoice":
            r = voz.calibrar_openvoice(motor, ref, job.get("lang", "es"), progreso=cb)
        else:
            r = voz.calibrar_referencia(motor, ref, job.get("lang", "es"), progreso=cb)
    except voz.Cancelado:
        job.update(estado="cancelado", detalle="cancelado por el usuario")
        return

    job["calibracion"] = r
    job["progreso"] = 1.0
    job["detalle"] = ""
    if motor_nombre == "openvoice":
        guardar_meta(ref, tau=r["mejor"]["tau"], calibracion=r)
    else:
        guardar_meta(ref, exag=r["mejor"]["exag"], calibracion=r)


def _evaluar(job: dict) -> None:
    motor = obtener_motor(job.get("variante", "neutro"))
    tomas = []
    for i, ruta in enumerate(job["refs"]):
        if job.get("cancelar"):
            raise voz.Cancelado()
        job["progreso"] = round(i / max(len(job["refs"]), 1), 3)
        job["detalle"] = f"probando {ruta} ({i + 1} de {len(job['refs'])})"
        p = REFS / ruta
        if not p.exists():
            continue
        try:
            r = voz.evaluar_toma(motor, p, job.get("lang", "es"), job.get("exag", 0.4))
        except Exception:  # noqa: BLE001
            continue
        guardar_meta(p, nota=r["score"])
        tomas.append(r)
    tomas.sort(key=lambda t: t["score"], reverse=True)
    job["evaluacion"] = {"tomas": tomas, "mejor": tomas[0]["ref"] if tomas else None}
    job["progreso"] = 1.0


def _worker() -> None:
    try:
        obtener_motor("neutro")
        ESTADO.update(motor="listo", detalle="", error=None)
    except Exception as e:  # noqa: BLE001
        ESTADO.update(motor="error", detalle="", error=str(e))

    while True:
        jid = COLA.get()
        job = TRABAJOS.get(jid)
        if not job:
            continue
        t0 = time.time()
        job["inicio"] = t0  # el cronómetro corre desde que empieza, no desde la cola
        try:
            if job.get("tipo") == "calibracion":
                _calibrar(job)
            elif job.get("tipo") == "evaluacion":
                _evaluar(job)
            else:
                _procesar(job)
            # _procesar puede haberlo cancelado: no pisar ese estado.
            if job["estado"] not in ("cancelado", "error"):
                job.update(estado="listo", progreso=1.0, detalle="")
        except voz.Cancelado:
            job.update(estado="cancelado", detalle="cancelado por el usuario")
        except Exception as e:  # noqa: BLE001
            job.update(estado="error", error=str(e))
        finally:
            job["segundos"] = round(time.time() - t0, 1)
            job["fin"] = time.time()
            guardar_cola()
            registrar_historial(job)


def _worker_tx() -> None:
    while True:
        jid = COLA_TX.get()
        job = TRABAJOS.get(jid)
        if not job:
            continue
        ruta = Path(job["ruta"])
        t0 = time.time()
        try:
            job.update(estado="transcribiendo", detalle="cargando modelo base")
            r = voz.transcribir(
                ruta, "base", job.get("lang") or None, HILOS,
                progreso=lambda p, total: job.update(
                    progreso=round(p, 3),
                    detalle=f"{int(p * 100)}% de {round(total)}s transcritos",
                ),
            )
            job.update(estado="listo", progreso=1.0, detalle="", **r)
        except voz.Cancelado:
            job.update(estado="cancelado", detalle="cancelado por el usuario")
        except Exception as e:  # noqa: BLE001
            job.update(estado="error", error=str(e))
        finally:
            job["segundos"] = round(time.time() - t0, 1)
            ruta.unlink(missing_ok=True)


cargar_cola()
threading.Thread(target=_worker, daemon=True).start()
threading.Thread(target=_worker_tx, daemon=True).start()


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #

app = FastAPI(title="ClonarVoz", docs_url=None, redoc_url=None)


@app.middleware("http")
async def sin_cache_ui(request, call_next):
    """La UI se revalida siempre: si no, un cambio de JS queda cacheado."""
    respuesta = await call_next(request)
    ruta = request.url.path
    if ruta.startswith("/api/"):
        respuesta.headers["Cache-Control"] = "no-store"
    elif ruta == "/" or ruta.startswith("/web/"):
        respuesta.headers["Cache-Control"] = "no-cache, must-revalidate"
    return respuesta


@app.get("/")
def index() -> HTMLResponse:
    """Sirve la UI con la versión de JS/CSS atada al mtime del archivo.

    Sin esto el navegador puede seguir usando un app.js viejo después de un
    cambio (StaticFiles no manda Cache-Control y la caché heurística gana).
    """
    html = (WEB / "index.html").read_text(encoding="utf-8")
    for nombre in ("app.js", "style.css"):
        archivo = WEB / nombre
        if archivo.exists():
            html = html.replace(f"/web/{nombre}",
                                f"/web/{nombre}?v={int(archivo.stat().st_mtime)}")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/api/estado")
def estado() -> dict:
    return {
        "motor": ESTADO["motor"],
        "detalle": ESTADO["detalle"],
        "error": ESTADO["error"],
        "refs": refs_disponibles(),
        "motores": {nombre: listo() for nombre, listo in MOTORES_DISPONIBLES.items()},
        "cola": COLA.qsize(),
    }


@app.post("/api/ref")
async def subir_ref(archivo: UploadFile = File(...), nombre: str = Form("voz")) -> dict:
    sufijo = Path(archivo.filename or "toma.wav").suffix or ".wav"
    tmp = Path(tempfile.gettempdir()) / f"ref-{uuid.uuid4().hex}{sufijo}"
    try:
        with tmp.open("wb") as f:
            shutil.copyfileobj(archivo.file, f)
        if tmp.stat().st_size < 2000:
            raise ValueError("el archivo llegó vacío")
        destino = REFS / f"{slug(nombre, 24)}.wav"
        nuevo = REFS / f".nuevo-{uuid.uuid4().hex[:8]}.wav"
        info = voz.preparar_referencia(tmp, nuevo)
        if destino.exists():
            rotar_tomas(destino)
        nuevo.replace(destino)
        analisis = voz.analizar_referencia(destino)
        guardar_meta(destino, analisis=analisis)
        return {"nombre": destino.name, "url": f"/files/refs/{destino.name}",
                "analisis": analisis, **info}
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    finally:
        tmp.unlink(missing_ok=True)


@app.post("/api/guion")
def crear_guion(body: dict) -> dict:
    try:
        return guiones.generar(
            body.get("tema", ""),
            body.get("objetivo", "educar"),
            int(body.get("segundos", 30)),
            int(body.get("variante", 0)),
        )
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))


def _ruta_ref(nombre: str) -> Path:
    ruta = REFS / Path(str(nombre)).name
    if not ruta.exists() or ruta.suffix != ".wav":
        raise HTTPException(404, "referencia no encontrada")
    return ruta


@app.post("/api/ref/analizar")
def analizar_ref(body: dict) -> dict:
    ruta = _ruta_ref(body.get("nombre", ""))
    a = voz.analizar_referencia(ruta)
    guardar_meta(ruta, analisis=a)
    return a


@app.post("/api/ref/calibrar")
def calibrar_ref(body: dict) -> dict:
    ruta = _ruta_ref(body.get("nombre", ""))
    jid = uuid.uuid4().hex[:12]
    TRABAJOS[jid] = {
        "id": jid, "tipo": "calibracion", "estado": "en_cola", "progreso": 0.0,
        "detalle": "en cola", "ref": ruta.name, "lang": body.get("lang", "es"),
        "variante": body.get("variante", "neutro"),
        "fidelidad": max(1, min(int(body.get("fidelidad", 1)), 4)),
        "motor": body.get("motor", "chatterbox"),
        "resultados": [], "parciales": [],
        "cancelar": False, "error": None, "creado": time.time(),
    }
    COLA.put(jid)
    guardar_cola()
    return {"job": jid}


@app.post("/api/ref/evaluar")
def evaluar_refs(body: dict) -> dict:
    refs = sorted(p.name for p in REFS.glob("*.wav")
                  if not p.name.startswith((".", "_")) and not p.stem.endswith("-completa"))
    if not refs:
        raise HTTPException(400, "no hay tomas guardadas")
    jid = uuid.uuid4().hex[:12]
    TRABAJOS[jid] = {
        "id": jid, "tipo": "evaluacion", "estado": "en_cola", "progreso": 0.0,
        "detalle": "en cola", "refs": refs, "lang": body.get("lang", "es"),
        "exag": float(body.get("exag", 0.4)), "variante": body.get("variante", "neutro"),
        "resultados": [], "parciales": [], "cancelar": False, "error": None,
        "creado": time.time(),
    }
    COLA.put(jid)
    guardar_cola()
    return {"job": jid}


@app.post("/api/generar")
def generar(body: dict) -> dict:
    items = body.get("items") or []
    limpio = []
    for i, it in enumerate(items):
        texto = (it.get("texto") or "").strip()
        if texto:
            limpio.append({"nombre": (it.get("nombre") or f"clip-{i+1}").strip(), "texto": texto})
    if not limpio:
        raise HTTPException(400, "el guion está vacío")
    if sum(len(i["texto"]) for i in limpio) > MAX_CHARS:
        raise HTTPException(400, f"el guion supera {MAX_CHARS} caracteres")
    # Este estudio clona una voz, no inventa hablantes: sin referencia no se genera.
    if not body.get("ref"):
        raise HTTPException(400, "elegí una referencia de voz: el motor clona tu voz, no genera voces nuevas")

    jid = uuid.uuid4().hex[:12]
    motor_nombre = str(body.get("motor") or "chatterbox")
    if motor_nombre not in MOTORES_DISPONIBLES:
        raise HTTPException(400, f"motor desconocido: {motor_nombre}")
    if not MOTORES_DISPONIBLES[motor_nombre]():
        raise HTTPException(400, f"el motor {motor_nombre} no está instalado")
    # Lo calibrado en la toma manda: la UI ya no expone estos ajustes.
    calibrada = meta_ref(REFS / str(body.get("ref"))) if body.get("ref") else {}
    TRABAJOS[jid] = {
        "id": jid,
        "estado": "en_cola",
        "progreso": 0.0,
        "detalle": "en cola",
        "items": limpio,
        "motor": motor_nombre,
        "ref": body.get("ref"),
        "lang": body.get("lang", "es"),
        "variante": body.get("variante", "neutro"),
        "fidelidad": max(1, min(int(body.get("fidelidad", 1)), 4)),
        "exag": float(body.get("exag", calibrada.get("exag") or 0.4)),
        "cfg": float(body.get("cfg", 0.5)),
        "seed": int(body.get("seed", 42)),
        "tau": float(body.get("tau", calibrada.get("tau") or 0.10)),
        "lufs": float(body.get("lufs", -14)),
        "pausas": voz.normalizar_pausas(body.get("pausas")),
        "cortar_comas": bool(body.get("cortar_comas", False)),
        "recortar_silencio": bool(body.get("recortar_silencio", True)),
        "silencio_max_ms": int(body.get("silencio_max_ms", 350)),
        "resultados": [],
        "parciales": [],
        "cancelar": False,
        "error": None,
        "creado": time.time(),
    }
    COLA.put(jid)
    guardar_cola()
    return {"job": jid, "estado": "en_cola"}


@app.post("/api/transcribir")
async def api_transcribir(archivo: UploadFile = File(...), lang: str = Form("es")) -> dict:
    sufijo = Path(archivo.filename or "audio.wav").suffix or ".wav"
    tmp = Path(tempfile.gettempdir()) / f"tx-{uuid.uuid4().hex}{sufijo}"
    with tmp.open("wb") as f:
        shutil.copyfileobj(archivo.file, f)
    if tmp.stat().st_size < 2000:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, "el archivo llegó vacío")
    if tmp.stat().st_size > 120 * 1024 * 1024:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, "el archivo supera 120 MB")

    jid = uuid.uuid4().hex[:12]
    TRABAJOS[jid] = {
        "id": jid, "tipo": "transcripcion", "estado": "en_cola", "progreso": 0.0,
        "detalle": "en cola", "ruta": str(tmp), "lang": lang, "creado": time.time(),
    }
    COLA_TX.put(jid)
    return {"job": jid, "estado": "en_cola"}


@app.post("/api/job/{jid}/cancelar")
def cancelar(jid: str) -> dict:
    j = TRABAJOS.get(jid)
    if not j:
        raise HTTPException(404, "trabajo no encontrado")
    if j["estado"] in ("listo", "error", "cancelado"):
        return {"ok": False, "estado": j["estado"]}
    j["cancelar"] = True
    if j["estado"] == "en_cola":
        # Todavía no arrancó: se marca cancelado ya, sin esperar al worker.
        j["estado"] = "cancelado"
        j["detalle"] = "cancelado antes de empezar"
    guardar_cola()
    return {"ok": True, "estado": j["estado"]}


@app.get("/api/job/{jid}")
def job(jid: str) -> dict:
    j = TRABAJOS.get(jid)
    if not j:
        raise HTTPException(404, "trabajo no encontrado")
    return {k: v for k, v in j.items() if k not in ("items", "ruta")}


@app.delete("/api/ref/{nombre}")
def borrar_ref(nombre: str) -> dict:
    nombre = Path(nombre).name
    if not re.fullmatch(r"[A-Za-z0-9._-]+\.wav", nombre):
        raise HTTPException(400, "nombre inválido")
    ruta = REFS / nombre
    if not ruta.exists():
        raise HTTPException(404, "toma no encontrada")

    for j in TRABAJOS.values():
        if j.get("estado") in ("en_cola", "generando") and j.get("ref") == nombre:
            raise HTTPException(409, "hay una generación en curso con esta toma")

    ruta.unlink()
    ruta.with_suffix(".json").unlink(missing_ok=True)

    ajustes = cargar_ajustes()
    if ajustes.get("ref") == nombre:
        ajustes["ref"] = None
        _escribir_json(AJUSTES_FILE, ajustes)

    return {"ok": True, "nombre": nombre}


@app.get("/api/historial")
def api_historial() -> dict:
    return {"clips": historial()}


@app.get("/api/ajustes")
def api_ajustes() -> dict:
    return cargar_ajustes()


@app.post("/api/ajustes")
def api_guardar_ajustes(body: dict) -> dict:
    return guardar_ajustes(body or {})


@app.get("/api/trabajos")
def api_trabajos() -> dict:
    """Cola de generación: los activos y los terminados en los últimos 10 min.

    La cola es una sola (una generación a la vez, la CPU manda), pero el cliente
    puede encolar varios trabajos y ver el avance de cada uno.
    """
    ahora = time.time()
    salida = []
    for j in TRABAJOS.values():
        if j.get("tipo") in ("transcripcion", "calibracion", "evaluacion"):
            continue
        fin = j.get("fin") or j.get("creado", 0)
        activo = j.get("estado") in ("en_cola", "generando")
        if not activo and ahora - fin > 600:
            continue
        d = {k: v for k, v in j.items() if k not in ("items", "ruta")}
        d["n_items"] = len(j.get("items") or [])
        salida.append(d)
    vistos = {j.get("id") for j in salida}
    for h in _leer_json(HISTORIAL_FILE, []):
        if h.get("id") in vistos:
            continue
        fin = h.get("fin") or h.get("creado", 0)
        if ahora - fin > 6 * 3600:
            continue
        h = dict(h)
        h["n_items"] = h.get("n_items") or 0
        salida.append(h)

    salida.sort(key=lambda j: j.get("creado", 0))
    return {"trabajos": salida, "cola": COLA.qsize()}


@app.delete("/api/historial/{nombre}")
def borrar(nombre: str) -> dict:
    if not re.fullmatch(r"[a-z0-9-]+", nombre):
        raise HTTPException(400, "nombre inválido")
    for ext in (".mp3", ".srt", ".wav", ".json", ".mp4"):
        (OUT / f"{nombre}{ext}").unlink(missing_ok=True)
    return {"ok": True}


app.mount("/files/refs", StaticFiles(directory=REFS), name="refs")
app.mount("/files/salida", StaticFiles(directory=OUT), name="salida")
app.mount("/web", StaticFiles(directory=WEB), name="web")
