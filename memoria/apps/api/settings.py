from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_public_url: str = "http://localhost:8000"
    allowed_uids: str = "*"

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection_prefix: str = "memoria"

    embedding_provider: str = "openai"
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    lyzr_api_key: str = ""
    lyzr_base_url: str = "https://agent-prod.studio.lyzr.ai"
    lyzr_user_id: str = "memoria-demo"
    lyzr_manager_id: str = ""
    lyzr_gatekeeper_id: str = ""
    lyzr_policy_id: str = ""
    lyzr_librarian_id: str = ""
    lyzr_forgetter_id: str = ""
    lyzr_registrar_id: str = ""
    lyzr_analyst_id: str = ""
    lyzr_fallback: str = "openai"

    demo_principal: str = "self"

    @property
    def lyzr_live(self) -> bool:
        return bool(self.lyzr_api_key and self.lyzr_gatekeeper_id and self.lyzr_policy_id)

    @property
    def lyzr_mode(self) -> str:
        return "live" if self.lyzr_live else "fallback"

    def collection_name(self, suffix: str) -> str:
        return f"{self.qdrant_collection_prefix}_{suffix}"

    def uid_allowed(self, uid: str) -> bool:
        if self.allowed_uids.strip() == "*":
            return True
        allowed = {u.strip() for u in self.allowed_uids.split(",") if u.strip()}
        return uid in allowed


@lru_cache
def get_settings() -> Settings:
    return Settings()
