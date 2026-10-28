# Modelos y licencias

Revisado en octubre de 2026. Verifica la licencia en el repo antes de monetizar:
las de pesos abiertos cambian con las versiones.

## Recomendado: Chatterbox Multilingual V3

- **Repo:** `resemble-ai/chatterbox` · pesos `ResembleAI/chatterbox`
- **Licencia:** MIT (código y pesos) → uso comercial sin regalías
- **Tamaño:** 0,5B (backbone Llama) + decoder s3gen
- **Idiomas:** 23+, con paquetes específicos para **español de España y LatAm**
- **Clonación:** zero-shot con 5–10 s de referencia
- **Marca de agua:** PerTh incrustada por defecto (declararla es lo correcto)
- **En esta máquina:** RTF ≈ 6,6× en CPU (6 hilos)

Consejos: `exaggeration` 0.3–0.5 para narración; por encima de 0.7 empieza a
sobreactuar y a arrastrar sílabas. `cfg_weight` 0.5 por defecto.

### Packs de español

Resemble publica finetunes de un solo idioma para el mismo modelo base:

| Pack | Repo | Notas |
|---|---|---|
| LatAm / México | `ResembleAI/Chatterbox-Multilingual-es-mx-latam` | el más cercano al rioplatense |
| España | `ResembleAI/Chatterbox-Multilingual-es-es` | castellano peninsular |

Licencia MIT, igual que el modelo base. El acento de la salida combina el pack con
la referencia: si tu referencia es neutra, el resultado también.

## Alternativas

### Kokoro 82M — Apache 2.0
No clona: usa voces preentrenadas (incluye españolas). Es **muy** rápido incluso
en CPU y sorprendentemente natural. Úsalo para borradores, para no gastar 5 min
por iteración, o para clips donde no necesitas tu timbre.

### NeuTTS Air — Apache 2.0
0,5B sobre Qwen, pensado para CPU/móvil, clona con 3 s. **Solo inglés.** Si algún
día haces contenido en inglés, es la opción más ligera.

### XTTS-v2 (Coqui) — CPML, **no comercial**
El estándar de facto para clonar en español desde 2024: zero-shot decente y
fine-tune con 10–30 min de audio que se acerca mucho al original. Más rápido que
Chatterbox en CPU. La licencia **prohíbe uso comercial** y Coqui cerró, así que
el mantenimiento es de la comunidad.

Ruta válida si tu cuenta no monetiza: úsalo para decidir si el proyecto va en
serio, y si va, migra a Chatterbox o paga una licencia.

### F5-TTS — código MIT, **pesos CC-BY-NC**
Calidad alta en español, zero-shot. Los pesos no son comerciales. Misma advertencia.

## Lo que NO es gratis aunque lo parezca

- ElevenLabs / OpenAI TTS: API de pago y no puedes alojarlo.
- "Modelos" de HuggingFace sin licencia explícita: sin licencia = sin permiso.
- Fine-tunes de la comunidad sobre XTTS: heredan la CPML del modelo base.

## Transcripción: Whisper base

- **Pesas:** OpenAI Whisper `base` (MIT), ejecutadas con `faster-whisper` sobre
  CTranslate2 en int8. Mismo resultado, ~4–8× más rápido en CPU.
- **En esta máquina:** 7 s de audio transcriptos en 1,2 s.
- **Uso en el proyecto:** convertir una nota de voz en guion editable, o sacar
  subtítulos de un audio existente (`./voz transcribir x.mp3 -o x.srt`).

## Si necesitas más calidad que zero-shot

Fine-tune de XTTS-v2 (30 min de audio transcrito, ~1 h en una GPU alquilada de
24 GB). Solo tiene sentido si el zero-shot no te convence **y** el uso no es
comercial. Para redes, el zero-shot con buena referencia suele bastar.
