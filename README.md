# EduCurator

Sistema agéntico de curación de bases de conocimiento para cursos universitarios.  
Los docentes suben documentos (PDF, DOCX, TXT), el sistema los procesa con un pipeline RAG y genera sugerencias automáticas de redundancias, conflictos y FAQs para revisión humana.

---

## Stack

| Capa | Tecnología |
|---|---|
| Backend | FastAPI + SQLAlchemy 2.0 (async) + Alembic |
| Base de datos | PostgreSQL 16 |
| Vector store | ChromaDB |
| Embeddings | sentence-transformers (Hugging Face local) |
| Agente (pendiente) | LangGraph |
| Observabilidad | Langfuse |
| Frontend | React 19 + Vite + Tailwind CSS 4 |

---

## Estructura

```
Educurator/
├── frontend/                   # React + Vite + Tailwind
│   └── src/
│       ├── pages/              # Login, Upload, DocList, Review, Analytics
│       ├── components/         # DocBadge, Header, Sidebar
│       └── api/                # Clientes HTTP hacia FastAPI
├── backend/
│   ├── app/
│   │   ├── api/                # Routers: auth, docs, suggestions, analytics
│   │   ├── agents/             # LangGraph workflow (pendiente Sprint 2)
│   │   ├── tools/              # Tool calling (pendiente Sprint 2)
│   │   ├── rag/                # chunker.py, embeddings.py
│   │   ├── models/             # SQLAlchemy models
│   │   ├── schemas/            # Pydantic schemas
│   │   ├── services/           # (pendiente Sprint 2)
│   │   └── utils/              # parser.py, security.py
│   └── alembic/                # Migraciones PostgreSQL
├── data/
│   ├── uploads/                # Archivos subidos por docentes
│   ├── processed/
│   └── archived/
├── docker-compose.yml          # Stack completo: api + db + chromadb + langfuse
└── Dockerfile                  # Build de la API
```

---

## Requisitos previos

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (recomendado)
- Node.js 20+ (solo para correr el frontend en modo dev)
- Python 3.12+ (solo para desarrollo local sin Docker)
- (Opcional) API key de OpenAI, Google Gemini, o modelo local de Hugging Face

---

## Opción A — Levantar con Docker (recomendado)

### 1. Clonar y configurar variables de entorno

```bash
git clone https://github.com/Teorxn/Educurator.git
cd Educurator/backend
cp .env.example .env
```

Editar `backend/.env` y completar (o usar el `.env` de la raíz):

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/educurator
SECRET_KEY=cambia-esto-por-un-secreto-largo
ALLOWED_ORIGINS=["http://localhost:5173"]
UPLOAD_DIR=data/uploads

# LLM — elige SOLO una:
# OPENAI_API_KEY=sk-...
# GEMINI_API_KEY=tu-api-key-de-gemini
# HUGGINGFACE_MODEL=TinyLlama/TinyLlama-1.1B-Chat-v1.0
```

### 2. Levantar el stack

```bash
# Desde la raíz del proyecto
docker-compose up -d
```

Servicios que levanta:

| Servicio | URL local |
|---|---|
| FastAPI API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| PostgreSQL | localhost:5432 |
| ChromaDB | http://localhost:8001 |
| Langfuse | http://localhost:3000 |

### 3. Correr las migraciones

```bash
docker-compose exec api alembic upgrade head
```

### 4. Crear usuarios iniciales (seed)

```bash
docker-compose exec api python seed.py
```

Usuarios creados:

| Email | Password | Rol |
|---|---|---|
| admin@educurator.dev | admin1234 | admin |
| instructor@educurator.dev | instructor1234 | instructor |

---

## Opción B — Desarrollo local (sin Docker)

### Backend

```bash
cd backend

# Crear entorno virtual
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

# Instalar dependencias
pip install -r requirements.txt

# Configurar .env
cp .env.example .env
# Editar .env con DATABASE_URL apuntando a Postgres local

# Correr migraciones
alembic upgrade head

# Seed de usuarios
python seed.py

# Iniciar servidor
uvicorn app.main:app --reload --port 8000
```

> **Nota Windows:** Las migraciones usan `psycopg2` (driver síncrono). La API en runtime usa `asyncpg`. Ambos deben estar instalados (están en `requirements.txt`).

### Frontend

```bash
cd frontend
npm install
npm run dev
```

El frontend corre en http://localhost:5173 y apunta al backend en `http://localhost:8000`.

---

## Opción C — Docker solo para la base de datos (desarrollo mixto)

