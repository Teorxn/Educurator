# Documentos de prueba para EduCurator

Juego de material de un curso ficticio (**Desarrollo Web Full Stack, ISW-3041**)
con defectos plantados a propósito, para comprobar qué detecta el agente y qué
no.

- `de-referencia/` → súbelos primero, en la pestaña **De referencia**. Son el
  criterio institucional contra el que se contrasta el material.
- `para-curar/` → súbelos después, en la pestaña **Documentos**. Son el material
  del curso, con los defectos.

El orden importa: sin documentos de referencia procesados, el agente sólo puede
detectar problemas *internos* del material (redundancias, contradicciones entre
documentos del curso), no incumplimientos de la normativa.

## Qué hay en cada carpeta

### `de-referencia/` (4 archivos)

| Archivo | Formato | Qué establece |
|---|---|---|
| `reglamento-academico.pdf` | PDF, 2 págs. | Entregas tardías: 3 días hábiles, 10%/día. Nota mínima 3.0/5.0. Asistencia 80%. Ninguna evaluación pasa del 30%. Las rúbricas suman 100%. |
| `lineamientos-evaluacion.txt` | TXT | Rúbricas: mínimo 3 criterios, observables, con 3 niveles de desempeño. Retroalimentación en 5 días hábiles. |
| `guia-estilo-material-docente.txt` | TXT | Un solo término por concepto. Las versiones deben llevar número. La información normativa vive en un único documento. |
| `politica-integridad-ia.txt` | TXT | El uso de IA generativa está **permitido** si se declara. |

### `para-curar/` (8 archivos)

| Archivo | Formato | Papel |
|---|---|---|
| `syllabus-desarrollo-web.txt` | TXT | Documento normativo del curso. Es la fuente de la mayoría de los conflictos. |
| `guia-de-entregas.txt` | TXT | Duplica el syllabus y lo contradice. |
| `modulo-1-html-css.txt` | TXT | Contenido con auto-contradicción numérica y dato desactualizado. |
| `modulo-2-javascript.txt` | TXT | Contenido con inconsistencias de terminología y redundancia interna. |
| `preguntas-frecuentes.txt` | TXT | FAQ que repite y contradice al syllabus. Buen material para generación de FAQs. |
| `rubrica-proyecto-final.docx` | **DOCX** | La pieza con más incumplimientos. Ejercita además la extracción de Word. |
| `cronograma-sesiones.txt` | TXT | **Control limpio**: no contradice nada. |
| `politica-herramientas-curso.txt` | TXT | Repite la prohibición de IA y añade reglas propias. |

## Defectos plantados

### Contradicciones entre documentos del curso

| # | Qué | Dónde |
|---|---|---|
| 1 | **Entregas tardías: 7 días / 5% vs 3 días / 10%** | `syllabus` §4 y `rubrica` vs `guia-de-entregas` §4 |
| 2 | **Peso del proyecto final: 40% vs 35%** | `syllabus` §3, `guia-de-entregas` §1, `rubrica` vs `preguntas-frecuentes` |
| 3 | **Retroalimentación: 5 días vs 15 días** | `preguntas-frecuentes` vs `rubrica` |

### Contradicciones dentro de un mismo documento

| # | Qué | Dónde |
|---|---|---|
| 4 | **El módulo vale 15%… y 20%** | `modulo-1-html-css` §Objetivos vs §6 |
| 5 | **Los criterios de la rúbrica suman 105%** (60% + 45%) | `rubrica-proyecto-final` |

### Inconsistencias de terminología

| # | Qué | Dónde |
|---|---|---|
| 6 | Un mismo concepto con tres nombres: *función flecha*, *arrow function*, *lambda* | `modulo-2-javascript` §2 y §3 |
| 7 | *Propiedad* y *atributo* usados como sinónimos (y declarado explícitamente) | `modulo-2-javascript` §4 |

### Contenido desactualizado

| # | Qué | Dónde |
|---|---|---|
| 8 | «HTML5 y CSS3… la última versión publicada en 2019» | `modulo-1-html-css` §1 |
| 9 | «Node.js 14, que es la versión LTS actual» | `modulo-2-javascript` §6 |

### Redundancias

| # | Qué | Dónde |
|---|---|---|
| 10 | El bloque de evaluación completo, copiado casi literal | `syllabus` §3 ↔ `guia-de-entregas` §1 |
| 11 | La política de asistencia, tres veces | `syllabus` §5, `guia-de-entregas` §5, `preguntas-frecuentes` |
| 12 | La definición de «función», dos veces con distinta redacción | `modulo-2-javascript` §2 y §3 |
| 13 | La prohibición de IA, tres veces | `syllabus` §6, `preguntas-frecuentes`, `politica-herramientas-curso` §3 |
| 14 | Las reglas de trabajo en parejas, dos veces | `preguntas-frecuentes` ↔ `politica-herramientas-curso` §5 |

### Incumplimientos de los documentos de referencia

| # | Qué dice el material | Qué dice la norma |
|---|---|---|
| 15 | Entregas tardías hasta 7 días con 5% | Reglamento art. 12: 3 días hábiles, 10% por día |
| 16 | Asistencia mínima del 70% | Reglamento art. 18: 80% |
| 17 | Proyecto final: 40% de la nota | Reglamento art. 22: ninguna evaluación pasa del 30% |
| 18 | La rúbrica suma 105% | Reglamento art. 27 y Lineamientos 2.3: exactamente 100% |
| 19 | La rúbrica tiene 2 criterios | Lineamientos 2.1: mínimo 3 |
| 20 | «que sea de buena calidad», «que se note el esfuerzo» | Lineamientos 2.2: prohíbe justo esos dos ejemplos |
| 21 | El criterio 2 tiene 2 niveles de desempeño | Lineamientos 2.4: mínimo 3 |
| 22 | Retroalimentación en 15 días hábiles | Lineamientos 3.1: 5 días hábiles |
| 23 | «Queda terminantemente prohibido» el uso de IA | Política de integridad 2.1: permitido si se declara |
| 24 | «la última versión», sin número | Guía de estilo 2.2: hay que indicar la versión concreta |
| 25 | Las políticas repetidas en cuatro documentos | Guía de estilo 3.2: viven en uno solo, el resto lo referencia |

### Controles: esto **no** debería marcarse

- **Nota mínima 3.0/5.0**: coincide en `syllabus`, `guia-de-entregas`,
  `preguntas-frecuentes` y el artículo 15 del reglamento. Si aparece como
  conflicto, es un falso positivo.
- **`cronograma-sesiones.txt`**: no contradice nada ni repite políticas. Si
  genera sugerencias de conflicto, revisa el umbral de similitud.

## Cómo usarlos

1. Sube los cuatro de `de-referencia/` y pulsa **Procesar**. Espera a que
   queden en *Disponible*.
2. Sube los ocho de `para-curar/` (caben en una sola carga: el límite es 10).
3. Pulsa **Analizar todo** y espera a que pasen a *Analizado*.
4. En **Revisión**, contrasta lo que propone el agente con las tablas de
   arriba: lo que encontró, lo que se le pasó y lo que marcó de más.
5. En **Preguntar**, prueba preguntas cuya respuesta esté repartida entre
   documentos, para ver si cita la fuente correcta:
   - «¿Cuántos días tengo para entregar tarde?» (la respuesta correcta
     depende de qué documento gane; debería citar sus fuentes)
   - «¿Cuánto vale el proyecto final?»
   - «¿Puedo usar ChatGPT en los talleres?»
   - «¿Qué pasa si falto a clase?»

> Los datos, el curso, la universidad y la docente son ficticios.
