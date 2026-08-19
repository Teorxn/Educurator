"""
Confianza del chat RAG: de similitud coseno cruda a un porcentaje legible.

El promedio directo de las similitudes del top-K subestima de forma
sistemática, por dos razones independientes:

1. **La cola del top-K es relleno.** Se recuperan CHAT_TOP_K chunks siempre,
   haya uno o cinco realmente pertinentes. Medido sobre el corpus del
   proyecto, la caída entre el chunk 1 y el 5 es de ~0.21 en mediana: la
   media castiga a una respuesta bien fundamentada por el simple hecho de
   que el recuperador devolvió relleno detrás.

2. **El coseno crudo no es un porcentaje.** Con
   paraphrase-multilingual-MiniLM-L12-v2 (pregunta ↔ pasaje, sin fine-tuning
   asimétrico) un match excelente vive alrededor de 0.70, no de 0.95.
   Enseñarlo tal cual como "70%" ya subestima; enseñar la media de cinco
   como "46%" es engañoso.

3. **La pregunta no siempre se parece a su respuesta.** "Resume este
   documento" no comparte vocabulario con el documento: medir sólo
   pregunta↔contexto dejaba un resumen impecable en 27%. Por eso la
   confianza mira también respuesta↔contexto (ver compute_confidence).

La medición sobre el corpus real (12 documentos) dio estas anclas:

    | pregunta                    | top-1 (mediana) | media top-5 |
    |-----------------------------|-----------------|-------------|
    | respondible por el corpus   | 0.642           | 0.475       |
    | sin relación (ruido)         | 0.136           | 0.073       |

De ahí salen los dos extremos de la escala: por debajo del piso de ruido no
hay evidencia, y el techo práctico del modelo queda apenas por encima del
mejor caso observado para no saturar en 100% (afirmar certeza total sobre
una recuperación semántica sería exagerar).

IMPORTANTE: las anclas son propiedad del MODELO DE EMBEDDINGS, no del
dominio. Si se cambia EMBEDDING_MODEL_NAME hay que volver a medirlas.
"""

import logging

logger = logging.getLogger(__name__)

# Peso de la mejor evidencia frente al respaldo del resto. La respuesta se
# fundamenta sobre todo en el mejor fragmento; los siguientes corroboran.
_TOP_WEIGHT = 0.75
_SUPPORT_WEIGHT = 1.0 - _TOP_WEIGHT

# Cuántos chunks entran en el término de respaldo (incluido el primero).
_SUPPORT_K = 3


def _calibrate(value: float, floor: float, ceiling: float) -> float:
    """Lleva una similitud coseno cruda al rango útil del modelo."""
    return max(0.0, min(1.0, (value - floor) / (ceiling - floor)))


def retrieval_score(similarities: list[float]) -> float:
    """Qué tan pertinente es el material recuperado para la pregunta.

    Pondera por posición en vez de promediar: la respuesta se fundamenta
    sobre todo en el mejor fragmento y los siguientes corroboran, así que el
    relleno del final del top-K no debe castigar.
    """
    sims = sorted(similarities, reverse=True)
    if not sims:
        return 0.0
    support = sum(sims[:_SUPPORT_K]) / len(sims[:_SUPPORT_K])
    return _TOP_WEIGHT * sims[0] + _SUPPORT_WEIGHT * support


def compute_confidence(
    similarities: list[float],
    *,
    floor: float,
    ceiling: float,
    grounding: float | None = None,
    grounding_weight: float = 0.55,
) -> float:
    """Confianza 0.0–1.0 de una respuesta del chat.

    Combina dos señales medidas con el mismo modelo de embeddings:

    - **Pertinencia** (pregunta ↔ contexto): ¿el material recuperado tiene
      que ver con lo que se preguntó?
    - **Respaldo** (respuesta ↔ contexto): ¿lo que se respondió está
      efectivamente en esos documentos?

    La segunda es la que el docente entiende por "confianza" y la que hace
    justicia a las preguntas genéricas. "Resume este documento" no se parece
    al documento (pertinencia 0.33) pero su respuesta sí (respaldo 0.69),
    porque sale de él; medido sobre respuestas reales, el respaldo legítimo
    vive entre 0.55 y 0.82, mientras que una respuesta inventada no pasa de
    0.14. Sin este término, resumir bien un documento se veía como un 27%.

    Args:
        similarities: Similitudes coseno pregunta↔chunk del contexto usado.
        floor: Similitud a partir de la cual empieza a haber evidencia.
        ceiling: Mejor caso alcanzable por el modelo de embeddings.
        grounding: Similitud máxima respuesta↔contexto. None cuando no se
            puede medir (p. ej. sin LLM, donde la "respuesta" son los
            extractos mismos y el respaldo daría 1.0 trivialmente): en ese
            caso la confianza sale sólo de la pertinencia.
        grounding_weight: Peso del respaldo frente a la pertinencia.

    Returns:
        Confianza en [0.0, 1.0], redondeada a 4 decimales.
    """
    sims = sorted(similarities, reverse=True)
    if not sims:
        return 0.0

    if ceiling <= floor:
        # Configuración inválida: mejor devolver la señal cruda acotada que
        # dividir por cero o inventar un número.
        logger.warning(
            "Anclas de confianza inválidas (floor=%.3f >= ceiling=%.3f); "
            "se usa la similitud cruda",
            floor,
            ceiling,
        )
        return round(max(0.0, min(1.0, sims[0])), 4)

    pertinencia = _calibrate(retrieval_score(sims), floor, ceiling)

    if grounding is None:
        return round(pertinencia, 4)

    w = max(0.0, min(1.0, grounding_weight))
    respaldo = _calibrate(grounding, floor, ceiling)
    return round(w * respaldo + (1.0 - w) * pertinencia, 4)
