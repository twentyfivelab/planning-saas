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
    demo_password: str = ""
    app_db_user: str = "planning_app"
    app_db_password: str = ""
    # production par défaut : le seed de démonstration est refusé hors development/test
    app_env: str = "production"
    max_upload_bytes: int = 2_000_000
    login_rate_limit: int = 10  # tentatives / minute / IP+email


settings = Settings()
