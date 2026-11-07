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
    # Мини-приложение MAX. Токен бота нужен, чтобы проверять подпись данных запуска
    # (initData) — так API узнаёт пользователя и хранит его дипломы. Без токена «Мои
    # дипломы» работают только на устройстве. Имя бота — для ссылок https://max.ru/<имя>.
    max_bot_token: str | None = None
    max_bot_name: str | None = None
    # сколько секунд после запуска мини-приложения его данные считаются действительными
    max_init_data_ttl: int = 86400
