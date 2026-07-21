# EduCurator

Sistema agéntico de curación de bases de conocimiento para cursos universitarios.
Los docentes suben documentos (PDF, DOCX, TXT), un agente LangGraph los procesa con un pipeline RAG y genera sugerencias de redundancias, conflictos, inconsistencias y FAQs — siempre con evidencia trazable y **revisión humana obligatoria**: el agente nunca modifica contenido oficial.

---

## Stack

| Capa | Tecnología |
|---|---|
| Backend | FastAPI + SQLAlchemy 2.0 (async) + Alembic |
| Base de datos | PostgreSQL 16 |
| Vector store | ChromaDB |
| Embeddings | sentence-transformers (local, multilingüe) |
| Agente | LangGraph (grafo de 9 nodos + subagente ReAct con 8 tools) |
| LLM | Gemini (rate-limited 4 RPM) / OpenAI / HuggingFace — opcional |
| Búsqueda web | ddgs (DuckDuckGo) → Tavily → Wikipedia (cadena de fallback) |
| Observabilidad | Langfuse (trazas) + histórico persistente de ejecuciones |
| Frontend | React 19 + Vite + Tailwind CSS 4 |

---

## El agente

```
START → load_documents ─(sin docs)→ END
          │ (con docs)
          ▼
   chunk_and_embed ──→ redundancy_detection ──┐
          │                                    ├──→ web_search
          └──→ inconsistency_detection ────────┘        │
                                                        ▼
                    react_agent (ReAct + 8 tools, si hay LLM)
                                                        │
                    faq_generation → generate_suggestions
                                                        │
                              wait_human_approval → END
```

**Tools del agente ReAct:** `search_documents`, `compare_content`, `detect_conflict`, `detect_redundancy`, `suggest_update`, `generate_faq_entry`, `search_web`, `log_action`.

**Resiliencia integrada:**
- Si el LLM agota cuota (429), el pipeline continúa en modo heurístico y el documento nunca queda atascado en `processing`.
- Búsqueda web con reintentos + cadena de fallback (`duckduckgo → tavily → wikipedia`).
- Sesión de DB por documento + embeddings en lote con cache por hash.
- El agente aprende del feedback: los últimos N rechazos/aprobaciones del instructor se inyectan a su prompt (HU-16).

---

## Levantar el proyecto

### Requisitos

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Node.js 20+ y Python 3.12+ (para el modo desarrollo local)
- (Opcional) API key de Gemini u OpenAI — sin ella el pipeline corre en modo solo-RAG

### Opción A — Infra en Docker + backend/frontend locales (recomendada para desarrollo)

```bash
git clone https://github.com/Teorxn/Educurator.git
cd Educurator
cp .env.example .env          # completar SECRET_KEY, LANGFUSE_SECRET/SALT

# 1. Infraestructura (Postgres 5434, ChromaDB 8001, Langfuse 3000)
docker compose up -d

# 2. Backend
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows  |  source .venv/bin/activate (Linux/Mac)
pip install -r requirements.txt
cp .env.example .env          # DATABASE_URL → localhost:5434 + GEMINI_API_KEY
alembic upgrade head
python seed.py
uvicorn app.main:app --reload --port 8000

# 3. Frontend (otra terminal)
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

### Opción B — Stack completo en Docker

```bash
docker compose --profile full up -d --build
docker compose exec api alembic upgrade head
docker compose exec api python seed.py
```

| Servicio | URL |
|---|---|
| Frontend | http://localhost:5173 |
| API + Swagger | http://localhost:8000/docs |
| PostgreSQL | localhost:5434 |
| ChromaDB | localhost:8001 |
| Langfuse | http://localhost:3000 |

### Usuarios seed

| Email | Password | Rol |
|---|---|---|
| admin@educurator.dev | admin1234 | admin |
| instructor@educurator.dev | instructor1234 | instructor |

---

## Flujo de uso

1. **Registro / Login** — los docentes se registran con su perfil académico
   (materias, especialidades, cursos), que el agente usa para personalizar
   sus recomendaciones. Un tutorial guiado se abre la primera vez y queda
   accesible desde el header.
2. **Inicio** — panel con análisis recientes, documentos pendientes de
   revisión, métricas generales y la última ejecución del agente.
3. **Subir documentos** — hasta 10 archivos a la vez (PDF/DOCX/TXT, máx.
   50 MB c/u). Cada uno se valida por separado y entra en una cola que el
   worker procesa secuencialmente. El estado se sigue en vivo:
   `En cola → Procesando → Analizado` (o `Error`, con mensaje y reintento).
4. El agente lee, divide, vectoriza, detecta redundancias/conflictos, contrasta
   con los documentos de referencia y propone FAQs — todo como sugerencias
   `pending` con evidencia (chunks fuente), razonamiento y % de confianza.
5. **Revisión** — al terminar el análisis el sistema redirige automáticamente
   a las sugerencias de ese documento (configurable). Lista paginada
   (10/25/50) con filtros por estado, tipo y documento; las aprobadas
   muestran quién y cuándo. Un documento solo puede aprobarse cuando todas
   sus sugerencias fueron revisadas.
6. **Preguntar** — chat en lenguaje natural sobre la base de conocimiento:
   respuestas fundamentadas solo en los documentos, con las fuentes citadas
   (documento + fragmento) y nivel de confianza.
7. **Ejecuciones del agente** — histórico persistente de corridas + diagrama
   del grafo LangGraph + botón para disparar el análisis manualmente.
8. **Analytics** — KPIs, distribución de sugerencias, tasa de aprobación y
   consumo de IA (tokens y costo estimado por operación y modelo).
9. **Administración** (admin) — gestión de usuarios, asignación de roles con
   confirmación y auditoría, y CRUD de roles personalizados.

---

## API — Endpoints principales

```
POST  /auth/login                          → JWT (rate limit: 5/min por IP)
POST  /auth/register                       → registro de docente + perfil académico
GET   /api/users/me · PATCH /api/users/me  → perfil propio (editable)

