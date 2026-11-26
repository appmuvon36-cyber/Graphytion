from email.utils import parseaddr
from functools import lru_cache
from urllib.parse import urlparse

from sqlalchemy.engine import make_url

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "production"
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
    supabase_service_role_key: SecretStr | None = Field(
        default=None,
        repr=False,
        validation_alias=AliasChoices("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_ROLE_KEY"),
    )
    bff_shared_secret: SecretStr | None = Field(default=None, repr=False)
    database_url: SecretStr = Field(
        default=SecretStr("postgresql+asyncpg://graphytion_api:CHANGE_ME@localhost:5432/postgres"),
        repr=False,
    )
    redis_url: SecretStr | None = Field(default=None, repr=False)
    invitation_email_provider: str = "resend"
    resend_api_key: SecretStr | None = Field(default=None, repr=False)
    resend_webhook_secret: SecretStr | None = Field(default=None, repr=False)
    invitation_from_email: str | None = None
    log_level: str = "INFO"
    internal_worker_token: SecretStr | None = Field(default=None, repr=False)
    openai_api_key: SecretStr | None = Field(default=None, repr=False)
    llm_model_key: str = "gpt-4.1-mini"
    llm_timeout_seconds: int = Field(default=60, ge=5, le=180)

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            value.strip().rstrip("/") for value in self.cors_origins.split(",") if value.strip()
        ]

    @property
    def database_url_value(self) -> str:
        value = self.database_url.get_secret_value()
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value.removeprefix("postgresql://")
        if value.startswith("postgres://"):
            return "postgresql+asyncpg://" + value.removeprefix("postgres://")
        return value

    @property
    def redis_url_value(self) -> str | None:
        return self.redis_url.get_secret_value() if self.redis_url else None

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

    @property
    def openai_api_key_value(self) -> str | None:
        return self.openai_api_key.get_secret_value() if self.openai_api_key else None

    @property
    def resend_webhook_secret_value(self) -> str | None:
        return self.resend_webhook_secret.get_secret_value() if self.resend_webhook_secret else None

    @model_validator(mode="after")
    def validate_runtime_configuration(self) -> "Settings":
        if self.app_env.lower() not in {"production", "prod"}:
            return self

        missing = [
            name
            for name, value in (
                ("APP_PUBLIC_URL", self.app_public_url),
                ("CORS_ORIGINS", self.cors_origins),
                ("SUPABASE_SERVICE_ROLE_KEY", self.supabase_service_role_key_value),
                ("BFF_SHARED_SECRET", self.bff_shared_secret_value),
            )
            if not value
        ]
        if missing:
            raise ValueError("Missing required production settings: " + ", ".join(missing))

        app_url = urlparse(self.app_public_url)
        if app_url.scheme != "https" or not app_url.netloc:
            raise ValueError("APP_PUBLIC_URL must be an absolute HTTPS origin in production")

        origins = self.cors_origin_list
        if not origins or any(
            urlparse(origin).scheme != "https" or "*" in origin for origin in origins
        ):
            raise ValueError(
                "CORS_ORIGINS must contain explicit HTTPS origins; wildcards are forbidden"
            )
        if f"{app_url.scheme}://{app_url.netloc}" not in origins:
            raise ValueError("APP_PUBLIC_URL origin must be included in CORS_ORIGINS")

        # Parse with SQLAlchemy's URL parser so percent-encoded credentials (including
        # reserved characters in the password) are interpreted consistently with the
        # engine that will open the connection. urllib.parse.urlparse does not decode
        # userinfo and can reject an otherwise valid SQLAlchemy connection URL.
        try:
            db_url = make_url(self.database_url_value)
        except Exception as exc:
            raise ValueError("DATABASE_URL is not a valid SQLAlchemy database URL") from exc

        direct_database = (
            db_url.host == "db.xtjwmezfzexvupbfsdqt.supabase.co"
            and db_url.username == "graphytion_api"
            and db_url.port in (None, 5432)
        )
        pooler_database = (
            db_url.host == "aws-0-ap-northeast-1.pooler.supabase.com"
            and db_url.username == "graphytion_api.xtjwmezfzexvupbfsdqt"
            and db_url.port in (5432, 6543)
        )
        if db_url.drivername != "postgresql+asyncpg":
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg driver")
        if not (direct_database or pooler_database):
            raise ValueError(
                "DATABASE_URL target/login is not the Graphytion dedicated database endpoint "
                "(expected graphytion_api on the direct host or project-scoped Supavisor)"
            )
        if not db_url.password or "CHANGE_ME" in self.database_url_value:
            raise ValueError("DATABASE_URL is missing a real password")
        if not any(
            db_url.query.get(key) == "require" for key in ("ssl", "sslmode")
        ):
            raise ValueError("DATABASE_URL must require TLS with ssl=require")
        if (
            self.supabase_service_role_key_value == self.supabase_anon_key_value
            and self.supabase_anon_key_value
        ):
            raise ValueError("SUPABASE_SERVICE_ROLE_KEY must be distinct from SUPABASE_ANON_KEY")
        if self.supabase_jwt_secret and len(self.supabase_jwt_secret.get_secret_value()) < 32:
            raise ValueError(
                "SUPABASE_JWT_SECRET must contain at least 32 characters when configured"
            )

        supabase_host = urlparse(self.supabase_url).hostname
        if supabase_host != "xtjwmezfzexvupbfsdqt.supabase.co":
            raise ValueError(
                "SUPABASE_URL must reference Graphytion Production project xtjwmezfzexvupbfsdqt"
            )
        expected_issuer = f"{self.supabase_url.rstrip('/')}/auth/v1"
        if self.supabase_jwt_issuer.rstrip("/") != expected_issuer:
            raise ValueError("SUPABASE_JWT_ISSUER does not match SUPABASE_URL")
        if self.supabase_jwks_url != f"{expected_issuer}/.well-known/jwks.json":
            raise ValueError("SUPABASE_JWKS_URL does not match SUPABASE_URL")
        if len(self.bff_shared_secret_value or "") < 32:
            raise ValueError("BFF_SHARED_SECRET must contain at least 32 characters")
        if self.invitation_from_email:
            sender_address = parseaddr(self.invitation_from_email)[1]
            sender_domain = (
                sender_address.rsplit("@", 1)[-1].lower() if "@" in sender_address else ""
            )
            if (
                not sender_address
                or "." not in sender_domain
                or sender_domain in {"example.com", "example.org", "localhost"}
            ):
                raise ValueError(
                    "INVITATION_FROM_EMAIL must use a real sender address on the verified domain"
                )
        if self.invitation_email_provider.lower() != "resend":
            raise ValueError("Only the configured Resend invitation provider is supported")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
