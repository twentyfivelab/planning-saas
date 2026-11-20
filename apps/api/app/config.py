from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../../.env", extra="ignore")

    database_url: str = "postgresql+psycopg://planning_app:x@localhost:5432/planning"
    migration_database_url: str = ""
    redis_url: str = "redis://localhost:6379/0"
    session_cookie_secure: bool = False
    session_ttl_hours: int = 12
    cors_origins: str = "http://localhost:3000"
    opt_execution: str = "rq"  # rq | inline
    slow_request_ms: int = 500  # au-delà : requête journalisée (diagnostic des lenteurs)
    demo_password: str = ""
    app_db_user: str = "planning_app"
    app_db_password: str = ""
    # production par défaut : le seed de démonstration est refusé hors development/test
    app_env: str = "production"
    max_upload_bytes: int = 2_000_000
    login_rate_limit: int = 10  # tentatives / minute / IP+email
    # limitation des tentatives : « redis » (partagée entre les processus de l'API, obligatoire dès qu'il y en a plusieurs) ou « memory »
    rate_limit_backend: str = "memory"
    # requêtes simultanées par processus d'API (≤ connexions du pool, voir main.InflightLimit) ; attente maximale avant « 503 réessayez »
    max_inflight_requests: int = 12
    inflight_wait_s: float = 25.0
    db_pool_size: int = 10
    db_max_overflow: int = 6
    db_pool_timeout_s: float = 10.0


settings = Settings()
