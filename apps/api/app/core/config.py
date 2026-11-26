from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    app_env: str = "local"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000,http://localhost:3001"
    supabase_url: str = "https://xtjwmezfzexvupbfsdqt.supabase.co"
    supabase_jwt_issuer: str = "https://xtjwmezfzexvupbfsdqt.supabase.co/auth/v1"
    supabase_jwks_url: str = "https://xtjwmezfzexvupbfsdqt.supabase.co/auth/v1/.well-known/jwks.json"
    supabase_anon_key: str | None = Field(default=None, repr=False)
    supabase_jwt_secret: str | None = Field(default=None, repr=False)
    supabase_service_role_key: str | None = Field(default=None, repr=False)
    database_url: str = Field(default="postgresql+asyncpg://postgres:CHANGE_ME@localhost:5432/postgres", repr=False)
    redis_url: str = "redis://localhost:6379/0"
    log_level: str = "INFO"
    internal_worker_token: str | None = Field(default=None, repr=False)
    @property
    def cors_origin_list(self) -> list[str]:
        return [v.strip() for v in self.cors_origins.split(",") if v.strip()]

@lru_cache
def get_settings() -> Settings:
    return Settings()
settings = get_settings()
