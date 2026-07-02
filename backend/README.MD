# Educurator Backend

Guía rápida para levantar el stack con Docker, correr migraciones y seed.

## Requisitos

- Docker Desktop (Windows/Mac) o Docker Engine (Linux)
- Python 3.11+ (solo si ejecutas en local sin Docker)

## Configuración inicial

Crea el archivo de entorno desde la **raíz del proyecto**:

```bash
cp .env.example .env
```

Edita `.env` con los valores necesarios (ver `.env.example` como referencia).

## Levantar servicios con Docker

El proyecto usa un solo `docker-compose.yml` en la raíz con perfiles.

### Solo infraestructura (db, chromadb, langfuse)

El frontend y backend se ejecutan en local a través de la terminal:

```bash
docker compose up -d
docker compose ps
```

Esto levanta PostgreSQL (puerto `5434` del host), ChromaDB y Langfuse.

### Stack completo (infra + api)

```bash
docker compose --profile full up -d
```

## Migraciones

Con el stack completo levantado (api incluido):

```bash
docker compose --profile full exec api alembic upgrade head
```

## Seed

```bash
docker compose --profile full exec api python seed.py
```

## Verificar salud

```bash
curl http://localhost:8000/health
```

## Notas

- Postgres se expone en el host como `5434:5432` para evitar choques con instalaciones locales de PostgreSQL.
- El `.env` ya viene configurado para desarrollo local (conexiones a `localhost`).
- Si quieres reiniciar todo desde cero (datos incluidos):

```bash
docker compose down -v
```

---

## Ejecución local (sin Docker para el API)

Usa esta opción si quieres correr el API desde tu máquina y solo usar Docker para la base de datos.

### 1) Entorno virtual

```bash
python -m venv .venv
```

Windows (PowerShell):
```powershell
.\\.venv\Scripts\activate
```

Linux/Mac:
```bash
source .venv/bin/activate
```

### 2) Instalar dependencias

```bash
pip install -r requirements.txt
```

### 3) Iniciar infraestructura

```bash
docker compose up -d
```

### 4) Migraciones y seed (local)

```bash
alembic upgrade head
python seed.py
```

### 5) Levantar el API con uvicorn

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
