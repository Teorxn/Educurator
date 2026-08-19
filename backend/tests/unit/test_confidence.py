"""Tests de la calibración de confianza del chat (app/rag/confidence.py).

Las similitudes usadas aquí son las medidas sobre el corpus real del
proyecto, no valores inventados: 0.13 es el ruido típico y 0.70 el mejor
match observado con paraphrase-multilingual-MiniLM-L12-v2.
"""

import pytest

from app.rag.confidence import compute_confidence

FLOOR = 0.20
CEILING = 0.75


def conf(sims: list[float]) -> float:
    return compute_confidence(sims, floor=FLOOR, ceiling=CEILING)


class TestRangos:
    def test_sin_chunks_es_cero(self):
        assert conf([]) == 0.0

    def test_ruido_puro_da_cero(self):
        # Pregunta sin relación con el corpus: todo por debajo del piso.
        assert conf([0.19, 0.12, 0.10, 0.09, 0.08]) == 0.0

    def test_mejor_match_observado_es_confianza_alta(self):
        # "¿Qué política hay sobre el uso de IA?" → top1 0.695
        assert conf([0.695, 0.50, 0.44, 0.40, 0.35]) >= 0.75

    def test_nunca_supera_uno(self):
        assert conf([0.99, 0.98, 0.97]) == 1.0

    def test_siempre_en_rango(self):
        for sims in ([0.0], [-0.1, 0.3], [0.5] * 10, [1.0, 0.0]):
            assert 0.0 <= conf(sims) <= 1.0


class TestLaColaNoCastiga:
    """El motivo original del bug: promediar el top-K hundía el número."""

    def test_relleno_al_final_no_hunde_una_buena_respuesta(self):
        fuerte = conf([0.70, 0.65, 0.60])
        con_relleno = conf([0.70, 0.65, 0.60, 0.22, 0.21])
        # La media simple caía de 0.65 a 0.476; aquí no debe moverse.
        assert con_relleno == fuerte

    def test_supera_a_la_media_simple(self):
        sims = [0.695, 0.50, 0.44, 0.40, 0.35]
        media_simple = sum(sims) / len(sims)  # 0.477 → el 46% que se veía antes
        assert conf(sims) > media_simple

    def test_el_orden_de_entrada_no_importa(self):
        assert conf([0.2, 0.7, 0.45]) == conf([0.7, 0.45, 0.2])


class TestMonotonia:
    def test_mejor_evidencia_da_mas_confianza(self):
        assert conf([0.70, 0.40, 0.30]) > conf([0.50, 0.40, 0.30])

    def test_mas_corroboracion_da_mas_confianza(self):
        # Mismo mejor chunk, respaldo más fuerte detrás.
        assert conf([0.70, 0.65, 0.60]) > conf([0.70, 0.30, 0.25])

    def test_un_solo_chunk_excelente_sigue_siendo_alto(self):
        # Documento corto: un único chunk, muy pertinente.
        assert conf([0.70]) >= 0.75


class TestRespaldoDeLaRespuesta:
    """El respaldo (respuesta↔contexto) es lo que salva a las genéricas."""

    def test_pregunta_generica_bien_respondida_sube(self):
        # Caso real: "¿Cuáles son los puntos principales de este documento?"
        # La pregunta no se parece al documento (0.356) pero la respuesta sí.
        sims = [0.356, 0.30]
        sin_respaldo = conf(sims)
        con_respaldo = compute_confidence(
            sims, floor=FLOOR, ceiling=CEILING, grounding=0.690
        )
        assert sin_respaldo < 0.35  # el 27% que se veía antes
        assert con_respaldo > 0.55

    def test_respuesta_inventada_no_levanta_la_confianza(self):
        # Control medido: una respuesta ajena al contexto se queda en ~0.14.
        sims = [0.356, 0.30]
        assert compute_confidence(
            sims, floor=FLOOR, ceiling=CEILING, grounding=0.14
        ) < conf(sims)

    def test_sin_respaldo_medible_cae_en_la_pertinencia(self):
        sims = [0.65, 0.50, 0.45]
        assert compute_confidence(sims, floor=FLOOR, ceiling=CEILING, grounding=None) == conf(sims)

    def test_mas_respaldo_nunca_baja_la_confianza(self):
        sims = [0.55, 0.45]
        valores = [
            compute_confidence(sims, floor=FLOOR, ceiling=CEILING, grounding=g)
            for g in (0.2, 0.4, 0.6, 0.8)
        ]
        assert valores == sorted(valores)

    def test_peso_cero_ignora_el_respaldo(self):
        sims = [0.65, 0.50]
        assert (
            compute_confidence(
                sims,
                floor=FLOOR,
                ceiling=CEILING,
                grounding=0.9,
                grounding_weight=0.0,
            )
            == conf(sims)
        )

    def test_peso_fuera_de_rango_se_acota(self):
        sims = [0.65, 0.50]
        # No debe extrapolar ni devolver algo fuera de [0, 1]
        for w in (-2.0, 5.0):
            valor = compute_confidence(
                sims, floor=FLOOR, ceiling=CEILING, grounding=0.7, grounding_weight=w
            )
            assert 0.0 <= valor <= 1.0


class TestAnclasInvalidas:
    def test_floor_mayor_que_ceiling_no_revienta(self):
        # Mala configuración: debe degradar a la señal cruda, no dividir por cero.
        valor = compute_confidence([0.6, 0.5], floor=0.9, ceiling=0.2)
        assert valor == pytest.approx(0.6)

    def test_floor_igual_a_ceiling_no_revienta(self):
        valor = compute_confidence([0.6], floor=0.5, ceiling=0.5)
        assert 0.0 <= valor <= 1.0
