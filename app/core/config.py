"""Configuration globale — lue depuis les variables d'environnement / .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Application
    APP_ENV: str = "development"
    APP_NAME: str = "KLASSCI Collège API"
    DEBUG: bool = False

    # Database (template — remplacé par tenant dans database.py)
    DATABASE_URL: str  # ex: mysql+aiomysql://user:pass@host:3306/{tenant}
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # Redis
    REDIS_URL: str  # ex: redis://localhost:6379/0

    # JWT
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # Tenant
    LOCAL_TENANT_ID: str = "local"  # tenant utilisé en dev local

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )


settings = Settings()
