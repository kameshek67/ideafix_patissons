# Фронтенд

Код — `apps/web`, правила разработки — [README сайта](../../apps/web/README.md#правила-разработки).

## Экраны

Одна страница (`src/app/page.tsx` → `OlympApp`) с тремя вкладками; ссылка «Поделиться»
`/s/<token>` (`src/app/s/[token]/page.tsx`, `noindex`) рендерит тот же `OlympApp` с токеном.

| Вкладка | Сценарий | Компоненты | API |
|---|---|---|---|
| «Вузы» | вуз → направление → олимпиады с БВИ / 100 баллами | `Combo`, `ProgramView`, `DataTable`, `SourceBlock` | `/v1/universities`, `/v1/programs`, `/v1/search/by-program` |
| «Олимпиады» | олимпиада → профиль → вузы → льготы вуза | `Combo`, `OlympiadView` (`OlympiadResults`, `UniversityBenefits`) | `/v1/olympiads`, `/v1/olympiads/{id}/profiles`, `/v1/search/by-olympiad` |
| «Дипломы» | мои дипломы → все вузы и направления с льготами | `DiplomasView`, `DiplomaSheet`, `useMyDiplomas` | `/v1/achievements/*`, `/v1/me/diplomas`, `/v1/max/config` |

Плюс `AboutModal` («О приложении»: что умеет «Олимп» и как работают льготы; годы действия дипломов — из `/v1/max/config`) и фильтр по типу льготы (БВИ / 100 баллов / все).

«Поделиться» ([F-01](../specs/F-01-share.md)): `ShareButton` в шапке карточки направления и
олимпиады и под итогами дипломов. Ссылку (`POST /v1/shares`) он создаёт заранее, пока экран
показан, а по нажатию отправляет её через `lib/share.ts`: MAX → меню телефона → `navigator.share`
→ копирование. Сообщения пользователю — тост (`lib/toast.ts`, `Toaster`). Открытие ссылки —
`parseStartParam` и `openShare` в `OlympApp`; чужие дипломы — `DiplomasView` с `readOnly`.

## Состояние

- Серверные данные — TanStack Query (`providers.tsx`), вызовы — только `src/lib/api.ts`.
- Состояние экрана (вкладка, выбранный вуз, выдача) — `useState` в `OlympApp.tsx`; в адресной
  строке оно не отражается — делиться экраном можно кнопкой «Поделиться» (ссылка `/s/<token>`).
- Дипломы — `useMyDiplomas`: в браузере `localStorage` (`olymp.diplomas.v1`), в MAX — профиль на
  сервере; при первом входе в MAX локальные дипломы переносятся в профиль.
- Таблицы — общий стор `TablesContext` (`DataTable.tsx`): сортировка, фильтр строки, CSV.

## Дизайн

Интерфейс повторяет прототип (тег `prototype-v1`) один в один: та же разметка и классы,
`styles.css` и Tailwind 3.4.16 с той же конфигурацией. Совпадение проверялось сравнением
раскладки и вычисленных стилей в 31 состоянии интерфейса. Новые элементы (основная кнопка,
шторка формы) собраны из токенов макета. Макеты — `design/board.html`. Решение — [ADR 0005](../adr/0005-ui-parity-with-prototype.md).

## Мини-приложение

Всё, что связано с MAX, — в [max-mini-app.md](max-mini-app.md). Главное правило: без MAX сайт
работает полностью; Bridge загружается только при запуске из MAX.