GET   /api/docs                            → lista (filtros: status, category)
POST  /api/docs/upload                     → subir + auto-curación (rate limit: 20/min)
POST  /api/docs/upload-batch               → hasta 10 documentos por carga
GET   /api/docs/status/all                 → estados para polling (all_final)
POST  /api/docs/{id}/retry                 → reencolar tras un error
GET   /api/docs/{id}/download              → descarga del original
GET   /api/docs/{id}/detail                → metadatos + conteos
GET   /api/docs/{id}                       → detalle
GET   /api/docs/{id}/history               → audit trail inmutable
DELETE /api/docs/{id}                      → eliminar documento

GET   /api/suggestions                     → filtros: status, type, document_id
POST  /api/suggestions/{id}/approve        → aprueba (history + feedback_pattern)
POST  /api/suggestions/{id}/reject         → rechaza con motivo obligatorio
POST  /api/suggestions/{id}/feedback       → comentario libre del instructor

POST  /api/analysis/curate                 → dispara el pipeline (instructor/admin)
GET   /api/analysis/status/{thread_id}     → estado de una corrida
GET   /api/analysis/runs                   → histórico persistente de ejecuciones
GET   /api/analysis/info                   → LLM, tools y tracing configurados

GET   /api/reference-docs                  → corpus de referencia del agente
GET   /api/analytics                       → KPIs y tasa de aprobación
GET   /api/analytics/dashboard             → panel de inicio (agregado)
GET   /api/analytics/tokens                → consumo de tokens y costo estimado
POST  /api/chat                            → preguntas en lenguaje natural (RAG)
GET   /api/roles · POST/PATCH/DELETE       → administración de roles (admin)
GET   /api/users/role-audit                → auditoría de cambios de rol (admin)
GET   /api/users · POST /api/users · PATCH /api/users/{id}/role   (admin)
GET   /health
```

Documentación interactiva: **http://localhost:8000/docs**

---

## Variables de entorno — referencia

```env
# Base de datos (backend local → puerto 5434 del compose)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/educurator

# JWT
SECRET_KEY=secreto-largo-y-aleatorio

# LLM — elige una (sin ninguna, el pipeline corre en modo solo-RAG):
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash-lite     # la cuota free-tier es POR modelo
# OPENAI_API_KEY=sk-...
# HUGGINGFACE_MODEL=TinyLlama/TinyLlama-1.1B-Chat-v1.0

# ChromaDB
CHROMADB_HOST=localhost
CHROMADB_PORT=8001

# Búsqueda web
WEB_SEARCH_PROVIDER=duckduckgo         # o "tavily"
TAVILY_API_KEY=                        # opcional: se inserta en la cadena de fallback

