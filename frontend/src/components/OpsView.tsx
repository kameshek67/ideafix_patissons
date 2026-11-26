"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import {
  acceptOpsJob,
  addOpsSource,
  ApiError,
  getOpsJob,
  getOpsJobs,
  rejectOpsJob,
  type OpsJobDetail,
} from "@/lib/api";
import { fmt, plural } from "@/lib/format";
import { IconChevronLeft } from "./icons";

const TOKEN_KEY = "olymp.ops.token";
const ACTIVE = new Set(["queued", "fetching", "extracting", "review"]);

const STATUS: Record<string, string> = {
  queued: "В очереди",
  fetching: "Загружаем",
  extracting: "Разбираем",
  review: "На проверке",
  accepted: "Принято",
  rejected: "Отклонено",
  failed: "Ошибка",
};

type OpsExample = {
  kind?: string;
  program?: string;
  olympiad?: string;
  profile?: string;
  quote?: string;
  page?: number | string | null;
};

type OpsDiff = {
  added?: number;
  removed?: number;
  changed?: number;
  examples?: Partial<Record<"added" | "removed" | "changed", OpsExample[]>>;
};

const EXAMPLE_KINDS = ["added", "removed", "changed"] as const;
const EXAMPLE_LABEL: Record<string, string> = {
  added: "добавится",
  removed: "пропадёт",
  changed: "изменится",
};

const count = (value: unknown): number => (typeof value === "number" ? value : 0);

