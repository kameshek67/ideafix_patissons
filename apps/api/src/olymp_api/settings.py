from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OLYMP_", env_file=".env", extra="ignore")

    env: str = "local"
    database_url: str | None = None
    redis_url: str | None = None
    log_level: str = "INFO"
    # Лимит запросов с одного IP: окно в секундах и число запросов. 0 — без лимита.
    rate_limit_window: int = 60
    rate_limit_requests: int = 600
    # Время жизни ответов поиска в Redis. Ключ включает время сборки базы, поэтому
    # после пересборки старый кэш просто перестаёт использоваться.
    cache_ttl: int = 600
