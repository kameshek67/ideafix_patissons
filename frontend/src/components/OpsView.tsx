"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import {
  acceptOpsJob,
  addOpsSource,
  ApiError,
  getOpsJob,
  getOpsJobs,
  getUniversities,
  rejectOpsJob,
  type OpsJob,
} from "@/lib/api";
import { fmt, place, plural } from "@/lib/format";
import {
  GROUP_LABEL,
  groupOf,
  IN_WORK,
  jobErrorText,
  shortUrl,
  GRADE_BADGE,
  GRADE_LABEL,
  STATUS_BADGE,
  STATUS_LABEL,
  STEPS,
  validUrl,
  type StatusGroup,
} from "@/lib/ops";
import { showToast } from "@/lib/toast";
import { Combo, type ComboItem } from "./Combo";
import { IconChevronLeft, IconCloseModal, IconDocument } from "./icons";
import { Toaster } from "./Toaster";

const TOKEN_KEY = "olymp.ops.token";
const GROUPS: StatusGroup[] = ["work", "review", "accepted", "rejected", "failed"];

type OpsExample = {
  kind?: string;
  program?: string;
  olympiad?: string;
  profile?: string;
  quote?: string;
  page?: number | string | null;
  url?: string;
};

type OpsDiff = {
  added?: number;
  removed?: number;
  changed?: number;
  examples?: Partial<Record<"added" | "removed" | "changed", OpsExample[]>>;
};

const EXAMPLE_KINDS = ["added", "removed", "changed"] as const;
const EXAMPLE_LABEL: Record<string, string> = { added: "добавится", removed: "пропадёт", changed: "изменится" };
const EXAMPLE_BADGE: Record<string, string> = { added: "badge-ok", removed: "badge-err", changed: "badge-sto" };

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

const isUnauthorized = (e: unknown) => e instanceof ApiError && e.status === 401;