Útil para desarrollar backend localmente con Postgres en Docker:

```bash
cd backend
docker-compose up -d db chromadb
```

Postgres queda en `localhost:5434` (puerto alternativo para no colisionar con instalaciones locales).  
Ajustar `backend/.env`:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/educurator
```

---

## API — Endpoints principales

### Autenticación
```
POST /auth/login          → { access_token, token_type }
```

### Documentos
```
GET  /api/docs            → lista con paginación y filtro por status
GET  /api/docs/{id}       → detalle de un documento
POST /api/docs/upload     → subir PDF, DOCX o TXT (max 50 MB)
PATCH /api/docs/{id}      → cambiar status manualmente
GET  /api/docs/{id}/history → historial de cambios (audit trail)
```

### Sugerencias
```
GET  /api/suggestions              → lista con filtros (status, type, document_id)
POST /api/suggestions/{id}/approve → aprobar (escribe history + feedback_pattern)
POST /api/suggestions/{id}/reject  → rechazar con motivo obligatorio
POST /api/suggestions/{id}/feedback → retroalimentación adicional
```

### Analytics
```
GET /api/analytics   → KPIs: total docs, por estado, sugerencias, tasa aprobación
```

### Admin (rol admin requerido)
```
GET   /api/users           → listar usuarios
POST  /api/users           → crear usuario
PATCH /api/users/{id}/role → cambiar rol
```

### Health
```
GET /health → { status: "ok" }
```

Documentación interactiva completa: **http://localhost:8000/docs**

---

## Base de datos — Tablas

| Tabla | Descripción |
|---|---|
| `users` | Docentes y admins con rol y estado activo |
| `documents` | Documentos subidos con status y path |
| `document_chunks` | Chunks del pipeline RAG (512 tokens, overlap 50) |
| `suggestions` | Sugerencias del agente: redundancy, conflict, faq, update |
| `document_history` | Audit trail inmutable (INSERT only) |
| `feedback_patterns` | Retroalimentación del instructor para mejorar el agente |

### Diagrama simplificado

```
users ──< documents ──< document_chunks
      ──< suggestions ──< feedback_patterns
           │
           └──< document_history
```

---

## Flujo del sistema

```
Docente sube archivo
       │
       ▼
POST /api/docs/upload
  → valida MIME (no confía en extensión)
  → guarda en data/uploads/
  → crea registro en documents (status: needs_review)
       │
       ▼
[Pipeline RAG — pendiente wiring]
  → parser.py extrae texto
  → chunker.py divide en chunks de 512 tokens
  → embeddings.py vectoriza y guarda en ChromaDB
  → agente LangGraph detecta redundancias/conflictos
  → crea Suggestion(s) en DB
       │
       ▼
Docente revisa en /review
  → aprueba o rechaza con motivo
  → se escribe DocumentHistory
  → se crea FeedbackPattern (para mejorar futuras sugerencias)
```

---

## Variables de entorno — referencia completa

```env
# Base de datos
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/educurator

# JWT
SECRET_KEY=secreto-largo-y-aleatorio
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# CORS
ALLOWED_ORIGINS=["http://localhost:5173","http://localhost:3000"]

# Uploads
UPLOAD_DIR=data/uploads
MAX_FILE_SIZE=52428800        # 50 MB

# LLM — elige SOLO una:
# OPENAI_API_KEY=sk-...
# GEMINI_API_KEY=tu-api-key-de-gemini
# HUGGINGFACE_MODEL=TinyLlama/TinyLlama-1.1B-Chat-v1.0

# Langfuse (Sprint 2)
# LANGFUSE_PUBLIC_KEY=
# LANGFUSE_SECRET_KEY=
```

---

## Comandos útiles

```bash
# Ver logs de la API
docker-compose logs -f api

# Acceder a PostgreSQL
docker-compose exec db psql -U postgres -d educurator

# Revertir todas las migraciones
alembic downgrade base

# Apagar y borrar volúmenes
docker-compose down -v
```

---

## Sprint 2 — Pendiente

- [ ] Agente LangGraph: grafo + nodos + tools
- [ ] 6 tools del agente: search, compare, detect_redundancy, suggest, generate_faq, log
- [ ] Algoritmo de redundancia: coseno > 0.90 con ChromaDB
- [ ] Wiring del pipeline RAG al endpoint de upload
- [ ] Integración Langfuse (trazas automáticas)
- [ ] Analytics UI: gráficas donut + series temporales
- [ ] Tests unitarios e integración
