# apps/web — сайт и мини-приложение MAX

Next.js 16 + React 19: интерфейс «Олимпа» с вкладками «Вузы», «Олимпиады», «Дипломы». Тот же код
работает как мини-приложение мессенджера MAX. Дизайн повторяет прототип
([ADR 0005](../../docs/adr/0005-ui-parity-with-prototype.md)).

## Запуск

```bash
npm install                            # из корня репозитория (npm workspaces)
just api                               # API на :8000 (в другом терминале)
just web                               # http://localhost:3000, /api/v1/* проксируется на API
```

Адрес API — `OLYMP_API_URL` (по умолчанию `http://localhost:8000`). В Docker — сервис `web` (:8080).
Открыть «как из MAX» в обычном браузере: `just max-link --start diplomas`.

## Устройство

```
src/app/            layout.tsx (шрифт, загрузчик MAX Bridge), page.tsx, styles.css — стили и токены прототипа
  s/[token]/       ссылка «Поделиться»: тот же OlympApp, открытый на экране из снимка (noindex)
src/components/
  OlympApp.tsx      корневой экран: вкладки, состояние, запуск по ссылке startapp и /s/<token>
  ShareButton.tsx   «Поделиться»: ссылка готовится заранее, отправка в MAX или браузере
  Toaster.tsx       тосты («Ссылка скопирована»)
  Onboarding.tsx    онбординг при первом запуске: 3 экрана, свайп, шторка с кнопками
  ProgramView.tsx   карточка направления («вуз → олимпиады»)
  OlympiadView.tsx  выдача по олимпиаде и льготы выбранного вуза («олимпиада → вузы»)
  DiplomasView.tsx  вкладка «Дипломы»; DiplomaSheet.tsx — форма-шторка диплома
  useMyDiplomas.ts  где живут дипломы: localStorage или профиль MAX
  MaxProvider.tsx   MAX Bridge: готовность, кнопка «Назад», ссылки, масштаб
  DataTable.tsx     таблица: сортировка, фильтр, выгрузка CSV
  Combo, ui, icons, AboutModal, SourceBlock — общие элементы
src/lib/
  api.ts            все вызовы API (openapi-fetch, типы из @olymp/api-client)
  max.ts            типы и обёртки MAX Bridge
  share.ts          текст сообщения «Поделиться» и выбор способа отправки
  startParam.ts     разбор payload startapp (diplomas, program-<id>, olympiad-<id>, s_<token>)
  diplomas, onboarding, format, table, csv, toast — чистые функции с тестами
src/proxy.ts        передаёт адрес посетителя в API (лимит запросов)
next.config.ts      прокси /api/v1/* → FastAPI, заголовки безопасности
```

Подробнее — [docs/architecture/frontend.md](../../docs/architecture/frontend.md) и
[docs/architecture/max-mini-app.md](../../docs/architecture/max-mini-app.md).

## Команды

```bash
npm test      --workspace olymp-web    # vitest + Testing Library
npm run lint  --workspace olymp-web    # tsc --noEmit
npm run build --workspace olymp-web
```

## Правила разработки

Общие правила — [CONTRIBUTING.md](../../CONTRIBUTING.md).

- **Данные** — только через функции `src/lib/api.ts` и TanStack Query. Типы ответов — `Schemas[...]`
  из `@olymp/api-client`; если нужного типа нет, сначала поменяй API и запусти `just openapi`.
- **Дизайн** повторяет прототип: новые элементы собирай из существующих классов `styles.css` и
  токенов Tailwind-конфига. UI-библиотеки не добавляй, Tailwind не обновляй (3.4.16).
- **MAX**: любой вызов Bridge — через `safely()` и с проверкой `app` из `useMax()`. Без MAX функция
  должна работать в браузере (например, «Поделиться» → `navigator.share` или копирование).
- **Логику** выноси в чистые функции `src/lib/` и покрывай тестами. Компонентные тесты мокают
  `@/lib/api` (см. `OlympApp.test.tsx`, `DiplomasTab.test.tsx`).
- **Тексты** — на русском, обращение на «ты», «ёлочки».
- **Основной экран — телефон** 360–430 px: проверяй вёрстку в узком окне.
- Версия Next.js новая: при сомнениях в API смотри документацию в `node_modules/next/dist/docs/`.
