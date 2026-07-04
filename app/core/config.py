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

    # Public login URL template — utilisé pour générer le lien envoyé dans
    # l'email de bienvenue tenant et l'URL affichée côté super-admin.
    # {slug} est remplacé par le slug du tenant.
    # Default = pattern single-domain (B-Lean) : ?c=<slug> en query param.
    # Flip vers subdomain plus tard sans changer de code :
    #   PUBLIC_LOGIN_URL_TEMPLATE="https://{slug}.college.klassci.com/login"
    PUBLIC_LOGIN_URL_TEMPLATE: str = "https://college.klassci.com/login?c={slug}"

    # Base URL publique du frontend — sert à construire l'URL de vérification
    # encodée dans le QR code des documents officiels :
    #   {PUBLIC_BASE_URL}/verifier/{tenant}/{token}
    # À surcharger via env sur le serveur de démo (ex: http://94.72.96.119).
    PUBLIC_BASE_URL: str = "https://college.klassci.com"

    # Host allowlist — protection CSRF / host header injection
    # Pattern regex matchant les hôtes acceptés en production multi-tenant.
    # Default couvre <tenant>.college.klassci.com (sous-domaines KLASSCI College).
    # Localhost et IPs numériques sont toujours acceptés (dev) en plus du regex.
    ALLOWED_HOST_PATTERN: str = r"^[a-z0-9][a-z0-9\-]{0,61}\.college\.klassci\.com$"
    # Optionnel : liste explicite supplémentaire (CSV via env var)
    EXTRA_ALLOWED_HOSTS: list[str] = []

    # Puppeteer microservice (génération bulletins PDF)
    PUPPETEER_URL: str = "http://localhost:3001"

    # SMTP (email notifications)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_FROM_NAME: str = "KLASSCI College"

    # Twilio (SMS notifications)
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""

    # MailPulse (notifications email + WhatsApp) — fallback quand les settings
    # tenant sont vides. La clé API réelle vit dans school_settings par tenant.
    MAILPULSE_BASE_URL: str = "https://mailpulse-two.vercel.app"
    MAILPULSE_CONTACTS_ENDPOINT: str = "/api/v1/contacts"
    MAILPULSE_MESSAGES_ENDPOINT: str = "/api/v1/messages"
    MAILPULSE_TIMEOUT: int = 20
    MAILPULSE_SENDER_NAME: str = "KLASSCI"
    MAILPULSE_DEFAULT_LANGUAGE: str = "fr"

    # DigitalOcean Spaces (stockage bulletins PDF)
    DO_SPACES_KEY: str | None = None
    DO_SPACES_SECRET: str | None = None
    DO_SPACES_REGION: str = "nyc3"
    DO_SPACES_ENDPOINT: str = "https://nyc3.digitaloceanspaces.com"
    DO_SPACES_BUCKET: str = "klassci-bulletins"

    # Sentry (observabilité — no-op si SENTRY_DSN vide)
    APP_VERSION: str = "0.1.0-alpha"
    SENTRY_DSN: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1
    SENTRY_ENVIRONMENT: str = ""  # défaut: APP_ENV

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )


settings = Settings()
