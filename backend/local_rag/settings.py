import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseModel):
    database_path: Path = ROOT / "data/rag.sqlite3"
    frontend_dist: Path = ROOT / "frontend/dist"
    embedding_provider: str = "model2vec"
    embedding_model: str = "minishlab/potion-base-2M"
    embedding_config_id: str = "potion-base-2M:cosine:v1"
    llm_provider: str = "ollama"
    llm_model: str = "granite4.2:3b"
    llm_base_url: str = "http://localhost:11434"
    llm_tokenizer_model: str = "ibm-granite/granite-4.2-3b"
    llm_tokenizer_revision: str = "main"
    context_reserve_tokens: int = Field(default=512, ge=128, le=8192)
    embedding_max_tokens: int = Field(default=512, ge=1)
    retrieval_cap: int = Field(default=5, ge=1, le=80)
    context_neighbors: int = Field(default=0, ge=0, le=3)
    context_tokens: int = Field(default=8192, ge=2048, le=131072)
    output_tokens: int = Field(default=768, ge=128, le=4096)
    theme_primary: str = Field(default="#163f3b", pattern=r"^#[0-9a-fA-F]{6}$")
    theme_secondary: str = Field(default="#4059a8", pattern=r"^#[0-9a-fA-F]{6}$")

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env", override=False)
        def path(key, fallback):
            value = Path(os.getenv(key, fallback)).expanduser()
            return value if value.is_absolute() else ROOT / value
        return cls(
            database_path=path("DATABASE_PATH", "./data/rag.sqlite3"),
            frontend_dist=path("FRONTEND_DIST", "./frontend/dist"),
            embedding_provider=os.getenv("EMBEDDING_PROVIDER", "model2vec"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "minishlab/potion-base-2M"),
            embedding_config_id=os.getenv("EMBEDDING_CONFIG_ID", "potion-base-2M:cosine:v1"),
            llm_provider=os.getenv("LLM_PROVIDER", "ollama"),
            llm_model=os.getenv("LLM_MODEL", "granite4.2:3b"),
            llm_base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434"),
            llm_tokenizer_model=os.getenv("LLM_TOKENIZER_MODEL", "ibm-granite/granite-4.2-3b" if os.getenv("LLM_MODEL", "granite4.2:3b") == "granite4.2:3b" else ""),
            llm_tokenizer_revision=os.getenv("LLM_TOKENIZER_REVISION", "main"),
            context_reserve_tokens=os.getenv("LLM_CONTEXT_RESERVE_TOKENS", "512"),
            embedding_max_tokens=os.getenv("EMBEDDING_MAX_TOKENS", "512"),
            retrieval_cap=os.getenv("RETRIEVAL_CAP", "5"),
            context_neighbors=os.getenv("CONTEXT_NEIGHBORS", "0"),
            context_tokens=os.getenv("LLM_CONTEXT_TOKENS", "8192"),
            output_tokens=os.getenv("LLM_MAX_OUTPUT_TOKENS", "768"),
            theme_primary=os.getenv("THEME_PRIMARY", "#163f3b"),
            theme_secondary=os.getenv("THEME_SECONDARY", "#4059a8"),
        )