/** Ссылка на документ с примера: у PDF добавляем номер страницы. */
function exampleLink(example: OpsExample, fallback: string): string {
  const base = typeof example.url === "string" && example.url ? example.url : fallback;
  const page = Number(example.page);
  return /\.pdf($|[?#])/i.test(base) && !base.includes("#") && page > 0 ? `${base}#page=${page}` : base;
}

// ------------------------------------------------------------------ индикатор шагов

function Steps({ status }: { status: string }) {
  const now = STEPS.indexOf(status as (typeof STEPS)[number]);
  if (now < 0 || !IN_WORK.has(status)) return null;
  return (
    <div>
      <div
        className="ops-steps"
        role="progressbar"
        aria-label="Шаг разбора"
        aria-valuemin={1}
        aria-valuemax={STEPS.length}
        aria-valuenow={now + 1}
        aria-valuetext={STATUS_LABEL[status]}
      >
        {STEPS.map((step, i) => (
          <i key={step} className={i < now ? "is-done" : i === now ? "is-now" : undefined} />
        ))}
      </div>
      <p className="ops-steps-note">{`Шаг ${now + 1} из ${STEPS.length} · ${STATUS_LABEL[status]}`}</p>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${STATUS_BADGE[status] ?? "badge-soft"}`}>{STATUS_LABEL[status] ?? status}</span>;
}

/** Оценка автопроверки: пусто, пока задачу не оценили. */
function GradeBadge({ grade }: { grade: string }) {
  if (!GRADE_LABEL[grade]) return null;
  return (
    <span className={`badge ${GRADE_BADGE[grade]}`} title="Оценка автопроверки">
      {`Проверка: ${GRADE_LABEL[grade].toLowerCase()}`}
    </span>
  );
}

function UserMark() {
  return <span className="badge badge-soft">от пользователя</span>;
}

// ------------------------------------------------------------------ карточка задачи

function JobDetail({
  token,
  job,
  onClose,
}: {
  token: string;
  job: OpsJob;
  onClose: () => void;
}) {
  const id = job.id;
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: ["ops", "job", token, id],
    queryFn: () => getOpsJob(token, id),
    refetchInterval: (query) => (IN_WORK.has(query.state.data?.status ?? job.status) ? 10_000 : false),
  });
  const [confirm, setConfirm] = useState<"accept" | "reject" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // список обновляется чаще, чем карточка: статус берём свежий из любого из них
  const data = detail.data;
  const status = data?.status ?? job.status;
  const diff = (data?.diff ?? {}) as OpsDiff;
  const added = count(diff.added);
  const removed = count(diff.removed);
  const changed = count(diff.changed);
  const examples = EXAMPLE_KINDS.flatMap((kind) => (diff.examples?.[kind] ?? []).map((ex) => ({ ...ex, kind }))).slice(0, 5);
  const failure = data?.error ?? job.error;
  const grade = data?.grade ?? job.grade;
  const reasons = data?.grade_reasons ?? job.grade_reasons;

  async function decide(kind: "accept" | "reject") {
    setBusy(true);
    setError(null);
    try {
      if (kind === "accept") await acceptOpsJob(token, id);
      else await rejectOpsJob(token, id);
      await queryClient.invalidateQueries({ queryKey: ["ops"] });
      showToast(kind === "accept" ? `Задача №${id} принята` : `Задача №${id} отклонена`);
      setConfirm(null);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <header className="ops-panel-head">
        <button type="button" className="icon-btn lg:hidden" onClick={onClose} aria-label="К задачам" title="К задачам">
          <IconChevronLeft />
        </button>
        <div className="min-w-0 flex-1">
          <h2 className="text-[17px] leading-[22px] font-medium">{`Задача №${id}`}</h2>
          <p className="text-[12.5px] leading-[17px] meta-text truncate">{job.university}</p>
        </div>
        <button type="button" className="icon-btn hidden lg:grid" onClick={onClose} aria-label="Закрыть" title="Закрыть">
          <IconCloseModal />
        </button>
      </header>

      <div className="ops-panel-body">
        <div className="ops-fade" key={detail.isPending ? "wait" : "ready"}>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <StatusBadge status={status} />
            <GradeBadge grade={grade} />
            {job.origin === "user" ? <UserMark /> : null}
            <span className="text-[12.5px] meta-text">{timeOf(data?.updated_at ?? job.updated_at)}</span>
          </div>
          {reasons.length ? (
            <ul className="mt-2 list-disc pl-5 text-[13px] leading-[18px]" aria-label="Что насторожило автопроверку">
              {reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          ) : null}
          {job.origin === "user" && job.comment ? (
            <p className="mt-2 text-[13px] leading-[18px] meta-text break-words">{`Комментарий: ${job.comment}`}</p>
          ) : null}
          <p className="mt-2 text-[13px] leading-[18px]">
            <a href={job.url} target="_blank" rel="noreferrer" className="link-cell break-all" title={job.url}>
              {shortUrl(job.url, 60)}
            </a>
          </p>
          <Steps status={status} />

          {status === "failed" || failure ? (
            <div className="mt-3 rounded-[12px] bg-[#FFF1F0] p-3 text-[13.5px] leading-[19px]" role="alert">
              <p className="text-[#B42318]">{jobErrorText(failure)}</p>
              {failure ? (
                <details className="mt-1">
                  <summary className="text-[12.5px] meta-text">Подробности</summary>
                  <p className="mt-1 text-[12.5px] meta-text break-words">{failure}</p>
                </details>
              ) : null}
            </div>
          ) : null}

          {detail.error && !data ? (
            <div className="mt-4" role="alert">
              <p className="text-[14px]">{errorText(detail.error)}</p>
              <button type="button" className="chip chip-lg mt-3" onClick={() => void detail.refetch()}>
                Повторить
              </button>
            </div>
          ) : detail.isPending ? (
            <div className="skeleton-stack mt-4" aria-label="Загружаем задачу">
              <div className="skeleton h-16 rounded-[12px]" />
              <div className="skeleton h-28 rounded-[12px]" />
              <div className="skeleton h-28 rounded-[12px]" />
            </div>
          ) : data ? (
            <>
              <h3 className="mt-5 card-kicker">{`Найденные документы · ${fmt(data.documents.length)}`}</h3>
              {data.documents.length ? (
                <ul>
                  {data.documents.map((doc, i) => {
                    const url = typeof doc.url === "string" ? doc.url : "";
                    const title = typeof doc.title === "string" && doc.title ? doc.title : "Документ";
                    const records = count(doc.records);
                    const docError = typeof doc.error === "string" ? doc.error : "";
                    return (
                      <li key={`${url}-${i}`} className="ops-doc">
                        <span className="mt-0.5 shrink-0 text-brand" aria-hidden="true">
                          <IconDocument />
                        </span>
                        <span className="min-w-0 flex-1 text-[14px] leading-[20px]">
                          {url ? (
                            <a href={url} target="_blank" rel="noreferrer" className="link-cell break-words">
                              {title}
                            </a>
                          ) : (
                            title
                          )}
                          <span className="block text-[12.5px] meta-text">
                            {`${fmt(records)} ${plural(records, "запись", "записи", "записей")}`}
                            {docError ? ` · ${jobErrorText(docError)}` : ""}
                          </span>
                        </span>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="mt-1 text-[14px] leading-[20px] meta-text">Документов не нашли.</p>
              )}
              {data.quotes_checked ? (
                <p className="mt-1 text-[12.5px] meta-text">
                  {`Цитат подтверждено в тексте: ${fmt(data.quotes_found)} из ${fmt(data.quotes_checked)}`}
                </p>
              ) : null}

              <h3 className="mt-5 card-kicker">Что изменится в базе</h3>
              <div className="ops-pills">
                <span className="ops-pill is-add">{`+${fmt(added)} новых`}</span>
                <span className="ops-pill is-del">{`−${fmt(removed)} пропадёт`}</span>
                <span className="ops-pill is-chg">{`~${fmt(changed)} изменится`}</span>
              </div>
              {data.rebuild_needed ? (
                <p className="mt-2 text-[12.5px] leading-[17px] meta-text">После принятия нужна пересборка базы.</p>
              ) : null}

              {examples.length ? (
                <>
                  <h3 className="mt-5 card-kicker">{`Примеры · ${examples.length}`}</h3>
                  <ol className="mt-2 space-y-2">
                    {examples.map((ex, i) => (
                      <li key={i} className="ops-example">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className={`badge ${EXAMPLE_BADGE[ex.kind] ?? "badge-soft"}`}>
                            {EXAMPLE_LABEL[ex.kind] ?? ex.kind}
                          </span>
                          <span className="text-[12.5px] meta-text">{`стр. ${ex.page ?? "—"}`}</span>
                        </div>
                        <p className="mt-2 text-[14px] leading-[19px] font-medium">{ex.program || "—"}</p>
                        {ex.olympiad || ex.profile ? (
                          <p className="text-[13px] leading-[18px]">{[ex.olympiad, ex.profile].filter(Boolean).join(", ")}</p>
                        ) : null}
                        <blockquote className="ops-quote">{`«${ex.quote || "цитата не найдена"}»`}</blockquote>
                        <a
                          href={exampleLink(ex, job.url)}
                          target="_blank"
                          rel="noreferrer"
                          className="mt-2 inline-block text-[13px] link-cell"
                        >
                          открыть документ
                        </a>
                      </li>
                    ))}
                  </ol>
                </>
              ) : null}
            </>
          ) : null}
        </div>
      </div>

      <div className="ops-panel-actions">
        {error ? (
          <p className="mb-2 text-[13px] leading-[18px] text-[#B42318]" role="alert">
            {error}
          </p>
        ) : null}
        {status !== "review" ? (
          <p className="text-[13.5px] leading-[19px] meta-text">
            {IN_WORK.has(status)
              ? "Решение появится, когда разбор закончится."
              : status === "accepted"
                ? "Решение принято: записи добавлены в базу."
                : status === "rejected"
                  ? "Разбор отклонён, в базу ничего не попало."
                  : "Разбор не удался, решать нечего."}
          </p>
        ) : confirm ? (
          <div className="ops-confirm">
            <p className="text-[14px] leading-[19px]">
              {confirm === "accept"
                ? `Принять разбор? В базу попадёт: +${fmt(added)}, −${fmt(removed)}, ~${fmt(changed)}.`
                : "Отклонить разбор? Найденные записи в базу не попадут."}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                className={`${confirm === "accept" ? "btn-primary" : "btn-secondary"} flex-1`}
                disabled={busy}
                onClick={() => void decide(confirm)}
              >
                {busy ? "Отправляю…" : confirm === "accept" ? "Да, принять" : "Да, отклонить"}
              </button>
              <button type="button" className="btn-secondary flex-1" disabled={busy} onClick={() => setConfirm(null)}>
                Назад
              </button>
            </div>
          </div>
        ) : (
          <div className="flex gap-2">
            <button
              type="button"
              className={grade === "green" ? "btn-primary ops-accept-ok flex-[2]" : "btn-primary flex-1"}
              disabled={!data}
              onClick={() => setConfirm("accept")}
            >
              Принять
            </button>
            <button type="button" className="btn-secondary flex-1" disabled={!data} onClick={() => setConfirm("reject")}>
              Отклонить
            </button>
          </div>
        )}
      </div>
    </>
  );
}

// ------------------------------------------------------------------ доступ

function AccessCard({
  token,
  failed,
  onSignIn,
  onSignOut,
  checking,
}: {
  token: string;
  failed: boolean;
  checking: boolean;
  onSignIn: (token: string) => void;
  onSignOut: () => void;
}) {
  const [draft, setDraft] = useState(token);
  const [shown, setShown] = useState(false);

  if (token && !failed)
    return (
      <section className="card ops-access-row" aria-label="Доступ">
        <p className="text-[14px] leading-[20px]">{checking ? "Проверяем доступ…" : "Доступ есть"}</p>
        <button type="button" className="ops-link-btn" onClick={onSignOut}>
          Выйти
        </button>
      </section>
    );

  return (
    <section className="card p-4 sm:p-5" aria-label="Доступ">
      <h2 className="block-title">Доступ</h2>
      <form
        className="mt-3"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          if (draft.trim()) onSignIn(draft.trim());
        }}
      >
        <label className="field-label block" htmlFor="ops-token">
          Токен оператора
        </label>
        <div className="field-wrap">
          <input
            id="ops-token"
            type={shown ? "text" : "password"}
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
            className="field-input"
            placeholder="Вставь токен"
            aria-invalid={failed || undefined}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <button type="button" className="field-toggle" aria-pressed={shown} onClick={() => setShown((v) => !v)}>
            {shown ? "Скрыть" : "Показать"}
          </button>
        </div>
        {failed ? (
          <p className="field-error" role="alert">
            Токен не подошёл. Проверь, что скопировал его целиком.
          </p>
        ) : (
          <p className="field-note">Хранится только в этой вкладке.</p>
        )}
        <button type="submit" className="btn-primary mt-4 w-full" disabled={!draft.trim()}>
          Войти
        </button>
      </form>
    </section>
  );
}

// ------------------------------------------------------------------ новый документ

function NewDocument({ token, onCreated }: { token: string; onCreated: (jobId: number) => void }) {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const [touched, setTouched] = useState(false);
  const [university, setUniversity] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const urlOk = validUrl(url);
  const urlBad = touched && url.trim() !== "" && !urlOk;
  const ready = Boolean(token) && urlOk && Boolean(university) && !busy;

  async function universityItems(q: string): Promise<ComboItem<string>[]> {
    const data = await queryClient.fetchQuery({
      queryKey: ["universities"],
      queryFn: getUniversities,
      staleTime: Infinity,
    });
    const needle = q.trim().toLowerCase();
    const found = data.items
      .filter((u) => !needle || u.name.toLowerCase().includes(needle))
      .slice(0, 60)
      .map<ComboItem<string>>((u) => ({
        key: u.id,
        value: u.name,
        label: u.name,
        content: (
          <>
            <span>{u.name}</span>
            <span className="meta">{place(u)}</span>
          </>
        ),
      }));
    // вуза может не быть в базе: оператор вводит название сам
    if (needle && !found.some((item) => item.label.toLowerCase() === needle)) {
      found.unshift({
        key: "custom",
        value: q.trim(),
        label: q.trim(),
        content: (
          <>
            <span>{`Использовать «${q.trim()}»`}</span>
            <span className="meta">такого вуза нет в списке</span>
          </>
        ),
      });
    }
    return found;
  }

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setTouched(true);
    if (!ready || !university) return;
    setBusy(true);
    setError(null);
    try {
      const created = await addOpsSource(token, { url: url.trim(), university });
      showToast(created.created ? `Задача №${created.job_id} поставлена в очередь` : `Задача №${created.job_id} уже идёт`);
      setUrl("");
      setTouched(false);
      setUniversity(null);
      await queryClient.invalidateQueries({ queryKey: ["ops", "jobs"] });
      onCreated(created.job_id);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const hint = !token
    ? "Сначала войди с токеном."
    : !url.trim()
      ? "Вставь ссылку на страницу или документ."
      : !urlOk
        ? "Исправь ссылку."
        : !university
          ? "Выбери вуз."
          : null;

  return (
    <section className="card p-4 sm:p-5" aria-label="Новый документ">
      <h2 className="block-title">Новый документ</h2>
      <form className="mt-3 space-y-4" onSubmit={(e) => void submit(e)} noValidate>
        <div>
          <label className="field-label block" htmlFor="ops-url">
            Ссылка на страницу или документ
          </label>
          <input
            id="ops-url"
            type="text"
            inputMode="url"
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
            className="field-input"
            placeholder="https://вуз.рф/olympiada.pdf"
            aria-invalid={urlBad || undefined}
            aria-describedby={urlBad ? "ops-url-error" : undefined}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onBlur={() => setTouched(true)}
          />
          {urlBad ? (
            <p className="field-error" id="ops-url-error" role="alert">
              Нужна полная ссылка, которая начинается с http:// или https://
            </p>
          ) : null}
        </div>
        <div>
          <div className="field-label">Вуз</div>
          <Combo<string>
            id="ops-combo-university"
            ariaLabel="Вуз"
            placeholder="Выбери вуз"
            searchPlaceholder="Название вуза…"
            value={university}
            onSearch={universityItems}
            onPick={(item) => setUniversity(item.value)}
          />
        </div>
        {error ? (
          <p className="field-error" role="alert">
            {error}
          </p>
        ) : null}
        <div>
          <button type="submit" className="btn-primary w-full" disabled={!ready}>
            {busy ? "Отправляю…" : "Разобрать"}
          </button>
          {hint && !busy ? <p className="field-note text-center">{hint}</p> : null}
        </div>
      </form>
    </section>
  );
}

// ------------------------------------------------------------------ список задач

function JobRow({ job, selected, onSelect }: { job: OpsJob; selected: boolean; onSelect: () => void }) {
  return (
    <button type="button" className={selected ? "ops-row is-selected" : "ops-row"} aria-pressed={selected} onClick={onSelect}>
      <span className="ops-row-top">
        <span className="ops-row-name">{job.university}</span>
        <StatusBadge status={job.status} />
      </span>
      {job.grade || job.origin === "user" ? (
        <span className="mt-1 flex flex-wrap items-center gap-1.5">
          <GradeBadge grade={job.grade} />
          {job.origin === "user" ? <UserMark /> : null}
        </span>
      ) : null}
      <span className="ops-row-url block" title={job.url}>
        {shortUrl(job.url)}
      </span>
      <Steps status={job.status} />
      {job.status === "failed" && job.error ? <span className="ops-row-err block">{jobErrorText(job.error)}</span> : null}
      <span className="ops-row-meta">
        <span>{`№${job.id}`}</span>
        <span>{timeOf(job.updated_at)}</span>
      </span>
    </button>
  );
}

function EmptyBlock({ title, text, children }: { title: string; text: string; children?: ReactNode }) {
  return (
    <div className="empty-state">
      <div className="empty-icon text-brand" aria-hidden="true">
        <IconDocument />
      </div>
      <p className="empty-title">{title}</p>
      <p className="empty-text">{text}</p>
      {children}
    </div>
  );
}

function JobsList({
  token,
  jobs,
  selected,
  onSelect,
}: {
  token: string;
  jobs: ReturnType<typeof useJobs>;
  selected: number | null;
  onSelect: (id: number) => void;
}) {
  const [filter, setFilter] = useState<StatusGroup | "all">("all");
  const [onlyUsers, setOnlyUsers] = useState(false);
  const all = useMemo(() => jobs.data ?? [], [jobs.data]);
  const usersCount = useMemo(() => all.filter((job) => job.origin === "user").length, [all]);
  // «от пользователей» опустело — фильтр снимается сам, как и фильтр по статусу
  const users = onlyUsers && usersCount > 0;
  const list = useMemo(() => (users ? all.filter((job) => job.origin === "user") : all), [all, users]);
  const counts = useMemo(() => {
    const result: Record<StatusGroup, number> = { work: 0, review: 0, accepted: 0, rejected: 0, failed: 0 };
    for (const job of list) result[groupOf(job.status)] += 1;
    return result;
  }, [list]);
  // выбранная группа опустела (задачи приняли): возвращаемся ко всем
  const active = filter !== "all" && counts[filter] === 0 ? "all" : filter;
  const shown = active === "all" ? list : list.filter((job) => groupOf(job.status) === active);

  return (
    <section aria-label="Задачи">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="block-title">Задачи</h2>
        {list.length ? <span className="table-count">{fmt(list.length)}</span> : null}
      </div>

      {!token ? (
        <div className="mt-3">
          <EmptyBlock title="Войди с токеном" text="После входа здесь появятся задачи разбора." />
        </div>
      ) : jobs.isPending ? (
        <div className="skeleton-stack mt-3" aria-label="Загружаем задачи">
          <div className="skeleton h-[84px] rounded-[15px]" />
          <div className="skeleton h-[84px] rounded-[15px]" />
          <div className="skeleton h-[84px] rounded-[15px]" />
        </div>
      ) : jobs.error && !jobs.data ? (
        isUnauthorized(jobs.error) ? null : (
          <div className="mt-3 empty-state" role="alert">
            <p className="empty-title">{errorText(jobs.error)}</p>
            <button type="button" className="btn-secondary mt-3" onClick={() => void jobs.refetch()}>
              Повторить
            </button>
          </div>
        )
      ) : list.length ? (
        <>
          <div className="chip-group mt-3" role="group" aria-label="Фильтр по статусу">
            <button
              type="button"
              className={`chip ${active === "all" ? "chip-on" : ""}`}
              aria-pressed={active === "all"}
              onClick={() => setFilter("all")}
            >
              Все <span className="chip-count">{list.length}</span>
            </button>
            {usersCount > 0 ? (
              <button
                type="button"
                className={`chip ${users ? "chip-on" : ""}`}
                aria-pressed={users}
                onClick={() => setOnlyUsers((v) => !v)}
              >
                От пользователей <span className="chip-count">{usersCount}</span>
              </button>
            ) : null}
            {GROUPS.filter((g) => counts[g] > 0).map((g) => (
              <button
                key={g}
                type="button"
                className={`chip ${active === g ? "chip-on" : ""}`}
                aria-pressed={active === g}
                onClick={() => setFilter(g)}
              >
                {GROUP_LABEL[g]} <span className="chip-count">{counts[g]}</span>
              </button>
            ))}
          </div>
          <ul className="mt-3 space-y-2">
            {shown.map((job) => (
              <li key={job.id}>
                <JobRow job={job} selected={selected === job.id} onSelect={() => onSelect(job.id)} />
              </li>
            ))}
          </ul>
        </>
      ) : (
        <div className="mt-3">
          <EmptyBlock title="Задач пока нет" text="Вставь ссылку в форме выше: первая задача появится здесь." />
        </div>
      )}
    </section>
  );
}

function useJobs(token: string) {
  return useQuery({
    queryKey: ["ops", "jobs", token],
    queryFn: () => getOpsJobs(token),
    enabled: Boolean(token),
    refetchInterval: (query) => (query.state.data?.some((job) => IN_WORK.has(job.status)) ? 10_000 : false),
  });
}

// ------------------------------------------------------------------ страница

export function OpsView() {
  const queryClient = useQueryClient();
  const [token, setToken] = useState("");
  const [ready, setReady] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    setToken(sessionStorage.getItem(TOKEN_KEY) ?? "");
    setReady(true);
  }, []);

  const jobs = useJobs(token);
  const unauthorized = isUnauthorized(jobs.error);
  const selectedJob = jobs.data?.find((job) => job.id === selected) ?? null;

  useEffect(() => {
    if (selected === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSelected(null);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [selected]);

  function signIn(value: string) {
    sessionStorage.setItem(TOKEN_KEY, value);
    setToken(value);
    setSelected(null);
    void queryClient.invalidateQueries({ queryKey: ["ops"] });
  }

  function signOut() {
    sessionStorage.removeItem(TOKEN_KEY);
    setToken("");
    setSelected(null);
    queryClient.removeQueries({ queryKey: ["ops"] });
  }

  const access = !token
    ? { text: "Нет доступа", tone: "" }
    : unauthorized
      ? { text: "Токен не подошёл", tone: "is-bad" }
      : jobs.isSuccess
        ? { text: "Токен принят", tone: "is-ok" }
        : jobs.error
          ? { text: "Доступ не проверен", tone: "" }
          : { text: "Проверяем токен…", tone: "" };

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
      <main className="mx-auto max-w-5xl px-4 pb-16">
        <div className="mt-4 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
          <div className="min-w-0 flex-1 basis-[280px]">
            <h1 className="text-[26px] leading-[32px] font-medium">Разбор документов</h1>
            <p className="mt-1 text-[14px] leading-[20px] meta-text">
              Скачиваем страницу или документ вуза, находим олимпиадные льготы и показываем, что изменится в базе. Решаешь ты.
            </p>
          </div>
          <span className={`ops-status ${access.tone}`} role="status">
            {access.text}
          </span>
        </div>

        {ready ? (
          <div className="ops-layout">
            <div className="ops-stack min-w-0">
              <AccessCard
                key={token && !unauthorized ? "in" : "out"}
                token={token}
                failed={unauthorized}
                checking={jobs.isPending && Boolean(token)}
                onSignIn={signIn}
                onSignOut={signOut}
              />
              <NewDocument token={unauthorized ? "" : token} onCreated={setSelected} />
              <JobsList token={unauthorized ? "" : token} jobs={jobs} selected={selected} onSelect={setSelected} />
            </div>

            {selectedJob ? (
              <aside className="ops-panel" role="region" aria-label={`Задача ${selectedJob.id}`}>
                <JobDetail key={selectedJob.id} token={token} job={selectedJob} onClose={() => setSelected(null)} />
              </aside>
            ) : (
              <div className="ops-panel-empty p-6 text-center">
                <p className="empty-title">Выбери задачу</p>
                <p className="empty-text">Здесь появятся найденные документы, примеры с цитатами и кнопки решения.</p>
              </div>
            )}
          </div>
        ) : null}
      </main>
      <Toaster />
    </>
  );
}
