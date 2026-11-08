# Обновить данные

## Пересобрать базу из XLSX

```bash
just seed                                   # локально: миграции + olymp-ingest
docker compose run --rm migrate olymp-ingest   # в Docker-стеке
```

Сборка идёт одной транзакцией; API всё это время отвечает прежними данными, новые появляются
разом при коммите (T-064). Кэш
обновится сам (ключ включает время сборки).

После сборки:

```bash
just validate                 # код 1 — есть ошибки уровня ERROR
just validate --check-links   # плюс HTTP-проверка ссылок на документы (долго)
```

## Обновить ссылки на документы вузов (раз в сезон)

```bash
just refresh-sources --dry-run   # посмотреть, что найдётся
just refresh-sources             # записать в БД и data/university_documents.json
just refresh-sources --only кфу  # один вуз
just refresh-sources --insecure  # без проверки TLS, если сайт с сертификатом Минцифры, а его нет в infra/certs
```

Если у вуза сменилась страница раздела «Документы / Олимпиады» — правка в
`apps/workers/src/olymp_workers/university_pages.py` (статусы `verified`, `page`, `guarded`, `todo`).
Обновлённый `data/university_documents.json` коммитится PR-ом.

## Новый XLSX

1. Положи файл вместо `data/Olimpiady_BVI_100ballov.xlsx` в отдельной ветке.
2. `just seed && just validate`, затем `uv run pytest apps/workers` — тест итоговых чисел упадёт:
   это ожидаемо. Сверь новые числа с изменениями в источнике и обнови тест.
3. PR с описанием, что изменилось в данных.
