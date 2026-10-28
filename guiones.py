"""
Generador de guiones base.

Sin modelos ni red: plantillas con rotación determinista. La misma entrada y la
misma variante devuelven el mismo guion; "otra versión" cambia la variante.
"""

from __future__ import annotations

import hashlib
import re

OBJETIVOS = {
    "educar": "Enseñar algo",
    "vender": "Vender o promocionar",
    "entretener": "Entretener",
    "historia": "Contar una historia",
}

SEGUNDOS = (15, 30, 60)

GANCHOS = {
    "educar": [
        "Nadie te explica esto sobre {tema}, y es más simple de lo que parece.",
        "Si alguna vez te frustró {tema}, esto te va a ahorrar meses.",
        "Hay tres cosas de {tema} que cambian todo, y la tercera casi nadie la aplica.",
        "Lo que aprendí sobre {tema} después de equivocarme muchas veces.",
        "Deja de complicarte con {tema}. Se resuelve con una sola decisión.",
        "Todo lo que te contaron sobre {tema} está incompleto. Falta esta parte.",
    ],
    "vender": [
        "Si {tema} te está costando más de lo que debería, mira esto.",
        "Probé de todo con {tema}. Solo una cosa funcionó de verdad.",
        "El problema no es {tema}. Es cómo lo estás encarando.",
        "Estaba a punto de rendirme con {tema}, y entonces cambié una cosa.",
        "Nadie compra {tema} por la razón que crees. Compra el resultado.",
        "Si ya intentaste con {tema} y no funcionó, el error fue el orden.",
    ],
    "entretener": [
        "Esto me pasó con {tema} y todavía me da risa.",
        "Nadie me creyó cuando conté lo de {tema}.",
        "Tenía todo planeado con {tema}. Salió exactamente al revés.",
        "Mi peor experiencia con {tema} empezó con una frase: tranquilo, es fácil.",
        "Hay una historia sobre {tema} que no le conté a nadie hasta hoy.",
        "Juraré que {tema} me tiene tomado de punto.",
    ],
    "historia": [
        "Hace dos años no sabía nada de {tema}. Hoy vivo de esto.",
        "Todo lo que tengo hoy nació de un fracaso con {tema}.",
        "Me dijeron que {tema} no era para mí. Insistí igual.",
        "La primera vez que intenté {tema} perdí dinero, tiempo y las ganas.",
        "Este video es la versión que me hubiera gustado ver sobre {tema}.",
        "Nadie te cuenta lo que pasa después de que {tema} sale bien.",
    ],
}

DESARROLLOS = {
    "educar": [
        "La mayoría empieza por el final: compra, prueba y cambia de método. El orden correcto es al revés, entender primero qué problema estás resolviendo.",
        "No necesitas más información, necesitas aplicarla una semana y medir. Sin medición, todo se vuelve opinión.",
        "El error más caro es copiar lo que le funcionó a otro. Sirve como mapa, nunca como receta.",
        "Hay una parte aburrida que nadie muestra: repetir lo mismo hasta que salga bien. Ahí está el resultado.",
        "Antes de sumar herramientas, quita una. La mitad de lo que usas solo agrega pasos y ruido.",
        "Piensa en pequeño: una mejora por semana se nota en un mes. Diez mejoras a la vez no se notan nunca.",
    ],
    "vender": [
        "Lo que cambió el resultado fue dejar de improvisar y tener un sistema. Tres pasos, siempre los mismos, sin depender del día que tengas.",
        "No es magia ni suerte: es repetir lo que ya sabes que funciona incluso cuando no tienes ganas.",
        "Y no hace falta invertir más. Hace falta dejar de pagar por cosas que nunca abriste.",
        "El cambio se nota en la primera semana: menos dudas, menos vueltas, menos tiempo perdido.",
        "Lo armé para gente que ya intentó por su cuenta y se cansó de empezar de cero cada vez.",
        "No vendo motivación. Vendo el orden exacto en el que hay que hacer las cosas.",
    ],
    "entretener": [
        "Arranqué convencido, con el plan perfecto. A los diez minutos ya estaba improvisando y fingiendo que sabía lo que hacía.",
        "Lo peor no fue el error. Fue darme cuenta de que el error se veía venir desde el principio.",
        "Al final salió bien, pero por un motivo que no tenía nada que ver con lo que había planeado.",
        "Mi amigo me miró, me dijo que no iba a funcionar, y tenía razón. Todo el mundo tenía razón menos yo.",
        "Lo intenté una segunda vez, convencido de que había aprendido. Spoiler: no había aprendido.",
        "Y en medio del desastre, alguien me preguntó si lo volvería a hacer. Tardé demasiado en contestar.",
    ],
    "historia": [
        "Los primeros meses fueron puro ruido: hacía todo lo que decían los tutoriales y no pasaba nada. El cambio llegó cuando dejé de buscar el atajo.",
        "No hubo un momento épico. Fue un martes, haciendo lo mismo de siempre, cuando el número subió y no volvió a bajar.",
        "Lo que sí cambió fue la constancia: menos ideas nuevas, más repetición de lo que ya funcionaba.",
        "Perdí más de lo que gané el primer año. Lo que me quedó fue el método, y eso no se pierde.",
        "Cada fracaso dejó una pista. El problema era que yo quería la respuesta completa antes de empezar.",
        "Todavía hoy me equivoco. La diferencia es que ahora sé cuándo parar y cuándo insistir.",
    ],
}

