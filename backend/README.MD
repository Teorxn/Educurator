# Educurator Backend

Guía rápida para levantar el stack con Docker, correr migraciones y seed.

## Requisitos

- Docker Desktop (Windows/Mac) o Docker Engine (Linux)
- Python 3.11+ (solo si ejecutas en local sin Docker)

## Configuración inicial

Crea el archivo de entorno desde la **raíz del proyecto**:

```bash
cd ..  # si estás en backend/
cp .env.example .env
```

Edita `.env` con los valores necesarios (ver `.env.example` como referencia).

## Levantar servicios con Docker

```bash
# Desde el directorio backend/
docker compose up -d db chromadb
docker compose ps
```

Esto levanta PostgreSQL (puerto `5434` del host) y ChromaDB usando las
definiciones del `docker-compose.yml` raíz sin duplicación.

> Si quieres el stack completo (api + langfuse incluidos), usa el compose raíz:
> ```bash
> cd ..
> docker compose up -d
> ```

## Migraciones

Con el stack completo levantado (api incluido):

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

- Postgres se expone en el host como `5434:5432` para evitar choques con instalaciones locales de PostgreSQL.
- Si quieres reiniciar todo desde cero (datos incluidos):

```bash
docker compose down -v
```

---

## Ejecución local (sin Docker)

Usa esta opción si quieres correr el API desde tu máquina y solo usar Docker para la base de datos.

### 1) Entorno virtual

```bash
python -m venv .venv
```

Windows (PowerShell):
```powershell
.\.venv\Scripts\activate
```

Linux/Mac:
```bash
source .venv/bin/activate
```

### 2) Instalar dependencias

```bash
pip install -r requirements.txt
```

### 3) Ajustar `.env` para local

Si la base está en Docker, usa el puerto expuesto en el host:

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
