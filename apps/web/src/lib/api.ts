import { apiClient, type Schemas } from "@olymp/api-client";

export type Stats = Schemas["Stats"];
export type UniversityItem = Schemas["UniversityItem"];
export type ProgramItem = Schemas["ProgramItem"];
export type OlympiadHit = Schemas["OlympiadHit"];
export type ProgramSearch = Schemas["ProgramSearch"];
export type OlympiadSearch = Schemas["OlympiadSearch"];
export type UniversityInfo = Schemas["UniversityInfo"];
export type Benefit = Schemas["Benefit"];
export type Source = Schemas["Source"];
export type BenefitGroup = Schemas["BenefitGroup"];

// Next.js проксирует /api/v1/* на FastAPI (next.config.ts). Адрес абсолютный: Request
// вне браузера (тесты) не принимает относительные URL.
const api = apiClient(typeof window === "undefined" ? "/api" : `${window.location.origin}/api`);

/** Ответ openapi-fetch -> данные; ошибка -> исключение «статус текст», как в прототипе. */
async function unwrap<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, response } = await p;
  if (!response.ok || data === undefined) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return data;
}

export const getStats = () => unwrap(api.GET("/v1/stats"));

export const getUniversities = () => unwrap(api.GET("/v1/universities"));

export const getPrograms = (universityId: number, q: string) =>
  unwrap(
    api.GET("/v1/programs", {
      params: { query: { university_id: universityId, ...(q ? { q } : {}) } },
    }),
  );

export const getOlympiads = (query: { q?: string; limit?: number }) =>
  unwrap(api.GET("/v1/olympiads", { params: { query } }));

export const getByProgram = (programId: number) =>
  unwrap(api.GET("/v1/search/by-program", { params: { query: { program_id: programId } } }));

export interface OlympiadQuery {
  q: string;
  olympiad_id?: number;
  profile_id?: number;
  benefit_type?: string;
  university_id?: number;
}

export const getByOlympiad = (query: OlympiadQuery) =>
  unwrap(api.GET("/v1/search/by-olympiad", { params: { query } }));
