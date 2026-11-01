from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ai_provider: str = "ollama"

    openai_api_key: str = ""
    openai_model: str = "gpt-6-astra"

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5:4b-q8_0"
    ollama_timeout_seconds: int = 300
    ollama_num_ctx: int = 4096
    ollama_think: bool = False
    ollama_candidate_review_limit: int = 64
    ollama_candidate_batch_size: int = 16

    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    max_upload_mb: int = 20
    max_pdf_pages: int = 150
    max_analysis_chars: int = 80_000
    data_dir: str = "./data"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    @property
    def root_data_dir(self) -> Path:
        path = Path(self.data_dir).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        (path / "uploads").mkdir(parents=True, exist_ok=True)
        return path

    @property
    def database_path(self) -> Path:
        return self.root_data_dir / "policy_intelligence.sqlite3"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
