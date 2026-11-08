# apps/workers — данные и фоновые задачи

Всё, что работает долго или по расписанию: сборка базы из XLSX, обход сайтов приёмных комиссий,
проверки качества данных, бот MAX и очередь фоновых задач (Dramatiq + RabbitMQ).

## Команды

| Команда | Что делает |
|---|---|
| `just seed` (`uv run olymp-ingest`) | миграции + сборка базы из `data/Olimpiady_BVI_100ballov.xlsx` одной транзакцией |
| `uv run olymp-ingest --if-empty` | собрать, только если база пустая (так стартует Docker) |
| `just validate [--check-links]` | проверки собранной базы; код 1 — есть ошибки ERROR |
| `just refresh-sources [--dry-run] [--only кфу]` | обойти страницы приёмных комиссий, обновить ссылки на документы |
| `just max-check` / `uv run olymp-max-bot run` | проверить токен бота MAX / запустить приветствие бота (long polling) |
| `just ai-cards sites` / `just ai-cards draft --top 50` | сайты олимпиад из перечня РСОШ / ИИ-черновики карточек олимпиад по этим сайтам (F-06) |
| `just worker` | воркер Dramatiq (фоновые задачи refresh-sources и пересборки) |

В Docker: сервис `migrate` собирает базу при первом старте, `worker` — очередь, `bot` — профиль `bot`.

## Устройство

```
src/olymp_workers/
  ingest.py            XLSX → PostgreSQL: адаптеры 13 листов, справочник олимпиад, разбор перечислений,
                       правила «по профилю», связи и полнотекстовый индекс
  university_pages.py  вуз → страница раздела документов (единственный файл, который правят руками)
  refresh_sources.py   обход этих страниц → university_documents + data/university_documents.json
  validate.py          проверки качества данных
  tasks.py             акторы Dramatiq
  max_bot.py           бот MAX: приветствие и подсказка с кнопками мини-приложения и сайта, check
  ai_cards.py          сайты олимпиад (rsr-olymp.ru) → ИИ-черновики карточек; факт без дословной цитаты
                       со страницы отбрасывается
tests/                 итоговые числа сборки на настоящем XLSX; бот — на поддельном API MAX;
                       ИИ-карточки — на поддельных сайте и модели
```

Как устроена сборка и слои данных — [docs/architecture/data.md](../../docs/architecture/data.md).
Как обновлять данные — [docs/runbooks/data-refresh.md](../../docs/runbooks/data-refresh.md).

Сборка не блокирует API: таблицы очищаются `DELETE` (`tables.py`), до коммита сайт видит прежние
данные (T-064).
