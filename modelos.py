"""Catálogo de modelos TTS: tamaño, licencia y viabilidad en este equipo.

Los tiempos son estimaciones para un clip de 30 s en un Ryzen 5 5600G (6
núcleos, sin GPU). Los tres primeros están medidos; el resto se extrapola por
cantidad de parámetros y tipo de arquitectura.
"""

from __future__ import annotations

CATALOGO = [
    {
        "id": "chatterbox", "nombre": "Chatterbox", "version": "Multilingual V3",
        "params": "0,5B", "gb": 3.2, "licencia": "MIT", "comercial": True,
        "idiomas": "23", "clona": True, "rtf": 6.5, "medido": True,
        "repo": "ResembleAI/chatterbox",
    },
    {
        "id": "openvoice", "nombre": "OpenVoice V2", "version": "MeloTTS ES",
        "params": "0,2B", "gb": 0.33, "licencia": "MIT", "comercial": True,
        "idiomas": "1 (es)", "clona": True, "rtf": 3.3, "medido": True,
        "repo": "myshell-ai/OpenVoice",
    },
    {
        "id": "qwen", "nombre": "Qwen3-TTS", "version": "0.6B Base",
        "params": "0,6B", "gb": 2.5, "licencia": "Apache-2.0", "comercial": True,
        "idiomas": "10", "clona": True, "rtf": 14.7, "medido": True,
        "repo": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
    },
    {
        "id": "qwen17", "nombre": "Qwen3-TTS", "version": "1.7B Base",
        "params": "1,7B", "gb": 4.5, "licencia": "Apache-2.0", "comercial": True,
        "idiomas": "10", "clona": True, "rtf": 42, "medido": False,
        "repo": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
    },
    {
        "id": "voxcpm2", "nombre": "VoxCPM2", "version": "0.5B",
        "params": "0,5B", "gb": 5.0, "licencia": "Apache-2.0", "comercial": True,
        "idiomas": "30", "clona": True, "rtf": 14, "medido": False,
        "repo": "openbmb/VoxCPM2",
    },
    {
        "id": "cosyvoice3", "nombre": "Fun-CosyVoice 3", "version": "0.5B (2512)",
        "params": "0,5B", "gb": 9.8, "licencia": "Apache-2.0", "comercial": True,
        "idiomas": "9", "clona": True, "rtf": 30, "medido": False,
        "repo": "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
    },
    {
        "id": "pocket", "nombre": "Pocket TTS", "version": "Kyutai",
        "params": "0,1B", "gb": 18.1, "licencia": "CC-BY-4.0", "comercial": True,
        "idiomas": "7", "clona": True, "rtf": 2.5, "medido": False,
        "repo": "kyutai/pocket-tts", "gated": True,
    },
    {
        "id": "neutts", "nombre": "NeuTTS Nano", "version": "Spanish",
        "params": "0,23B", "gb": 1.0, "licencia": "NeuTTS Open", "comercial": None,
        "idiomas": "1 (es)", "clona": True, "rtf": 4, "medido": False,
        "repo": "neuphonic/neutts-nano-spanish", "gated": True,
    },
    {
        "id": "xtts", "nombre": "XTTS v2", "version": "Coqui",
        "params": "0,5B", "gb": 2.1, "licencia": "CPML", "comercial": False,
        "idiomas": "17", "clona": True, "rtf": 8, "medido": False,
        "repo": "coqui/XTTS-v2",
    },
    {
        "id": "f5", "nombre": "F5-TTS", "version": "Base",
        "params": "0,34B", "gb": 6.7, "licencia": "CC-BY-NC", "comercial": False,
        "idiomas": "multi", "clona": True, "rtf": 12, "medido": False,
        "repo": "SWivid/F5-TTS",
    },
    {
        "id": "kokoro", "nombre": "Kokoro", "version": "82M",
        "params": "0,08B", "gb": 0.3, "licencia": "Apache-2.0", "comercial": True,
        "idiomas": "9", "clona": False, "rtf": 0.1, "medido": False,
        "repo": "hexgrad/Kokoro-82M",
    },
]


def evaluar(modelo: dict, instalados: set[str]) -> dict:
    """Agrega estado, minutos por clip de 30 s y semáforo."""
    minutos = modelo["rtf"] * 30 / 60
    m = dict(modelo)
    m["instalado"] = modelo["id"] in instalados
    m["min_clip"] = round(minutos, 1)

    if not modelo["clona"]:
        m["semaforo"], m["motivo"] = "rojo", "no clona voces"
    elif modelo.get("comercial") is None:
        m["semaforo"], m["motivo"] = "amarillo", "licencia propia: revisar antes de monetizar"
    elif not modelo["comercial"]:
        m["semaforo"], m["motivo"] = "rojo", "licencia no comercial"
    elif minutos > 20:
        m["semaforo"], m["motivo"] = "rojo", f"~{minutos:.0f} min por clip de 30 s"
    elif modelo.get("gated"):
        m["semaforo"], m["motivo"] = "amarillo", "requiere cuenta de Hugging Face"
    elif minutos > 8:
        m["semaforo"], m["motivo"] = "amarillo", f"~{minutos:.0f} min por clip de 30 s"
    else:
        m["semaforo"], m["motivo"] = "verde", f"~{minutos:.0f} min por clip de 30 s"
    return m