# Pipeline
MAX_DOCS_PER_CURATION=20
EMBED_CONCURRENCY=4                    # docs parseados/embebidos en paralelo
MAX_FAQ_PER_DOC=3                      # FAQs con LLM por documento
LLM_MAX_CONCURRENCY=2
LLM_MAX_RETRIES=4                      # backoff exponencial ante 429
FEEDBACK_CONTEXT_SIZE=5                # patrones de feedback inyectados al agente
REDUNDANCY_THRESHOLD=0.90
MAX_BATCH_UPLOAD=10                    # documentos por carga múltiple

# Chat RAG y costos de IA
CHAT_TOP_K=5
CHAT_MIN_SIMILARITY=0.25
LLM_COST_PER_1K_INPUT_TOKENS=0.0001    # tarifa del modelo configurado
LLM_COST_PER_1K_OUTPUT_TOKENS=0.0004

# Rate limiting de la API
RATE_LIMIT_ENABLED=true
RATE_LIMIT_LOGIN=5/60
RATE_LIMIT_UPLOAD=20/60

# Langfuse (opcional)
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=http://localhost:3000
```

---

## Base de datos

| Tabla | Descripción |
|---|---|
| `users` | Docentes y admins con rol y estado |
| `documents` | Documentos con status, categoría (curated/reference) y path |
| `document_chunks` | Chunks del pipeline RAG (512 tokens, overlap 50) |
| `suggestions` | Sugerencias: redundancy, conflict, faq, update — con evidencia |
| `document_history` | Audit trail inmutable (solo INSERT) |
| `feedback_patterns` | Feedback del instructor → aprendizaje del agente (HU-16) |
| `agent_runs` | Histórico persistente de ejecuciones del agente (HU-19) |
| `roles` | Roles personalizados del sistema (HU-30) |
| `token_usage` | Consumo de tokens y costo por llamada al LLM (HU-32) |

---

## Tests

```bash
cd backend
python -m pytest tests/ -q
```

- Unit tests: parser, chunker, embeddings, tools, guardrails, inconsistencias, rate limiting.
- Integración: flujo completo upload → pipeline → sugerencia → aprobación (`tests/test_integration_flow.py`).
- Los tests **no** consumen cuota de LLM ni servicios externos (todo mockeado).

---

## Producción — stack completo con HTTPS

> 📄 Estrategia completa (dónde desplegar, dimensionamiento, por qué no
> microservicios y ruta de escalado): [docs/despliegue-y-escalado.md](docs/despliegue-y-escalado.md)

Hay un compose de producción listo (`docker-compose.prod.yml`) con Caddy
como reverse proxy (TLS automático), frontend compilado (Vite build +
nginx, no dev server) y todos los servicios internos sin puertos al host:

```bash
# En el .env: SECRET_KEY/LANGFUSE_SECRET/SALT únicos + DOMAIN=midominio.com
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
docker compose -f docker-compose.prod.yml exec api python seed.py
```

- Con `DOMAIN` definido y DNS apuntando al servidor, Caddy obtiene el
  certificado de Let's Encrypt automáticamente.
- Sin `DOMAIN`, sirve `https://localhost` con certificado local
  autofirmado — útil para probar el stack productivo en tu máquina.
- Langfuse queda en `127.0.0.1:3000` (solo el operador, vía túnel SSH).

Checklist de producción:
- [x] Reverse proxy con TLS automático (Caddy + Let's Encrypt)
- [x] Frontend compilado servido como estáticos (nginx multi-stage)
- [x] Servicios internos sin puertos expuestos al host
- [x] Rate limiting de login/upload (middleware propio, configurable por env)
- [x] Rate limiting del LLM (4 RPM Gemini free tier) y de búsqueda web
- [x] Validación MIME real de archivos (magic bytes, no extensión)
- [x] JWT con expiración + roles
- [ ] `SECRET_KEY` y `LANGFUSE_SECRET/SALT` únicos por entorno (manual)
- [ ] Con múltiples réplicas: mover rate limiting a Redis o al proxy

---

## Comandos útiles

```bash
docker compose logs -f api                     # logs de la API
docker compose exec db psql -U postgres -d educurator
alembic upgrade head                           # migraciones
docker compose down -v                         # apagar y borrar volúmenes
```
