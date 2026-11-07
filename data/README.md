# data — исходные данные

| Файл | Что | Как меняется |
|---|---|---|
| `Olimpiady_BVI_100ballov.xlsx` | льготы олимпиадников, приёмная кампания 2026: 17 листов (сводная «База» + подробные листы вузов) | **не редактируется руками**; новый файл — по [data-refresh.md](../docs/runbooks/data-refresh.md) |
| `university_documents.json` | кэш ссылок на документы приёмных комиссий | `just refresh-sources`, коммит PR-ом |

Как XLSX превращается в базу — [docs/architecture/data.md](../docs/architecture/data.md).
Известные проблемы данных — [docs/product/limitations.md](../docs/product/limitations.md).
