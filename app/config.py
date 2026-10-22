from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_url: str = "postgresql+asyncpg://app:app@localhost:5433/app"
    webhook_secret: str = "dev-secret"
    provider_timeout: int = 60          
    watchdog_interval: float = 1.0      
    provider_urls: dict[str, str] = {
        "alpha": "http://localhost:9001",
        "beta": "http://localhost:9002",
    }
    self_url: str = "http://localhost:8000"   
    max_active_tasks: int = 3
    http_timeout: float = 5.0           


settings = Settings()