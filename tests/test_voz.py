"""Tests de las piezas puras: no cargan modelos ni usan red."""

import pathlib
import sys

import numpy as np
import soundfile as sf

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import guiones  # noqa: E402
import voz  # noqa: E402


# ------------------------------------------------------------------ troceado

def test_partir_trozos_respeta_puntuacion():
    assert [t for t, _ in voz.partir_trozos("Uno. Dos, tres; cuatro!")] == [
        "Uno.", "Dos, tres; cuatro!"
    ]


def test_partir_trozos_marca_el_tipo_de_pausa():
    trozos = voz.partir_trozos("Hola. Chau.\n\nOtro.")
    assert [t for t, _ in trozos] == ["Hola.", "Chau.", "Otro."]
    assert trozos[0][1] == "frase"
    assert trozos[1][1] == "parrafo"
    assert trozos[2][1] == "frase"


def test_partir_trozos_corta_por_coma_si_se_pide():
    assert len(voz.partir_trozos("Uno, dos, tres.", cortar_comas=True)) == 3
    assert len(voz.partir_trozos("Uno, dos, tres.")) == 1


def test_partir_trozos_respeta_el_maximo():
    largo = "palabra " * 60 + "."
    assert all(len(t) <= 180 for t, _ in voz.partir_trozos(largo))


# -------------------------------------------------------------------- pausas

def test_normalizar_pausas_mezcla_y_acota():
    p = voz.normalizar_pausas({"frase": -1, "coma": 99})
    assert p["frase"] == 0.0
    assert p["coma"] == 3.0
    assert p["parrafo"] == voz.PAUSAS["parrafo"]


# ----------------------------------------------------------------------- srt

def test_srt_arranca_en_cero_y_suma_bien(tmp_path):
    dst = tmp_path / "x.srt"
    voz.escribir_srt(dst, ["Primera frase.", "Segunda frase."], [2.0, 3.0])
    texto = dst.read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:02,000" in texto
    assert "00:00:02,000 --> 00:00:05,000" in texto


def test_srt_corta_frases_largas_en_varios_cues(tmp_path):
    dst = tmp_path / "y.srt"
    voz.escribir_srt(dst, [" ".join(["palabra"] * 20) + "."], [6.0])
    assert dst.read_text(encoding="utf-8").count("-->") >= 3


# --------------------------------------------------------------- regionalismo

def test_regionalizar_argentino():
    assert voz.regionalizar("Tú tienes un móvil.", "argentina") == "Vos tenés un celular."


def test_regionalizar_no_toca_otras_variedades():
    assert voz.regionalizar("Tú tienes un móvil.", "latam") == "Tú tienes un móvil."


def test_regionalizar_no_cambia_genero_del_articulo():
    # "ordenador" (masc) → "computadora" (fem) rompería "un ordenador"
    assert "ordenador" in voz.regionalizar("Tienes un ordenador.", "argentina")


# -------------------------------------------------------------------- guiones

def test_guion_es_determinista_y_cambia_con_la_variante():
    a = guiones.generar("café de especialidad", "educar", 30, 0)
    b = guiones.generar("café de especialidad", "educar", 30, 0)
    c = guiones.generar("café de especialidad", "educar", 30, 1)
    assert a["lineas"] == b["lineas"]
    assert a["lineas"] != c["lineas"]
    assert len(a["lineas"]) == 5


def test_guion_rechaza_tema_vacio():
    try:
        guiones.generar("   ", "educar", 30, 0)
    except ValueError:
        return
    raise AssertionError("un tema vacío debería fallar")


# ------------------------------------------------------------------ análisis

def test_analisis_marca_una_toma_corta(tmp_path):
    p = tmp_path / "corta.wav"
    sr = 24000
    t = np.linspace(0, 1.0, sr, endpoint=False)
    sf.write(p, 0.2 * np.sin(2 * np.pi * 120 * t), sr)
    a = voz.analizar_referencia(p)
    assert a["veredicto"] == "malo"
    assert any("menos de 3" in aviso for aviso in a["avisos"])
