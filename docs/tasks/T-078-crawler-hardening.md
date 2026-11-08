---
id: T-078
title: "Обходчик сайтов: проверка TLS и фильтр схем ссылок"
status: done
priority: P2
area: workers
estimate: S
spec: ""
depends: []
owner: shmlv9
branch: fix/T-078-crawler-tls
pr: 52
updated: 2026-11-08
---

## Цель
refresh_sources работает с CERT_NONE и пропускает javascript:/data: ссылки в карточки.

## Что сделать
- [x] Проверка TLS (с сертификатом Минцифры для нужных доменов)
- [x] Только http/https в найденных ссылках; тест

## Критерии приёмки
- [x] javascript: ссылка не попадает в university_documents
- [ ] `just check` зелёный

## Контекст
По итогам ревью 2026-11-07.

## Журнал
- 2026-11-08 — shmlv9 — `olymp_workers.tls`: проверка TLS с сертификатом Минцифры из
  `infra/certs` (как у бота), в обходчике и `olymp-validate --check-links`; `--insecure` у
  `refresh-sources`. Только http(s) в найденных ссылках и при чтении кэша в `ingest`. Воркеру в
  `docker-compose.yml` подключены сертификаты. Живой `--dry-run`: без сертификата Минцифры локально
  5 сайтов получают `TLS` (МГИМО, МИРЭА, МАИ, Сеченова, Пирогова), прежние ссылки сохраняются.
  С сертификатом не проверено — его нет на этой машине; на стенде он лежит в `infra/certs`.

