import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type { components, paths };
export type Schemas = components["schemas"];

/** Типизированный клиент API: пути и ответы берутся из docs/openapi.json.
 *  fetch берётся в момент запроса, а не при создании клиента — его можно подменить в тестах. */
export const apiClient = (baseUrl = "/api") =>
  createClient<paths>({ baseUrl, fetch: (request) => globalThis.fetch(request) });