function timeOf(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function errorText(e: unknown): string {
  if (e instanceof ApiError && e.status === 401) return "Токен не подошёл";
  if (e instanceof ApiError && e.status === 404) return "Разбор выключен на сервере";
  if (e instanceof ApiError && e.status >= 500) return "Сервер сейчас не отвечает";
  return "Не получилось. Попробуй ещё раз";
}

function JobCard({ token, id }: { token: string; id: number }) {
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: ["ops", "job", token, id],
    queryFn: () => getOpsJob(token, id),
    enabled: Boolean(token),
  });
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function decide(kind: "accept" | "reject") {
    setBusy(kind);
    setError(null);
    try {
      if (kind === "accept") await acceptOpsJob(token, id);
      else await rejectOpsJob(token, id);
      await queryClient.invalidateQueries({ queryKey: ["ops"] });
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
    }
  }

  if (detail.isPending)
    return (
      <section className="card mt-4 p-4 sm:p-5">
        <p className="meta-text text-[14px]">Загружаем задачу…</p>
      </section>
    );
  if (detail.error)
    return (
      <section className="card mt-4 p-4 sm:p-5" role="alert">
        <p className="text-[14px]">{errorText(detail.error)}</p>
        <button type="button" className="chip chip-lg mt-3" onClick={() => void detail.refetch()}>
          Повторить
        </button>
      </section>
    );
  const job = detail.data;
  if (!job) return null;

  const diff = job.diff as OpsDiff;
  const examples = EXAMPLE_KINDS.flatMap((kind) =>
    (diff.examples?.[kind] ?? []).map((ex) => ({ ...ex, kind })),
  ).slice(0, 5);
  const canDecide = job.status === "review" && !busy;

  return (
    <section className="card mt-4 p-4 sm:p-5" aria-label={`Задача ${id}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-[18px] leading-[24px] font-medium">{`Задача №${id}`}</h2>
        <span className="badge badge-soft">{STATUS[job.status] ?? job.status}</span>
      </div>
      <p className="mt-1 text-[13px] leading-[18px] meta-text">
        {job.university} · {timeOf(job.updated_at)} · записей: {fmt(job.records_count)}
      </p>
      <p className="mt-1 text-[13px] leading-[18px] break-all">
        <a href={job.url} target="_blank" rel="noreferrer" className="underline">
          {job.url}
        </a>
      </p>
      {job.error ? (
        <p className="mt-2 text-[13px] leading-[18px] text-red-600" role="alert">
          {job.error}
        </p>
      ) : null}

      <h3 className="mt-4 card-kicker">Документы</h3>
      {job.documents.length ? (
        <ul className="mt-1 space-y-1.5 text-[14px] leading-[20px]">
          {job.documents.map((doc, i) => {
            const url = typeof doc.url === "string" ? doc.url : "";
            const title = typeof doc.title === "string" && doc.title ? doc.title : "Документ";
            const records = count(doc.records);
            const docError = typeof doc.error === "string" ? doc.error : "";
            return (
              <li key={`${url}-${i}`}>
                {url ? (
                  <a href={url} target="_blank" rel="noreferrer" className="underline">
                    {title}
                  </a>
                ) : (
                  title
                )}
                {` · ${fmt(records)} ${plural(records, "запись", "записи", "записей")}`}
                {docError ? <span className="meta-text">{` · ${docError}`}</span> : null}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="mt-1 text-[14px] leading-[20px] meta-text">Документов нет.</p>
      )}

      <p className="mt-4 text-[16px] leading-[22px] font-medium tabular-nums">
        {`станет строк: +${fmt(count(diff.added))} −${fmt(count(diff.removed))} ~${fmt(count(diff.changed))}`}
      </p>

      {examples.length ? (
        <>
          <h3 className="mt-4 card-kicker">Примеры</h3>
          <ol className="mt-2 space-y-2">
            {examples.map((ex, i) => (
              <li key={i} className="rounded-[12px] bg-brand-50 p-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-[13px] leading-[18px]">
                  <span className="font-medium">
                    {ex.program || "—"} · {EXAMPLE_LABEL[ex.kind] ?? ex.kind}
                  </span>
                  <span className="meta-text">{`стр. ${ex.page ?? "—"}`}</span>
                </div>
                {ex.olympiad || ex.profile ? (
                  <p className="mt-1 text-[13px] leading-[18px]">
                    {[ex.olympiad, ex.profile].filter(Boolean).join(", ")}
                  </p>
                ) : null}
                <blockquote className="mt-1 text-[13px] leading-[18px] meta-text">
                  {`«${ex.quote || "цитата не найдена"}»`}
                </blockquote>
              </li>
            ))}
          </ol>
        </>
      ) : null}

      <div className="mt-4 flex gap-2">
        <button type="button" className="btn-primary flex-1" disabled={!canDecide} onClick={() => void decide("accept")}>
          Принять
        </button>
        <button type="button" className="btn-secondary flex-1" disabled={!canDecide} onClick={() => void decide("reject")}>
          Отклонить
        </button>
      </div>
      {error ? (
        <p className="mt-2 text-[13px] leading-[18px] text-red-600" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}

export function OpsView() {
  const queryClient = useQueryClient();
  const [token, setToken] = useState("");
  const [url, setUrl] = useState("");
  const [university, setUniversity] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    setToken(sessionStorage.getItem(TOKEN_KEY) ?? "");
  }, []);

  const jobs = useQuery({
    queryKey: ["ops", "jobs", token],
    queryFn: () => getOpsJobs(token),
    enabled: Boolean(token),
    refetchInterval: (query) => (query.state.data?.some((job) => ACTIVE.has(job.status)) ? 10_000 : false),
  });

  function changeToken(value: string) {
    setToken(value);
    if (value) sessionStorage.setItem(TOKEN_KEY, value);
    else sessionStorage.removeItem(TOKEN_KEY);
    setSelected(null);
    setMessage(null);
    setError(null);
  }

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const link = url.trim();
    const name = university.trim();
    if (!token || !link || !name || busy) return;
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      const created = await addOpsSource(token, { url: link, university: name });
      setMessage(
        created.created ? `Задача №${created.job_id} поставлена` : `Задача №${created.job_id} уже идёт`,
      );
      setUrl("");
      setUniversity("");
      await queryClient.invalidateQueries({ queryKey: ["ops", "jobs"] });
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <header className="app-header">
        <div className="mx-auto max-w-5xl h-14 px-2 flex items-center">
          <a href="/" className="icon-btn" aria-label="На главную" title="На главную">
            <IconChevronLeft />
          </a>
          <div className="flex-1 text-center text-[17px] font-medium">Оператор</div>
          <span className="w-10 shrink-0" aria-hidden="true" />
        </div>
      </header>
      <main className="mx-auto max-w-2xl px-4 pb-16">
        <h1 className="mt-4 text-[26px] leading-[32px] font-medium">Разбор документов</h1>

        <section className="card mt-4 p-4 sm:p-5">
          <h2 className="text-[18px] leading-[24px] font-medium">Доступ</h2>
          <label className="field-label mt-3" htmlFor="ops-token">
            Токен
          </label>
          <input
            id="ops-token"
            type="password"
            autoComplete="off"
            className="table-filter w-full"
            placeholder="Токен оператора"
            value={token}
            onChange={(e) => changeToken(e.target.value)}
          />
          <p className="field-note">Хранится только в этой вкладке.</p>
        </section>

        <section className="card mt-4 p-4 sm:p-5">
          <h2 className="text-[18px] leading-[24px] font-medium">Новая ссылка</h2>
          <form className="mt-3" onSubmit={(e) => void submit(e)}>
            <label className="field-label" htmlFor="ops-url">
              Ссылка
            </label>
            <input
              id="ops-url"
              className="table-filter w-full"
              placeholder="https://вуз.рф/olympiada.pdf"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
            <label className="field-label mt-3" htmlFor="ops-university">
              Вуз
            </label>
            <input
              id="ops-university"
              className="table-filter w-full"
              placeholder="Название вуза"
              value={university}
              onChange={(e) => setUniversity(e.target.value)}
            />
            {message ? (
              <p className="mt-2 text-[13px] leading-[18px]" role="status">
                {message}
              </p>
            ) : null}
            {error ? (
              <p className="mt-2 text-[13px] leading-[18px] text-red-600" role="alert">
                {error}
              </p>
            ) : null}
            <button
              type="submit"
              className="btn-primary mt-4 w-full"
              disabled={!token || !url.trim() || !university.trim() || busy}
            >
              {busy ? "Ставим…" : "Разобрать"}
            </button>
          </form>
        </section>

        <section className="card mt-4 p-4 sm:p-5">
          <h2 className="text-[18px] leading-[24px] font-medium">Задачи</h2>
          {!token ? (
            <p className="mt-2 text-[14px] leading-[20px] meta-text">Введи токен, чтобы увидеть задачи.</p>
          ) : jobs.isPending ? (
            <p className="mt-2 text-[14px] leading-[20px] meta-text">Загружаем…</p>
          ) : jobs.error ? (
            <div role="alert">
              <p className="mt-2 text-[14px] leading-[20px]">{errorText(jobs.error)}</p>
              <button type="button" className="chip chip-lg mt-3" onClick={() => void jobs.refetch()}>
                Повторить
              </button>
            </div>
          ) : jobs.data?.length ? (
            <>
              <p className="mt-1 text-[12.5px] leading-[17px] meta-text">Нажми на задачу, чтобы открыть карточку.</p>
              <ul className="mt-3 space-y-2">
                {jobs.data.map((job) => (
                  <li key={job.id}>
                    <button
                      type="button"
                      className={`w-full rounded-[12px] p-3 text-left ${selected === job.id ? "bg-brand-50" : "bg-brand-50/60"}`}
                      onClick={() => setSelected(job.id)}
                    >
                      <div className="flex flex-wrap items-baseline justify-between gap-2 text-[14px] leading-[20px]">
                        <span className="font-medium">{`№${job.id} · ${job.university}`}</span>
                        <span className="meta-text">{STATUS[job.status] ?? job.status}</span>
                      </div>
                      <p className="mt-1 text-[12.5px] leading-[17px] meta-text">
                        {timeOf(job.updated_at)}
                        {job.error ? ` · ${job.error}` : ""}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="mt-2 text-[14px] leading-[20px] meta-text">Задач пока нет.</p>
          )}
        </section>

        {selected !== null && token ? <JobCard key={selected} token={token} id={selected} /> : null}
      </main>
    </>
  );
}
