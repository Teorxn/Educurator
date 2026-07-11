# EduCurator — Estrategia de despliegue y escalado

> Decisiones de arquitectura de despliegue, justificación frente a
> microservicios y ruta de evolución. Complementa la sección "Producción"
> del README y `docker-compose.prod.yml`.

---

## 1. Arquitectura elegida: monolito modular + Docker Compose

EduCurator se despliega como **un stack de Docker Compose en un único
servidor**, detrás de un reverse proxy con TLS automático:

```
Internet ──► Caddy (80/443, TLS Let's Encrypt)
               ├── /api, /auth, /health ──► FastAPI (monolito modular)
               └── /* ──────────────────► nginx (frontend compilado)

Red interna (sin puertos al host):
  FastAPI ──► PostgreSQL ──► también usado por Langfuse
          ──► ChromaDB (vectores)
          ──► Gemini API (externo, rate-limited 4 RPM)
  Langfuse ──► 127.0.0.1:3000 (solo operador, túnel SSH)
```

Las dependencias **con estado ya son servicios separados** (Postgres,
ChromaDB, Langfuse); lo que llamamos "monolito" es solo la capa de
aplicación: API + pipeline del agente, factorizada internamente en
módulos con fronteras claras (`api/`, `agents/`, `rag/`, `tools/`,
`services/`).

## 2. Dónde desplegar

| Opción | Costo | Cuándo elegirla |
|---|---|---|
| **Oracle Cloud Always Free** (ARM 4 cores / 24 GB) | $0 | Primera opción para el proyecto académico; sobra capacidad |
| **Hetzner CPX21 / CX32** (4-8 GB) | €5-8/mes | Mejor precio/rendimiento si Oracle no tiene stock ARM |
| **DigitalOcean 4 GB** + GitHub Student Pack | ~$0 (crédito) | Si el equipo tiene el Student Developer Pack |

**Dimensionamiento mínimo: 4 GB de RAM** (8 GB cómodo). El contenedor de
la API es pesado: PyTorch + sentence-transformers (~1 GB con el modelo
cargado) + tesseract/poppler para OCR.

**Descartados y por qué:**

- **PaaS (Render, Railway, Fly.io)** — cobran por servicio y este stack
  tiene 5 contenedores; los tiers económicos (512 MB-1 GB) no sostienen
  el modelo de embeddings. Resultado: $30-50/mes por lo que un VPS de $8
  hace mejor.
- **Serverless (Vercel, Lambda)** — incompatible de raíz: las corridas
  del agente duran hasta 15 minutos (`CURATION_TIMEOUT_SECONDS=900`),
  corren como background tasks del proceso y el modelo tarda ~7 s en
  cargar. Es exactamente el anti-patrón serverless.

### Pasos de despliegue

```bash
# En el servidor (Ubuntu + Docker instalado):
git clone https://github.com/Teorxn/Educurator.git && cd Educurator
cp .env.example .env
# Editar .env: SECRET_KEY, LANGFUSE_SECRET, LANGFUSE_SALT únicos,
# GEMINI_API_KEY, y DOMAIN=su-dominio.com (DNS apuntando al servidor)

docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
docker compose -f docker-compose.prod.yml exec api python seed.py

# Backups diarios (ver scripts/backup_db.sh):
crontab -e   →   0 3 * * * /ruta/Educurator/scripts/backup_db.sh
```

Caddy obtiene y renueva el certificado de Let's Encrypt automáticamente.

## 3. ¿Por qué NO microservicios?

Decisión explícita y defendible:

1. **La separación que importa ya existe.** BD, vector store,
   observabilidad y LLM ya son procesos/servicios con contratos claros.
   Partir la capa de aplicación añadiría fronteras de red donde hoy hay
   llamadas a función.
2. **Costo real, beneficio nulo a esta escala.** Microservicios implican
   autenticación entre servicios, contratos versionados, N pipelines de
   despliegue, debugging distribuido y duplicar el modelo de embeddings
   (~1 GB de RAM) en cada servicio que lo necesite. Resuelven problemas
   de *organización de equipos grandes* y *escalado independiente* —
   este proyecto no tiene ninguno de los dos.
3. **El acoplamiento interno es bajo.** El grafo LangGraph, el RAG y la
   API se comunican por interfaces de módulo; si mañana hiciera falta
   extraer una pieza, las costuras ya están marcadas.

## 4. Ruta de evolución (cuándo y qué cambiar)

La escalada correcta es **por etapas, guiada por señales** — no
anticipada:

### Etapa 1 (actual) — un servidor, un proceso
Estado actual. Sirve sin problemas a un curso/facultad con uso moderado.

### Etapa 2 — worker con cola (NO son microservicios)
**Señales para activarla:** la API se siente lenta mientras el agente
procesa; corridas que se pierden al reiniciar; varios docentes subiendo
documentos a la vez.

**Cambio:** mover `run_curation` de `BackgroundTasks` a una cola de
tareas (Redis + arq o Celery) con un contenedor `worker` — **mismo
código, mismo repo, mismo compose**; solo se separa el proceso que
ejecuta el pipeline del que atiende HTTP. Los workers escalan con
`docker compose up --scale worker=3`.

### Etapa 3 — réplicas de la API
**Señales:** CPU/latencia saturadas en el proceso HTTP con el worker ya
separado.

**Prerequisitos (ya documentados como limitación conocida):**
- Rate limiting: de memoria del proceso → Redis (o al proxy).
- Checkpointer de LangGraph: de SQLite local → Postgres.

### Etapa 4 — separar servicios de verdad (si algún día aplica)
Solo si aparece un equipo por dominio o un componente con perfil de
carga radicalmente distinto (p. ej. un servicio de OCR/embeddings con
GPU compartido por varios productos). Hasta entonces, **el monolito
modular es la arquitectura correcta, no una deuda.**

## 5. Checklist operativo de producción

- [ ] `SECRET_KEY`, `LANGFUSE_SECRET`, `LANGFUSE_SALT` únicos del entorno
- [ ] `DOMAIN` configurado y DNS apuntando al servidor
- [ ] API key de Gemini de tier pago si habrá usuarios concurrentes
      (el free tier de 4 req/min es el cuello de botella del pipeline)
- [ ] Backups diarios con `scripts/backup_db.sh` en cron (retención 14 días)
- [ ] Actualizaciones: `git pull && docker compose -f docker-compose.prod.yml up -d --build`
      y `alembic upgrade head` si hay migraciones
