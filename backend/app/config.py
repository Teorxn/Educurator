from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings

# Ruta absoluta al .env en la raíz del proyecto
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_PATH = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/educurator"
    )

    # JWT
    SECRET_KEY: str = "change-this-secret-key-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # CORS
    ALLOWED_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Upload
    UPLOAD_DIR: str = "data/uploads"
    REFERENCE_DOCS_DIR: str = "data/references"
    MAX_FILE_SIZE: int = 52_428_800  # 50 MB

    # OCR para PDFs escaneados (rutas locales; en Docker vienen en PATH)
    POPPLER_PATH: str = ""  # Ej Windows: C:\...\poppler-25.07.0\Library\bin
    TESSERACT_CMD: str = ""  # Ej Windows: C:\Program Files\Tesseract-OCR\tesseract.exe
    OCR_DPI: int = 200  # 200 basta para texto impreso (~2x más rápido que 300)
    OCR_WORKERS: int = 4  # Páginas OCR en paralelo (tesseract = subproceso)

    # LLM (opcional — si no se configura, el grafo funciona sin agente)
    OPENAI_API_KEY: str = ""  # También puede ir en env var OPENAI_API_KEY
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.1-flash-lite"  # Cambia a gemini-2.5-flash-lite si agotas cuota diaria
    HUGGINGFACE_MODEL: str = ""  # Ej: "TinyLlama/TinyLlama-1.1B-Chat-v1.0"

    # ChromaDB
    CHROMADB_HOST: str = "localhost"
    CHROMADB_PORT: int = 8001

    # Rate limiting de la API (#33) — ventana deslizante por IP
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_LOGIN: str = "5/60"  # intentos de login por IP: 5 cada 60s
    RATE_LIMIT_UPLOAD: str = "20/60"  # subidas por IP: 20 cada 60s

    # Redundancy detection
    REDUNDANCY_THRESHOLD: float = (
        0.90  # Cosine similarity threshold for redundancy detection
    )

    # Comparación contra documentos de referencia (buenas prácticas)
    REFERENCE_SIMILARITY_THRESHOLD: float = 0.35  # Mín. similitud curso↔referencia
    REFERENCE_TOP_K: int = 2  # Referencias recuperadas por chunk curado
    MAX_REFERENCE_PAIRS: int = 6  # Cap de pares enviados al LLM (1 llamada batch)
    MAX_REDUNDANCY_COMPARISONS: int = (
        100_000  # Max comparisons in scan_all_redundancy (prevents O\u00b2 blowup)
    )

    # Langfuse — tracing y observabilidad
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    # Curation pipeline limits
    MAX_DOCS_PER_CURATION: int = 20  # Máx. documentos por corrida de análisis
    CURATION_TIMEOUT_SECONDS: int = 900  # OCR 300dpi + Gemini a 4 RPM superan 300s fácil
    FEEDBACK_CONTEXT_SIZE: int = 5  # HU-16: últimos N feedback_patterns inyectados al agente
    EMBED_CONCURRENCY: int = 4  # Máx. documentos parseados/embebidos en paralelo
    MAX_FAQ_PER_DOC: int = 3  # Máx. FAQs (llamadas al LLM) por documento
    LLM_MAX_CONCURRENCY: int = 2  # Máx. llamadas simultáneas al LLM
    LLM_MAX_RETRIES: int = 4  # Reintentos con backoff ante rate limits (429)

    # LangGraph checkpoint persistence
    AGENT_CHECKPOINT_DB_PATH: str = "data/checkpoints/curation_graph.sqlite"

    # Web search
    WEB_SEARCH_PROVIDER: str = "duckduckgo"  # "tavily" | "duckduckgo"
    TAVILY_API_KEY: str = ""
    WEB_SEARCH_MAX_RESULTS: int = 5
    WEB_SEARCH_TIMEOUT: int = 10  # segundos

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",")]
        return v

    model_config = {"env_file": str(_ENV_PATH), "env_file_encoding": "utf-8"}


settings = Settings()