CIERRES = {
    "educar": [
        "Si quieres que profundice en {tema}, dime en los comentarios por dónde empiezo.",
        "Guarda este video para cuando te toque resolverlo.",
        "Cuéntame en un comentario cómo lo estás haciendo hoy.",
        "Sígueme si te sirvió, la parte dos va más al detalle.",
    ],
    "vender": [
        "Si quieres el paso a paso, te lo dejo en el enlace de mi perfil.",
        "Escríbeme la palabra quiero y te mando cómo empezar hoy.",
        "Lo tienes en el enlace de mi perfil, sin vueltas.",
        "Si te interesa, responde este video y te cuento si encaja contigo.",
    ],
    "entretener": [
        "¿Te pasó algo parecido con {tema}? Cuéntame.",
        "Si te dio risa, sígueme para la parte dos.",
        "Y así aprendí que {tema} no se planifica tanto como se practica.",
        "Dime si quieres que cuente cómo terminó.",
    ],
    "historia": [
        "Si {tema} se está poniendo difícil, quédate un poco más.",
        "Te cuento el resto en el próximo video.",
        "Guárdalo para cuando quieras abandonar.",
        "Si te identificas, dime en qué parte estás tú.",
    ],
}


def _semilla(texto: str) -> int:
    return int(hashlib.sha256(texto.encode("utf-8")).hexdigest()[:8], 16)


def _elegir(lista: list[str], semilla: int, salto: int) -> str:
    return lista[(semilla + salto * 11) % len(lista)]


def _arreglar(texto: str) -> str:
    """Contracciones del español que las plantillas pueden romper."""
    texto = re.sub(r"\bde el\b", "del", texto)
    texto = re.sub(r"\ba el\b", "al", texto)
    return texto


def _limpiar_tema(tema: str) -> str:
    t = re.sub(r"\s+", " ", (tema or "").strip()).rstrip(".")
    return t[:80]


def generar(tema: str, objetivo: str = "educar", segundos: int = 30,
            variante: int = 0) -> dict:
    tema = _limpiar_tema(tema)
    if not tema:
        raise ValueError("escribe un tema")
    if objetivo not in GANCHOS:
        raise ValueError(f"objetivo desconocido: {objetivo}")
    if segundos not in SEGUNDOS:
        segundos = 30

    semilla = _semilla(f"{tema}|{objetivo}|{variante}")
    cuerpo = {15: 1, 30: 3, 60: 6}[segundos]

    lineas = [_elegir(GANCHOS[objetivo], semilla, 0).format(tema=tema)]
    for i in range(cuerpo):
        lineas.append(_elegir(DESARROLLOS[objetivo], semilla, i + 1).format(tema=tema))
    lineas.append(_elegir(CIERRES[objetivo], semilla, cuerpo + 1).format(tema=tema))

    lineas = [_arreglar(l) for l in lineas]
    palabras = sum(len(l.split()) for l in lineas)
    return {
        "lineas": lineas,
        "tema": tema,
        "objetivo": objetivo,
        "segundos": segundos,
        "variante": variante,
        "palabras": palabras,
        "duracion_estimada": round(palabras / 2.6, 1),
    }
