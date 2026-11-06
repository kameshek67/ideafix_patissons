# @olymp/api-client

Типы API, сгенерированные из контракта `docs/openapi.json`, и клиент на `openapi-fetch`.

Пересоздать после изменения эндпоинтов:

```bash
just openapi                               # docs/openapi.json из FastAPI
npm run gen:api --workspace olymp-web      # schema.d.ts из docs/openapi.json
```

CI проверяет, что `schema.d.ts` совпадает с контрактом.
