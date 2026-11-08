from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OLYMP_", env_file=".env", extra="ignore")

    env: str = "local"
    database_url: str | None = None
    # потолок одного запроса к БД и ожидания блокировки, мс: зависание (блокировка таблиц,
    # тяжёлый запрос) становится быстрой ошибкой 503, а не висящим соединением (T-064)
    db_statement_timeout_ms: int = 15_000
    db_lock_timeout_ms: int = 3_000
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
    # ИИ-помощник (F-02). Шлюз работает с любым OpenAI-совместимым провайдером. Без адреса,
    # ключа и модели помощник выключен, остальное приложение работает как обычно.
    llm_enabled: bool = True  # мгновенное отключение, например во время демо
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_fallback_model: str | None = None
    llm_timeout: float = 30
    llm_max_tokens: int = 1500
    # низкая температура — меньше «творчества» и выдумок; None — значение провайдера
    llm_temperature: float | None = 0.2
    llm_top_p: float | None = None
    # OpenRouter: не отправлять запросы провайдерам, которые хранят данные и учатся на них
    llm_deny_data_collection: bool = True
    # общий бюджет обращений к модели в сутки на весь сервис; 0 — без ограничения. Одно сообщение
    # стоит 2–3 обращения, бесплатный OpenRouter даёт около 50 запросов в сутки на аккаунт
    llm_daily_requests: int = 45
    # лимиты сообщений на пользователя MAX, вне MAX — на IP
    assistant_rate_per_minute: int = 10
    assistant_rate_per_day: int = 100
    # ключ подписи контекста диалога помощника (HMAC-SHA256). Без него — случайный ключ на
    # процесс: после рестарта контекст прошлых ответов перестаёт приниматься, и только
    assistant_context_secret: str | None = None
    # «Поделиться»: сколько ссылок можно создать с одного адреса в минуту и всего за сутки
    # (0 — без лимита) и сколько дней живёт ссылка после последнего «Поделиться».
    # Сайт готовит ссылку заранее, когда экран открыт, поэтому лимит в минуту с запасом.
    share_rate_limit: int = 60
    share_daily_limit: int = 20000
    # «Нашли ошибку в данных»: с одного посетителя в час и всего в сутки (T-079)
    report_rate_limit: int = 5
    report_daily_limit: int = 500
    share_ttl_days: int = 90
