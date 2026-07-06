# EduCurator — Presentación técnica

> Material de apoyo para la presentación: arquitectura, decisiones de diseño,
> guion de demo y métricas. (Issue #31/#32)

---

## 1. El problema

Los cursos universitarios acumulan documentos que se duplican, se contradicen
y quedan desactualizados. Curarlos a mano no escala. EduCurator lo automatiza
**sin quitarle el control al docente**: la IA propone, el humano dispone.

## 2. Arquitectura

```
┌─────────────┐   REST/JWT   ┌──────────────────────────────────────┐
│  React 19   │ ───────────► │  FastAPI (async)                     │
│  (Vite)     │              │   ├─ /api/docs        (upload, CRUD) │
└─────────────┘              │   ├─ /api/suggestions (HITL)         │
                             │   ├─ /api/analysis    (agente)       │
                             │   └─ middleware: rate limit, CORS    │
                             └───────┬──────────────────────────────┘
                                     │ dispara (background)
                             ┌───────▼──────────────────────────────┐
                             │  Agente LangGraph                    │
                             │  9 nodos + subagente ReAct (8 tools) │
                             └──┬──────────┬──────────┬─────────────┘
                                │          │          │
                        ┌───────▼──┐  ┌────▼─────┐  ┌─▼──────────────┐
                        │ Postgres │  │ ChromaDB │  │ LLM (Gemini) + │
                        │ (estado, │  │ (vectores│  │ web: ddgs →    │
                        │ auditoría│  │  + cache)│  │ tavily → wiki  │
                        └──────────┘  └──────────┘  └────────────────┘
```

### El grafo de curación

| # | Nodo | Qué hace |
|---|------|----------|
| 1 | `load_documents` | Toma docs `needs_review` y los marca `processing` |
| 2 | `chunk_and_embed` | Parsea → chunks de 512 tokens → embeddings locales (batch + cache por hash) |
| 3 | `redundancy_detection` | Similitud coseno > 0.90 entre todos los chunks |
| 4 | `inconsistency_detection` | Contradicciones numéricas, estructurales y terminológicas |
| 5 | `web_search` | Valida contra la web (cadena de fallback anti rate-limit) |
| 6 | `react_agent` | LLM con 8 tools; tolerante a fallos de cuota |
| 7 | `faq_generation` | FAQs con LLM (máx. 3/doc) + fallback heurístico |
| 8 | `generate_suggestions` | Persiste todo como sugerencias `pending` |
| 9 | `wait_human_approval` | Devuelve el doc a revisión — nunca publica solo |

## 3. Decisiones de diseño defendibles

1. **Zero hallucinations por diseño** — toda sugerencia exige `source_chunk_ids`
   (evidencia verificable en la UI) y los outputs de tools pasan por guardrails
   Pydantic estrictos (`extra="forbid"`).
2. **Human-in-the-loop real** — el agente solo crea sugerencias `pending`;
   aprobar/rechazar escribe auditoría inmutable (`document_history`, solo INSERT).
3. **Aprendizaje por feedback (HU-16)** — los últimos N rechazos/aprobaciones
   del instructor se inyectan al prompt del agente en cada corrida.
4. **Resiliencia ante el mundo real**:
   - LLM sin cuota → el pipeline degrada a modo heurístico, nunca se cae.
   - DuckDuckGo bloquea → reintentos con backoff → Tavily → Wikipedia.
   - Documento nunca queda atascado: failsafe restaura su estado ante cualquier fallo.
5. **Observabilidad en dos capas** — trazas Langfuse por corrida + histórico
   persistente en `agent_runs` (fecha, duración, resumen, error).
6. **Costo controlado** — embeddings 100% locales (sentence-transformers);
   LLM limitado a 4 RPM y máx. 3 FAQs/doc; cache por hash evita re-embeber.

## 4. Guion de demo (5 minutos)

1. **Login** (`instructor@educurator.dev`) — JWT + roles.
2. **Subir un PDF** → el badge "Procesando" aparece: el agente ya está corriendo.
3. **Ejecuciones del agente** → mostrar la corrida en vivo (estado, duración).
4. **Revisión** → abrir una FAQ generada: mostrar % de confianza, razonamiento
   y **"Ver evidencia"** (el chunk original del que salió — cero alucinación).
5. **Rechazar** una sugerencia con motivo → explicar que ese motivo se inyecta
   al prompt de la siguiente corrida (aprendizaje).
6. **Subir un segundo documento con un párrafo duplicado** → mostrar la
   sugerencia de **redundancia** con los dos chunks y su similitud.
7. **Analytics** → tasa de aprobación y distribución por tipo.
8. Cierre: mostrar Langfuse (traza completa del grafo) si hay tiempo.

## 5. Métricas del proyecto

| Métrica | Valor |
|---|---|
| Nodos del grafo | 9 (+ subagente ReAct) |
| Tools del agente | 8, todas con guardrails de salida |
| Tipos de sugerencia | redundancy, conflict, faq, update |
| Tests | 190+ (unit + integración end-to-end), sin consumo de APIs |
| Corrida típica (1 doc corto) | ~60-90 s con LLM; ~15 s modo heurístico |
| Costo de embeddings | $0 (modelo local multilingüe) |
| Historias de usuario | 19/19 implementadas |

## 6. Trabajo futuro

- TLS/HTTPS en reverse proxy (documentado en README, pendiente de despliegue).
- Rate limiting distribuido (Redis) para múltiples réplicas.
- Re-ranking de sugerencias usando los `feedback_patterns` acumulados.
