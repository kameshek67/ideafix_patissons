import { apiClient, type Schemas } from "@/api";
import type { EgeScores } from "./ege";

export type UniversityItem = Schemas["UniversityItem"];
export type ProgramItem = Schemas["ProgramItem"];
export type OlympiadHit = Schemas["OlympiadHit"];
export type OlympiadCard = Schemas["OlympiadCard"];
export type ProgramSearch = Schemas["ProgramSearch"];
export type OlympiadSearch = Schemas["OlympiadSearch"];
export type UniversityInfo = Schemas["UniversityInfo"];
export type Benefit = Schemas["Benefit"];
// в контракте имя Source занято двумя схемами (поиск и баллы за достижения), поэтому длинное имя
export type Source = Schemas["olymp_api__modules__search__schemas__Source"];
export type BenefitGroup = Schemas["BenefitGroup"];
export type Quality = Schemas["Quality"];
export type GoalOlympiad = Schemas["GoalOlympiad"];
export type GoalOlympiads = Schemas["GoalOlympiads"];

// Next.js проксирует /api/v1/* на FastAPI (next.config.ts). Адрес абсолютный: Request
// вне браузера (тесты) не принимает относительные URL.
const api = apiClient(typeof window === "undefined" ? "/api" : `${window.location.origin}/api`);

/** Ошибка ответа API: статус нужен, чтобы отличить «сервер лёг» (5xx) от «не нашлось» (4xx). */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    statusText: string,
  ) {
    super(`${status} ${statusText}`);
  }
}

/** Ответ openapi-fetch -> данные; ошибка -> ApiError «статус текст», как в прототипе. */
async function unwrap<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, response } = await p;
  if (!response.ok || data === undefined) {
    throw new ApiError(response.status, response.statusText);
  }
  return data;
}

/** Текст ошибки загрузки для школьника: без кодов, адресов и слов «бэкенд» и «сборка базы». */
export function friendlyError(e: unknown): string {
  if (e instanceof ApiError && e.status >= 500) return "Сервер сейчас не отвечает. Попробуй ещё раз через минуту.";
  if (e instanceof ApiError) return "Не получилось загрузить данные. Попробуй ещё раз.";
  return "Нет связи с сервером. Проверь интернет и попробуй ещё раз.";
}


export const getQuality = () => unwrap(api.GET("/v1/quality"));

export const getUniversities = () => unwrap(api.GET("/v1/universities"));

export const getPrograms = (universityId: number, q: string) =>
  unwrap(
    api.GET("/v1/programs", {
      params: { query: { university_id: universityId, ...(q ? { q } : {}) } },
    }),
  );

export const getOlympiads = (query: { q?: string; limit?: number; with_profile?: boolean }) =>
  unwrap(api.GET("/v1/olympiads", { params: { query } }));

export const getByProgram = (programId: number) =>
  unwrap(api.GET("/v1/search/by-program", { params: { query: { program_id: programId } } }));

export const getGoalOlympiads = (programIds: number[]) =>
  unwrap(api.GET("/v1/goals/olympiads", { params: { query: { program_id: programIds } } }));

export interface OlympiadQuery {
  q: string;
  olympiad_id?: number;
  profile_id?: number;
  benefit_type?: string;
  university_id?: number;
  /** группа регионов: «Москва», «Санкт-Петербург», «Регионы» */
  region?: string;
  /** summary — список вузов со счётчиками, без строк льгот (строки вуза грузятся с university_id) */
  view?: "full" | "summary";
}

export const getByOlympiad = (query: OlympiadQuery) =>
  unwrap(api.GET("/v1/search/by-olympiad", { params: { query } }));

// ---------------------------------------------------------------- «Мои дипломы»

export type DiplomaForm = Schemas["DiplomaForm"];
export type DiplomaProfile = Schemas["DiplomaProfile"];
export type AchievementsMatch = Schemas["AchievementsMatch"];
export type AchievementUniversity = Schemas["AchievementUniversity"];
export type AchievementRow = Schemas["AchievementRow"];
export type DiplomaResult = Schemas["DiplomaResult"];
export type MaxConfig = Schemas["MaxConfig"];
export type MyDiplomas = Schemas["MyDiplomas"];

export const getDiplomaForm = (olympiadId: number) =>
  unwrap(
    api.GET("/v1/achievements/olympiads/{olympiad_id}", {
      params: { path: { olympiad_id: olympiadId } },
    }),
  );

export interface AchievementsQuery {
  benefit_type?: string;
  university_id?: number;
  /** баллы ЕГЭ «предмет:балл» */
  ege?: string[];
  /** по каким правилам считать: проект 2027 заменяет призёрам БВИ на 100 баллов */
  rules?: "current" | "project2027";
}

export const getAchievements = (diplomas: string[], query: AchievementsQuery = {}) =>
  unwrap(api.GET("/v1/achievements/match", { params: { query: { diploma: diplomas, ...query } } }));

export const getMaxConfig = () => unwrap(api.GET("/v1/max/config"));

// ---------------------------------------------------------------- помощник
// сам чат идёт потоком через /api/assistant/chat (см. lib/assistant.ts)

export const getAssistantConfig = () => unwrap(api.GET("/v1/assistant/config"));

