# data — исходные данные

| Файл | Что | Как меняется |
|---|---|---|
| `Olimpiady_BVI_100ballov.xlsx` | льготы олимпиадников, приёмная кампания 2026: 17 листов (сводная «База» + подробные листы вузов) | **не редактируется руками**; новый файл — по [data-refresh.md](../docs/runbooks/data-refresh.md) |
| `individual_achievements.csv`, `individual_achievement_limits.csv` | баллы вузов за индивидуальные достижения (ГТО, аттестат с отличием…) и потолок суммы; у каждой строки документ, страница, цитата | вручную или разбором документа вуза; сверка человеком меняет `review` на `reviewed` |
| `olympiad_cards.json` | карточки олимпиад: сайт, формат, классы, этапы, секции-треки; у каждого факта источник и дата проверки ([F-06](../docs/specs/F-06-olympiad-cards.md)) | вручную по официальному сайту олимпиады, проверка человеком в PR; неизвестная олимпиада или профиль останавливает сборку |
| `university_documents.json` | кэш ссылок на документы приёмных комиссий | `just refresh-sources`, коммит PR-ом |

Как XLSX превращается в базу — [docs/architecture/data.md](../docs/architecture/data.md).
Известные проблемы данных — [docs/product/limitations.md](../docs/product/limitations.md).
