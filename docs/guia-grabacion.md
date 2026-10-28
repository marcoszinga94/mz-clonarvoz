# Guía de grabación

El modelo no inventa tu timbre: lo **copia** del clip de referencia. Un clip malo
produce un clon genérico por mucho que subas el modelo de gama.

## Qué grabar

| Parámetro | Valor |
|---|---|
| Duración | **20–60 s**; el pipeline usa la toma completa (mínimo 3 s) |
| Micro | El mismo que uses siempre; el del móvil sirve si no hay ruido |
| Distancia | 15–20 cm, fuera del eje de la boca (evita plosivas) |
| Formato | WAV 44.1/48 kHz mono (el pipeline lo pasa a 24 kHz) |
| Sala | Sin reverberación: armario con ropa o habitación con alfombra |
| Ruido | Nada de ventilador, nevera, tráfico, notificaciones |
| Tono | Conversacional, como si explicaras algo a un amigo |

## Qué decir

No leas un texto plano; el modelo copia también la **energía**. Graba algo que
dirías de verdad, con comas y puntos, y una pregunta al final (fuerza entonación):

> "Mira, esto es algo que aprendí después de mucho prueba y error.
> No hace falta tener un estudio para sonar bien. ¿Quieres que te cuente cómo lo hice?"

**Evita** en el clip: susurros, gritos, risas, "ehhh", cambios de volumen, y
cualquier palabra que pronuncies raro (se te queda pegada).

## Si tu micro es regular

Graba 60 s de habla normal, corta los 10 mejores segundos y pásalos por `prep`.
El filtro `afftdn` quita un ruido de fondo constante; **no** quita reverberación
ni clics. Si el audio suena a habitación vacía, vuelve a grabar en otro sitio.

## Cuánto audio usa el modelo

Chatterbox no usa la referencia de forma uniforme:

- **Primeros 6 s**: tokens de estilo (ritmo, entonación).
- **Primeros 10 s**: prompt del decoder (prosodia del arranque).
- **Todo el archivo**: embedding del hablante, promediado por tramos.

Por eso grabar 30–60 s sí mejora el timbre: el promedio es más estable y no
depende de una sola frase. Lo que no aporta es pasar de ~60 s, porque el peso
del promedio se diluye en pausas. La app corta ahí.

Grabar de más sigue siendo útil: si una frase sale trabada, hay otra parte buena
dentro de la misma toma.

## Validación

```bash
./voz record --secs 40    # graba 40 s y deja refs/mi-voz.wav limpio
# o, si ya tienes el archivo:
./voz prep toma.wav -o refs/mi-voz.wav
```

Debe imprimir 20–60 s, 24 000 Hz, medio ≈ −18 dB y pico ≤ −3 dB. Si avisa de
duración o de picos, regraba antes de seguir.

## Elige entre varias tomas

Genera el mismo texto con 2–3 referencias y quédate con la que suene más a ti:

```bash
for r in refs/toma1.wav refs/toma2.wav refs/toma3.wav; do
  ./voz say "Esto es una prueba de mi voz clonada." --voice "$r" -o "salida/$(basename $r .wav).mp3"
done
```
