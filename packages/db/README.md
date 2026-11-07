# packages/db — модели и миграции

Библиотека `olymp_db`: модели SQLAlchemy 2 и миграции Alembic — **единственное место, где
меняется схема БД**. Ею пользуются API (asyncpg) и сборка базы (psycopg).

```
src/olymp_db/
  models.py        таблицы данных: universities, programs, benefits, olympiads, olympiad_aliases,
                   olympiad_profiles, benefit_olympiads, benefit_keywords, university_documents,
                   search_index, ingest_log, meta; пользователи: max_users, user_diplomas
  session.py       адрес БД (OLYMP_DATABASE_URL), синхронный движок для сборки и миграций
  migrations/      Alembic: 0001_initial_schema, 0002_max_users_and_diplomas
tests/             миграции создают все таблицы, сортировка "C", ограничения CHECK
```

## Команды

```bash
just migrate                      # применить миграции
just migration "добавить таблицу X"   # новая миграция по изменениям models.py — проверь файл руками
uv run pytest packages/db -q      # нужен PostgreSQL (just up)
```

Правила: у текстовых колонок сортировка `"C"` (как в прототипе). Пользовательские таблицы не
ссылаются внешними ключами на таблицы данных — сборка очищает их через `TRUNCATE`.
Модель данных целиком — [docs/architecture/data.md](../../docs/architecture/data.md).
