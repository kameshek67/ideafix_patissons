---
id: T-078
title: Обходчик сайтов: проверка TLS и фильтр схем ссылок
status: todo
priority: P2
area: workers
estimate: S
spec: ""
depends: []
owner: ""
branch: ""
pr: ""
updated: 2026-11-07
---

## Цель
refresh_sources работает с CERT_NONE и пропускает javascript:/data: ссылки в карточки.

## Что сделать
- [ ] Проверка TLS (с сертификатом Минцифры для нужных доменов)
- [ ] Только http/https в найденных ссылках; тест

## Критерии приёмки
- [ ] javascript: ссылка не попадает в university_documents
- [ ] `just check` зелёный

## Контекст
По итогам ревью 2026-11-07.

## Журнал
