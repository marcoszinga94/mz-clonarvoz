# ClonarVoz

> Clonación de voz local en CPU con motores TTS de pesos abiertos, app web y CLI.

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Chatterbox](https://img.shields.io/badge/Chatterbox-Multilingual%20V3-6A5ACD)
![CPU](https://img.shields.io/badge/inferencia-CPU-2E8B57)
![ffmpeg](https://img.shields.io/badge/audio-ffmpeg-007808?logo=ffmpeg&logoColor=white)

**Demo:** https://clonarvoz.vercel.app

## Características

- **Clonación zero-shot**: parte de una toma de referencia de 30–60 s; no entrena ni ajusta pesos.
- **App web local**: grabación guiada con vúmetro y análisis de la toma, guiones, cola de generación, historial y descarga de MP3/SRT.
- **CLI completa**: limpieza de referencias, grabación, generación por frase o por lote, transcripción y normalización.
- **Varios motores TTS**: Chatterbox Multilingual V3 por defecto, más OpenVoice V2, Qwen3-TTS y VoxCPM2 desde el catálogo.
- **Transcripción local** con Whisper base mediante `faster-whisper`; convierte audios en guiones editables.
- **Audio listo para redes**: −14 LUFS integrados, pico real −1,5 dBTP, 48 kHz mono y MP3 de 192 kbps.
- **Subtítulos sincronizados**: cada clip puede generar un `.srt` con los tiempos reales de síntesis.
- **Reproducible**: semilla fija, guiones JSON y manifiesto por lote; cada clip guarda sus parámetros.
- **Sin GPU**: la inferencia corre en CPU (6 hilos por defecto); aproximadamente 6–7 minutos de CPU por minuto de audio.

## Stack

| Capa | Tecnología |
| --- | --- |
| Lenguaje | Python 3.11 (entorno `.venv` con `uv`) |
| API y app web | FastAPI + Uvicorn, HTML/CSS/JS sin framework |
| Motores TTS | Chatterbox, OpenVoice V2/MeloTTS, Qwen3-TTS, VoxCPM2 |
| Transcripción | `faster-whisper` (Whisper base, int8 en CPU) |
| Audio | `ffmpeg`, `soundfile`, `numpy` |
| Pruebas | `pytest` |

## Estructura del proyecto

```text
.
├── app / app.ps1          # lanzadores de la app web (Linux / Windows)
├── servidor.py            # API FastAPI, cola de trabajos y generación
├── voz.py                 # CLI principal
├── motor_*.py             # adaptadores de cada motor TTS
├── motores/               # workers aislados de Qwen y VoxCPM
├── modelos.py             # catálogo, licencias y viabilidad por equipo
├── guiones.py             # carga y validación de guiones
├── web/                   # interfaz local (HTML, CSS y JS)
├── guiones/               # guion JSON de ejemplo
├── docs/                  # guía de grabación y licencias de modelos
├── deploy/                # unidad systemd de ejemplo
├── tests/                 # pruebas de las piezas puras
├── setup.sh
└── requirements.txt
```

## Puesta en marcha

### Requisitos

- Linux (probado en Arch/CachyOS); también hay lanzador para Windows.
- `ffmpeg` y `uv`.
- Unos 3 GB de disco para el entorno y los pesos base.
- No requiere GPU.

### Instalación

```bash
./setup.sh
./app
```

`setup.sh` crea un entorno Python 3.11 con PyTorch para CPU, instala las dependencias y descarga los pesos de Chatterbox en el primer uso. `./app` sirve la interfaz en `http://127.0.0.1:8000`.

En Windows, `app.ps1` asume un `.venv` ya creado con `uv` e instala las mismas dependencias.

## Scripts

| Comando | Descripción |
| --- | --- |
| `./setup.sh` | Crea el entorno, instala dependencias y descarga pesos. |
| `./app` | Levanta la app web local y abre el navegador. |
| `./voz prep <audio>` | Limpia y normaliza el clip de referencia. |
| `./voz say "<texto>"` | Genera un clip desde el texto indicado. |
| `./voz batch <guion.json>` | Genera un lote con MP3, SRT y manifiesto. |
| `./voz transcribir <audio>` | Transcribe con Whisper y exporta TXT, JSON o SRT. |
| `./voz guion "<tema>"` | Genera un guion base por plantilla. |
| `./voz post <audio>` | Normaliza un audio existente a −14 LUFS. |
| `pytest` | Ejecuta las pruebas de las piezas puras. |

## Despliegue

El uso previsto es local: la interfaz escucha en `127.0.0.1` y no envía audio ni texto a servicios externos. `deploy/clonarvoz.service` incluye una unidad systemd de usuario para mantenerla activa. `pyproject.toml` declara el entrypoint que espera el builder de Vercel, pero la síntesis necesita CPU local.

## Estado del proyecto

Funcional y en uso sobre CPU. La app web cubre el flujo completo (referencia, guion, generación, subtítulos y descarga), la CLI permite automatizar lotes y el catálogo evalúa cada motor por similitud, tono y tiempo en el equipo local.

## Licencia

Sin licencia definida para el código. Cada motor y sus pesos conservan su licencia original (MIT o Apache-2.0), documentada en `docs/modelos-y-licencias.md` y en el catálogo.

## Autor

Marcos Zingaretti — https://github.com/marcoszinga94
