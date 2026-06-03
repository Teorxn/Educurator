# Educurator Backend

Guia rapida para levantar el backend con Docker, correr migraciones y seed.

## Requisitos

- Docker Desktop (Windows/Mac) o Docker Engine (Linux)
- Python 3.11 (solo si ejecutas en local sin Docker)

## Configuracion inicial

1. Crea el archivo de entorno:

```bash
cp .env.example .env
```

2. Verifica estos valores en `.env`:

```bash
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/educurator
ALLOWED_ORIGINS=["http://localhost:5173","http://localhost:3000"]
```

## Levantar servicios

```bash
docker compose up -d --build
docker compose ps
```

## Migraciones

```bash
docker compose exec api alembic upgrade head
```

## Seed

```bash
docker compose exec api python seed.py
```

## Verificar salud

```bash
curl http://localhost:8000/health
```

## Notas

- Postgres se expone en el host como `5434:5432` para evitar choques con instalaciones locales.
- Si quieres reiniciar todo desde cero (datos incluidos):

```bash
docker compose down -v
```

## Ejecucion local (sin Docker)

Usa esta opcion si quieres correr el API desde tu maquina y solo usar Docker para la base de datos.

### 1) Entorno virtual

Windows (PowerShell):

```bash
python -m venv .venv
.\.venv\Scripts\activate
```

Windows (Git Bash):

```bash
python -m venv .venv
source .venv/Scripts/activate
```

Linux/Mac:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2) Instalar dependencias

```bash
pip install -r requirements.txt
```

### 3) Ajustar `.env` para local

Si la base esta en Docker, usa el puerto expuesto en el host:

```bash
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/educurator
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