export async function sendAssistantFeedback(messageId: string, rating: 1 | -1): Promise<void> {
  const { response } = await api.POST("/v1/assistant/feedback", {
    body: { message_id: messageId, rating },
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
}

export type BenefitReportRequest = Schemas["BenefitReportIn"];
export type BenefitReportReason = BenefitReportRequest["reason"];
export type ReportRequest = Schemas["ProgramReportIn"] | Schemas["OlympiadReportIn"] | BenefitReportRequest;

/** «Нашли ошибку в данных» и «Не совпадает с документом» у строки льготы. Из MAX
 *  передаём данные запуска: так бот ответит автору, когда оператор проверит. */
export async function sendReport(body: ReportRequest, initData?: string | null): Promise<void> {
  const { response } = await api.POST("/v1/reports", {
    body,
    ...(initData ? { headers: maxHeaders(initData) } : {}),
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
}

// дипломы пользователя MAX: API узнаёт его по подписанным данным запуска мини-приложения
const maxHeaders = (initData: string) => ({ "X-Max-Init-Data": initData });

export const getMyDiplomas = (initData: string) =>
  unwrap(api.GET("/v1/me/diplomas", { headers: maxHeaders(initData) }));

export const putMyDiplomas = (initData: string, diplomas: string[], ege?: EgeScores) =>
  unwrap(
    api.PUT("/v1/me/diplomas", {
      // без ege сервер баллы не трогает (ege_is_mock тогда не читается)
      body: { diplomas, ege_is_mock: ege?.mock ?? false, ...(ege ? { ege: ege.scores } : {}) },
      headers: maxHeaders(initData),
    }),
  );

// «Поделиться»: снимок экрана по id текущей сборки и открытие ссылки по токену
export type ShareRequest = Schemas["ProgramShareIn"] | Schemas["OlympiadShareIn"] | Schemas["DiplomasShareIn"];
export type ShareCreated = Schemas["ShareCreated"];
export type SharedScreen = Schemas["Share"];
export type ShareBenefitType = NonNullable<Schemas["ProgramShareIn"]["benefit_type"]>;

/** Фильтр «Все / БВИ / 100 баллов» в снимке: «Все» — без фильтра. */
export const shareBenefitType = (type: string): ShareBenefitType | null =>
  type === "БВИ" || type === "100 баллов" ? type : null;

export const createShare = (body: ShareRequest) => unwrap(api.POST("/v1/shares", { body }));

export const getShare = (token: string) =>
  unwrap(api.GET("/v1/shares/{token}", { params: { path: { token } } }));

// ---------------------------------------------------------------- баллы за достижения (ГТО…)

export type ExtraUniversities = Schemas["ExtraUniversities"];
export type ExtraUniversity = Schemas["ExtraUniversity"];
export type ExtraRules = Schemas["ExtraRules"];
export type ExtraRule = Schemas["ExtraRule"];
export type ExtraScore = Schemas["Score"];
export type ExtraClaim = Schemas["ClaimIn"];

/** Год кампании, по которому собраны баллы за достижения (data/individual_achievements.csv). */
export const EXTRA_YEAR = 2026;

export const getExtraUniversities = () =>
  unwrap(api.GET("/v1/extra-points/universities", { params: { query: { admission_year: EXTRA_YEAR } } }));

export const getExtraRules = (universityId: number) =>
  unwrap(
    api.GET("/v1/extra-points/universities/{university_id}", {
      params: { path: { university_id: universityId }, query: { admission_year: EXTRA_YEAR } },
    }),
  );

export const scoreExtra = (universityId: number, claims: ExtraClaim[]) =>
  unwrap(
    api.POST("/v1/extra-points/score", {
      body: { university_id: universityId, admission_year: EXTRA_YEAR, claims },
    }),
  );

// служебный раздел скрыт из OpenAPI, поэтому его типы и запросы живут здесь
export interface OpsSourceIn {
  url: string;
  university: string;
}

export interface OpsJobDetail {
  id: number;
  source_id: number;
  university: string;
  url: string;
  status: string;
  error: string;
  records_count: number;
  quotes_checked: number;
  quotes_found: number;
  rebuild_needed: boolean;
  created_at: string;
  updated_at: string;
  documents: Record<string, unknown>[];
  diff: Record<string, unknown>;
}

export type OpsJob = Omit<OpsJobDetail, "documents" | "diff">;

interface OpsCreated {
  source_id: number;
  job_id: number;
  created: boolean;
}

interface OpsDecision {
  id: number;
  status: string;
  records: number;
}

async function opsRequest<T>(
  path: string,
  token: string,
  method: "GET" | "POST" = "GET",
  body?: unknown,
): Promise<T> {
  const base = typeof window === "undefined" ? "/api" : `${window.location.origin}/api`;
  const request = new Request(`${base}/v1/ops${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body === undefined ? {} : { "content-type": "application/json" }),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const response = await fetch(request);
  if (!response.ok) throw new ApiError(response.status, response.statusText);
  return (await response.json()) as T;
}

export const getOpsJobs = (token: string) => opsRequest<OpsJob[]>("/jobs", token);

export const getOpsJob = (token: string, id: number) => opsRequest<OpsJobDetail>(`/jobs/${id}`, token);

export const addOpsSource = (token: string, body: OpsSourceIn) =>
  opsRequest<OpsCreated>("/sources", token, "POST", body);

export const acceptOpsJob = (token: string, id: number) =>
  opsRequest<OpsDecision>(`/jobs/${id}/accept`, token, "POST");

export const rejectOpsJob = (token: string, id: number) =>
  opsRequest<OpsDecision>(`/jobs/${id}/reject`, token, "POST");
