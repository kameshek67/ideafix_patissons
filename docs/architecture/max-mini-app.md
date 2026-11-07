# Мини-приложение MAX

Как подключить бота и получить HTTPS — [runbooks/max-setup.md](../runbooks/max-setup.md).
Решение — [ADR 0006](../adr/0006-max-auth-initdata.md).

## Как сайт понимает, что он в MAX

MAX открывает мини-приложение с данными запуска во фрагменте адреса (`#WebAppData=…`).
Встроенный в `<head>` загрузчик (`MAX_BRIDGE_LOADER` в `lib/max.ts`) подключает скрипт Bridge
(`https://st.max.ru/js/max-web-app.js`) **только** в этом случае — обычные посетители его не
грузят. `MaxProvider` ждёт Bridge (`whenMax`, до 5 с) и, если `window.WebApp.initData` есть:

- помечает `<html data-max="ios|android|desktop|web">`;
- фиксирует масштаб (`maximum-scale=1`) — иначе iOS увеличивает страницу при фокусе на поле;
- открывает внешние ссылки через `openLink` / `openMaxLink`;
- управляет кнопкой «Назад» в шапке MAX (`useMaxBackButton` — стек шагов);
- вызывает `ready()`.

Любой вызов Bridge — через `safely()`: метод может не поддерживаться платформой.

## Вход и данные пользователя

1. Сайт берёт `WebApp.initData` и отправляет в заголовке `X-Max-Init-Data`.
2. API (`olymp_api/max_auth.py`) проверяет HMAC-подпись токеном бота по алгоритму
   https://dev.max.ru/docs/webapps/validation и срок годности (`OLYMP_MAX_INIT_DATA_TTL`, сутки).
3. Пользователь создаётся или обновляется в `max_users`; дипломы — в `user_diplomas`.
4. `GET/PUT /v1/me/diplomas` — чтение и полная замена списка дипломов.

Без `OLYMP_MAX_BOT_TOKEN` (`/v1/max/config` → `enabled: false`) дипломы хранятся на устройстве.
ID пользователя MAX — персональные данные: не логируем, не передаём в LLM и сторонние сервисы.

## Ссылки на экраны (deep links)

`https://max.ru/<бот>?startapp=<payload>` — MAX передаёт payload в `initDataUnsafe.start_param`,
`OlympApp` открывает нужный экран:

| payload | Экран |
|---|---|
| `diplomas` | вкладка «Дипломы» |
| `olympiad-<id>` | выдача по олимпиаде |
| `program-<id>` | карточка направления |
| `s_<token>` | ссылка «Поделиться»: экран из снимка `/v1/shares/{token}` ([F-01](../specs/F-01-share.md)) |

Ограничения payload: `[A-Za-z0-9_-]`, до 512 символов (`startAppLink`). **id меняются при
пересборке базы**, поэтому кнопка «Поделиться» отправляет `s_<token>`: снимок хранит стабильные
ключи. Разбор payload — `parseStartParam` (`lib/startParam.ts`).

## «Поделиться»

`WebApp.shareMaxContent({ text, link })` открывает выбор чата внутри MAX, но **только в ответ
на нажатие** — поэтому ссылку `ShareButton` создаёт заранее, пока экран показан. Ссылка в
сообщении — `https://max.ru/<бот>?startapp=s_<token>`; вне MAX — `https://<сайт>/s/<token>`
(системное меню `navigator.share` или копирование).

## Онбординг

При первом запуске (флаг `olymp.onboarding.v1` на устройстве) поверх приложения показывается
онбординг из трёх экранов (`Onboarding.tsx`, макет — `design/figma-onboarding/`). Решение
принимается после `whenMax()` (`shouldShowOnboarding` в `lib/onboarding.ts`):

- запуск ссылкой `startapp=…` — онбординг не показывается (человек пришёл за этим экраном),
  флаг ставится сразу;
- кнопка «Назад» в шапке MAX — на предыдущий шаг (на первом её нет);
- текст третьего экрана: «сохранится в профиле MAX» в MAX, «на этом устройстве» — в браузере;
- `?onboarding` в адресе показывает его принудительно — для демо и проверки.

## Проверка без телефона

```bash
OLYMP_MAX_BOT_TOKEN=local-test-token uv run python scripts/max_dev_link.py --start diplomas
```

Скрипт печатает ссылку, которая открывает сайт в браузере «как из MAX» с данными запуска,
подписанными тем же токеном, что у API. Bridge в этом случае не загружается с MAX, поэтому
нативные функции (кнопка «Назад», «Поделиться» через MAX) проверяются только на устройстве.

## Бот

`olymp-max-bot run` (профиль `bot`) отвечает на «Начать» приветствием с кнопками «Открыть
«Олимп»» и «Мои дипломы» (long polling). API бота подписан сертификатом Минцифры — корневой
сертификат кладётся в `infra/certs` ([инструкция](../../infra/certs/README.md)).
