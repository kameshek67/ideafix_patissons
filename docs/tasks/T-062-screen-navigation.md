---
id: T-062
title: Навигация navigate(intent) и «Назад» между вкладками
status: todo
priority: P0
area: web
estimate: M
spec: ""
depends: []
owner: ""
branch: ""
pr: ""
updated: 2026-11-07
---

## Цель
Переходы между вкладками рвут контекст, кнопка «Назад» MAX и браузера не работает. Та же основа нужна для ссылок F-01 и карточек помощника F-02.

## Что сделать
- [ ] Тип ScreenIntent (program, olympiad, university, diplomas) и navigate(); вынести из замыканий OlympApp
- [ ] parseStartParam() с тестами; deep link не ждёт загрузки списка вузов, если не нужно
- [ ] Стек «Назад»: MAX BackButton + history.pushState на сайте; ссылка «← К дипломам» после перехода из «Дипломов»

## Критерии приёмки
- [ ] Системная «назад» на Android возвращает на предыдущий экран, а не закрывает приложение
- [ ] Есть тесты parseStartParam и navigate
- [ ] `just check` зелёный

## Контекст
По итогам ревью 2026-11-07.

## Журнал
