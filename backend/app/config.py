from pydantic import field_validator
from pydantic_settings import BaseSettings


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

    # LLM (opcional — si no se configura, el grafo funciona sin agente)
    OPENAI_API_KEY: str = ""  # También puede ir en env var OPENAI_API_KEY
    GEMINI_API_KEY: str = ""
    HUGGINGFACE_MODEL: str = ""  # Ej: "TinyLlama/TinyLlama-1.1B-Chat-v1.0"

    # ChromaDB
    CHROMADB_HOST: str = "localhost"
    CHROMADB_PORT: int = 8001

    # Redundancy detection
    REDUNDANCY_THRESHOLD: float = (
        0.90  # Cosine similarity threshold for redundancy detection
    )
    MAX_REDUNDANCY_COMPARISONS: int = (
        100_000  # Max comparisons in scan_all_redundancy (prevents O\u00b2 blowup)
    )

    # Langfuse — tracing y observabilidad
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    # Curation pipeline limits
    MAX_DOCS_PER_CURATION: int = 20  # Máx. documentos por corrida de análisis

    # LangGraph checkpoint persistence
    AGENT_CHECKPOINT_DB_PATH: str = "data/checkpoints/curation_graph.sqlite"

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",")]
        return v

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
