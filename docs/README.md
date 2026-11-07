# Документация «Олимпа»

| Раздел | Что внутри | Когда читать |
|---|---|---|
| [product/spec.md](product/spec.md) | ТЗ продукта: пользователи, сценарии, требования, что вне рамок | Перед любой фичей |
| [product/glossary.md](product/glossary.md) | БВИ, РСОШ, профиль, слой данных и другие термины | Если непонятно слово |
| [product/limitations.md](product/limitations.md) | Известные ограничения данных и функций | Перед ответом «почему так» |
| [architecture/overview.md](architecture/overview.md) | Компоненты, потоки данных, границы модулей | Первым делом разработчику |
| [architecture/stack.md](architecture/stack.md) | Стек и зачем каждая технология | При выборе библиотеки |
| [architecture/data.md](architecture/data.md) | Модель данных, сборка базы из XLSX, слои | Работа с данными и поиском |
| [architecture/api.md](architecture/api.md) | Эндпоинты, соглашения, кэш, лимиты | Работа с API |
| [architecture/frontend.md](architecture/frontend.md) | Экраны, состояние, дизайн | Работа с сайтом |
| [architecture/max-mini-app.md](architecture/max-mini-app.md) | Мини-приложение MAX: вход, deep links, Bridge | Всё, что связано с MAX |
| [adr/](adr/README.md) | Архитектурные решения и их причины | Прежде чем менять подход |
| [specs/](specs/README.md) | ТЗ фич | Перед работой над фичей |
| [tasks/](tasks/README.md) | Задачи, дорожная карта, протокол взятия задачи | Каждый день |
| [guides/development.md](guides/development.md) | Окружение, запуск, частые проблемы | Первый запуск |
| [guides/testing.md](guides/testing.md) | Пирамида тестов, как писать и запускать | При написании кода |
| [guides/release.md](guides/release.md) | Релиз и hotfix | Перед демо |
| [runbooks/](runbooks/) | Пошаговые инструкции: MAX, обновление данных, деплой | Эксплуатация |
| [review/](review/) | Результаты ревью проекта | Планирование |
| `openapi.json` | Контракт API (генерируется `just openapi`) | Не редактировать руками |

Правила для документации: одна тема — один файл; факты, которые меняются вместе с кодом
(числа сборки, эндпоинты), обновляются в том же PR, что и код.
