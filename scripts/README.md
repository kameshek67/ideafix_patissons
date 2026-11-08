# scripts — утилиты

| Скрипт | Что делает | Запуск |
|---|---|---|
| `tasks.py` | задачи `docs/tasks`: доска, что взять, проверка, взять задачу, сменить статус | `just tasks`, `just tasks-next`, `uv run python scripts/tasks.py claim T-012 --owner <ник>` |
| `max_dev_link.py` | ссылка, открывающая сайт в браузере «как из MAX» (подписанные данные запуска) | `just max-link --start diplomas` |
| `compare_with_prototype.py` | сверка ответов API с прототипом (тег `prototype-v1` на :8000) | `just compare` |
| `export_reports.py` | сообщения «Нашли ошибку в данных» в CSV (новые или `--all`, `--mark-seen`) | `just reports > reports.csv` |
