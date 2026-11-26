from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "local"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    app_public_url: str = "http://localhost:3000"
    cors_origins: str = "http://localhost:3000,http://localhost:3001"
    supabase_url: str = "https://xtjwmezfzexvupbfsdqt.supabase.co"
    supabase_jwt_issuer: str = "https://xtjwmezfzexvupbfsdqt.supabase.co/auth/v1"
    supabase_jwks_url: str = (
        "https://xtjwmezfzexvupbfsdqt.supabase.co/auth/v1/.well-known/jwks.json"
    )
    supabase_anon_key: SecretStr | None = Field(default=None, repr=False)
    supabase_jwt_secret: SecretStr | None = Field(default=None, repr=False)
    supabase_service_role_key: SecretStr | None = Field(default=None, repr=False)
    bff_shared_secret: SecretStr | None = Field(default=None, repr=False)
    database_url: SecretStr = Field(
        default=SecretStr("postgresql+asyncpg://graphytion_api:CHANGE_ME@localhost:5432/postgres"),
        repr=False,
    )
    redis_url: SecretStr = Field(default=SecretStr("redis://localhost:6379/0"), repr=False)
    invitation_email_provider: str = "resend"
    resend_api_key: SecretStr | None = Field(default=None, repr=False)
    invitation_from_email: str | None = None
    log_level: str = "INFO"
    internal_worker_token: SecretStr | None = Field(default=None, repr=False)

    @property
    def cors_origin_list(self) -> list[str]:
        return [value.strip().rstrip("/") for value in self.cors_origins.split(",") if value.strip()]

    @property
    def database_url_value(self) -> str:
        return self.database_url.get_secret_value()

    @property
    def redis_url_value(self) -> str:
        return self.redis_url.get_secret_value()

    @property
    def supabase_anon_key_value(self) -> str | None:
        return self.supabase_anon_key.get_secret_value() if self.supabase_anon_key else None

    @property
    def supabase_service_role_key_value(self) -> str | None:
        return (
            self.supabase_service_role_key.get_secret_value()
            if self.supabase_service_role_key
            else None
        )

    @property
    def bff_shared_secret_value(self) -> str | None:
        return self.bff_shared_secret.get_secret_value() if self.bff_shared_secret else None

    @property
    def resend_api_key_value(self) -> str | None:
        return self.resend_api_key.get_secret_value() if self.resend_api_key else None

    @model_validator(mode="after")
    def validate_runtime_configuration(self) -> "Settings":
        if self.app_env.lower() not in {"production", "prod"}:
            return self

        missing = [
            name
            for name, value in (
                ("APP_PUBLIC_URL", self.app_public_url),
                ("CORS_ORIGINS", self.cors_origins),
                ("SUPABASE_ANON_KEY", self.supabase_anon_key_value),
                ("SUPABASE_SERVICE_ROLE_KEY", self.supabase_service_role_key_value),
                ("BFF_SHARED_SECRET", self.bff_shared_secret_value),
                ("RESEND_API_KEY", self.resend_api_key_value),
                ("INVITATION_FROM_EMAIL", self.invitation_from_email),
            )
            if not value
        ]
        if missing:
            raise ValueError("Missing required production settings: " + ", ".join(missing))

        app_url = urlparse(self.app_public_url)
        if app_url.scheme != "https" or not app_url.netloc:
            raise ValueError("APP_PUBLIC_URL must be an absolute HTTPS origin in production")

        origins = self.cors_origin_list
        if not origins or any(urlparse(origin).scheme != "https" or "*" in origin for origin in origins):
            raise ValueError("CORS_ORIGINS must contain explicit HTTPS origins; wildcards are forbidden")
        if app_url.origin not in origins:
            raise ValueError("APP_PUBLIC_URL origin must be included in CORS_ORIGINS")

        db_url = urlparse(self.database_url_value)
        if (
            db_url.scheme not in {"postgresql+asyncpg", "postgresql"}
            or not db_url.hostname
            or db_url.hostname in {"localhost", "127.0.0.1"}
            or db_url.username != "graphytion_api"
            or not db_url.password
            or "CHANGE_ME" in self.database_url_value
        ):
            raise ValueError(
                "DATABASE_URL must use a dedicated non-administrative PostgreSQL login and a real password"
            )
        if "ssl=require" not in self.database_url_value and "sslmode=require" not in self.database_url_value:
            raise ValueError("DATABASE_URL must require TLS with ssl=require")

        redis_url = urlparse(self.redis_url_value)
        if redis_url.scheme != "rediss" or not redis_url.hostname:
            raise ValueError("Production REDIS_URL must use rediss:// TLS")
        if redis_url.hostname in {"localhost", "127.0.0.1"}:
            raise ValueError("Production REDIS_URL cannot point to localhost")

        supabase_host = urlparse(self.supabase_url).hostname
        if supabase_host != "xtjwmezfzexvupbfsdqt.supabase.co":
            raise ValueError("SUPABASE_URL must reference Graphytion Production project xtjwmezfzexvupbfsdqt")
        expected_issuer = f"{self.supabase_url.rstrip('/')}/auth/v1"
        if self.supabase_jwt_issuer.rstrip("/") != expected_issuer:
            raise ValueError("SUPABASE_JWT_ISSUER does not match SUPABASE_URL")
        if self.supabase_jwks_url != f"{expected_issuer}/.well-known/jwks.json":
            raise ValueError("SUPABASE_JWKS_URL does not match SUPABASE_URL")
        if len(self.bff_shared_secret_value or "") < 32:
            raise ValueError("BFF_SHARED_SECRET must contain at least 32 characters")
        if self.invitation_from_email and (
            "@" not in self.invitation_from_email or "example.com" in self.invitation_from_email.lower()
        ):
            raise ValueError("INVITATION_FROM_EMAIL must use a real verified sender domain")
        if self.invitation_email_provider.lower() != "resend":
            raise ValueError("Only the configured Resend invitation provider is supported")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
