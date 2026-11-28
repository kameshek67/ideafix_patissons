"use client";

import { useQuery } from "@tanstack/react-query";
import { friendlyError, getQuality, type Quality } from "@/lib/api";
import { fmt, plural } from "@/lib/format";
import { duration, LAYER_LABELS, pct, ruDate } from "@/lib/quality";
import { IconChevronLeft } from "./icons";

type Score = NonNullable<Quality["extraction"]["holdout"]["extraction"]>;

const dokumentakh = (n: number) => plural(n, "документе", "документах", "документах");
const zapisey = (n: number) => plural(n, "записи", "записях", "записях");

/** Полоса «доля от целого»: цифра — в подписи, полоса только помогает сравнить. */
function Bar({ share, label, value, tone = "bg-brand" }: { share: number; label: string; value: string; tone?: string }) {
  return (
    <div className="mt-3">
      <div className="flex items-baseline justify-between gap-3 text-[14px] leading-[19px]">
        <span>{label}</span>
        <span className="font-medium tabular-nums">{value}</span>
      </div>
      <div
        className="mt-1.5 h-2 rounded-full bg-soft overflow-hidden"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(share * 100)}
      >
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${Math.max(share * 100, share > 0 ? 1.5 : 0)}%` }} />
      </div>
    </div>
  );
}

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section id={id} className="card mt-4 p-4 sm:p-5">
      <h2 className="text-[18px] leading-[24px] font-medium">{title}</h2>
      {children}
    </section>
  );
}

function ExtractionBlock({ data }: { data: Quality["extraction"] }) {
  const { holdout, development } = data;
  // главная оценка — на отложенных страницах; нет их — на эталоне, с оговоркой
  const onHoldout = Boolean(holdout.extraction);
  const set = onHoldout ? holdout : development;
  const after: Score | null | undefined = set.extraction;
  const before: Score | null | undefined = set.old_table;
  return (
    <Section id="quality-extraction" title="Насколько точно мы переносим документы вузов">
      {after ? (
        <>
          <p className="mt-1 text-[13.5px] leading-[19px] meta-text">
            Какая доля строк из документов вуза попала в таблицу льгот
            {onHoldout ? " — на страницах, на которых мы извлечение не настраивали" : " — на документах, под которые мы настраивали извлечение"}.
          </p>
          {before ? <Bar share={before.recall} label="Старая таблица" value={pct(before.recall)} tone="bg-[#D6BEDB]" /> : null}
          <Bar share={after.recall} label="Извлечение из документов" value={pct(after.recall)} />
          <p className="mt-3 text-[13.5px] leading-[19px]">
            Из найденных строк верны {pct(after.precision)}
            {before ? ` (в старой таблице — ${pct(before.precision)})` : ""}.
            {after.who !== null && after.who !== undefined ? ` Кому даётся льгота — победителям или и призёрам — указано верно в ${pct(after.who)} найденных строк.` : ""}
          </p>
          <p className="mt-3 text-[12.5px] leading-[17px] meta-text" id="quality-extraction-note">
            Проверено на {fmt(after.documents)} {dokumentakh(after.documents)}, {fmt(after.records)} {zapisey(after.records)}: мы разметили их вручную и сверили
            с тем, что нашла программа. Это выборка, а не все вузы, поэтому по другим документам результат может отличаться.
            {onHoldout && development.extraction
              ? ` На документах, под которые мы настраивали извлечение, полнота выше — ${pct(development.extraction.recall)}, но честнее смотреть на отложенные.`
              : ""}
            {!onHoldout ? " Отложенных страниц для проверки пока нет, поэтому цифры могут быть завышены." : ""}
          </p>
        </>
      ) : (
        <p className="mt-2 text-[14px] leading-[20px] meta-text">Оценки точности пока нет: мы ещё не сверяли извлечение с ручной разметкой.</p>
      )}
    </Section>
  );
}

function CoverageBlock({ data }: { data: Quality["coverage"] }) {
  const layers = Object.entries(data.layers).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...layers.map(([, rows]) => rows));
  return (
    <Section id="quality-coverage" title="Что есть в базе">
      <Bar
        share={data.universities ? data.with_table / data.universities : 0}
        label="Вузы с таблицей льгот"
        value={`${fmt(data.with_table)} из ${fmt(data.universities)}`}
      />
      {data.without_table.length ? (
        <details className="mt-3" id="quality-without-table">
          <summary className="cursor-pointer text-[14px] leading-[20px] underline">
            Без таблицы: {fmt(data.without_table.length)} {plural(data.without_table.length, "вуз", "вуза", "вузов")}
          </summary>
          <p className="mt-2 text-[12.5px] leading-[17px] meta-text">
            У этих вузов нет таблицы «олимпиада × профиль»: льготу смотри в документе вуза.
          </p>
          <ul className="mt-1.5 text-[14px] leading-[20px]">
            {data.without_table.map((u) => (
              <li key={u.id}>{u.name}</li>
            ))}
          </ul>
        </details>
      ) : null}
      {layers.length ? (
        <>
          <h3 className="mt-5 card-kicker">Строки льгот по происхождению</h3>
          {layers.map(([layer, rows]) => (
            <Bar key={layer} share={rows / max} label={LAYER_LABELS[layer] ?? layer} value={fmt(rows)} tone="bg-bvi" />
          ))}
        </>
      ) : null}
    </Section>
  );
}

function ReportsBlock({ data }: { data: Quality["reports"] }) {
  const periods = [
    { title: "За всё время", p: data.total },
    { title: "За 30 дней", p: data.days_30 },
  ];
  return (
    <Section id="quality-reports" title="Жалобы на ошибки">
      <p className="mt-1 text-[13.5px] leading-[19px] meta-text">
        Если в строке льготы что-то не совпадает с документом, есть кнопка «Не совпадает с документом». Мы сверяем с документом и либо исправляем, либо отвечаем, что данные верны.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {periods.map(({ title, p }) => {
          const rows: [string, string][] = p.received
            ? [
                ["Пришло", fmt(p.received)],
                ["Исправлено", fmt(p.fixed)],
                ["Данные верны", fmt(p.correct)],
                p.median_hours !== null && p.median_hours !== undefined
                  ? ["Решаем обычно за", duration(p.median_hours)]
                  : ["Решено", "пока ничего"],
              ]
            : [["Жалоб", "не было"]];
          return (
            <div key={title} className="rounded-[15px] bg-soft p-3.5">
              <h3 className="card-kicker">{title}</h3>
              <dl className="mt-1 divide-y divide-[color:var(--hair)] text-[14px] leading-[19px]">
                {rows.map(([term, value]) => (
                  <div key={term} className="flex justify-between gap-3 py-2">
                    <dt>{term}</dt>
                    <dd className="font-medium tabular-nums">{value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          );
        })}
      </div>
      <p className="mt-3 text-[12.5px] leading-[17px] meta-text">Тексты жалоб не публикуем, только счётчики. Повторы не считаем.</p>
    </Section>
  );
}

type ModelRun = NonNullable<Quality["assistant"]>["models"][number];

const seconds = (n: number | null) => (n === null ? "—" : `${n.toFixed(1).replace(".", ",")} с`);
const dollars = (n: number | null) => (n === null ? "—" : `$${n.toFixed(4).replace(".", ",")}`);
const share = (n: number | null) => (n === null ? "—" : pct(n));

/** Полные прогоны идут первыми, прогоны на нескольких вопросах — ниже и с пометкой. */
function splitRuns(models: ModelRun[]): { full: ModelRun[]; preliminary: ModelRun[]; total: number } {
  const total = Math.max(0, ...models.map((m) => m.cases ?? 0));
  const isFull = (m: ModelRun) => (m.cases ?? 0) >= total / 2;
  return { full: models.filter(isFull), preliminary: models.filter((m) => !isFull(m)), total };
}

function ModelsBlock({ models, selected }: { models: ModelRun[]; selected: string }) {
  const { full, preliminary } = splitRuns(models);
  const rows = [...full, ...preliminary.map((m) => ({ ...m, rough: true }))];
  return (
    <Section id="quality-models" title="Сравнение моделей">
      <p className="mt-1 text-[13.5px] leading-[19px] meta-text">
        Одни и те же вопросы, разные модели. Ошибки считаем в названных фактах: до проверки кодом и после неё. Выбрана самая дешёвая из тех, что прошли порог на полном наборе.
      </p>
      <div className="models-scroll mt-3">
        <table className="models-table">
          <thead>
            <tr>
              <th scope="col">Модель</th>
              <th scope="col">Вопросов</th>
              <th scope="col">Прошло</th>
              <th scope="col">Ошибки до → после</th>
              <th scope="col">p95</th>
              <th scope="col">Цена ответа</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => {
              const rough = "rough" in m;
              return (
                <tr key={m.model} className={m.model === selected ? "is-selected" : undefined} aria-current={m.model === selected || undefined}>
                  <th scope="row">
                    <span className="break-all">{m.model}</span>
                    {m.model === selected ? <span className="badge badge-bvi ml-1.5">выбрана</span> : null}
                    {rough ? <div className="meta-text text-[12px]">{`предварительно, ${fmt(m.cases)} ${plural(m.cases ?? 0, "вопрос", "вопроса", "вопросов")}`}</div> : null}
                    {m.gate_passed === false ? <div className="meta-text text-[12px]">порог включения не прошла</div> : null}
                  </th>
                  <td data-label="Вопросов">{fmt(m.cases)}</td>
                  <td data-label="Прошло">{share(m.passed_share)}</td>
                  <td data-label="Ошибки до → после">{`${share(m.error_share_raw)} → ${share(m.error_share_final)}`}</td>
                  <td data-label="Ответ, p95">{seconds(m.answer_p95)}</td>
                  <td data-label="Цена ответа">{dollars(m.cost_per_answer)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[12.5px] leading-[17px] meta-text">
        Прогоны на нескольких вопросах — пробные: по ним модель можно только отсеять, но не сравнить. p95 — за сколько секунд пришёл полный ответ у девяти из десяти вопросов.
      </p>
    </Section>
  );
}

function AssistantBlock({ data }: { data: NonNullable<Quality["assistant"]> }) {
  const rows: [string, string | null][] = [
    ["Ответ прошёл проверку", data.passed_share != null ? pct(data.passed_share) : null],
    ["Ответов с ошибкой в факте", data.error_share != null ? pct(data.error_share) : null],
    ["Выдумок там, где данных нет", data.fabrication != null ? pct(data.fabrication) : null],
    ["Полный ответ, обычно", data.answer_p50 != null ? `${data.answer_p50.toFixed(1).replace(".", ",")} с` : null],
  ];
  const date = ruDate(data.date);
  return (
    <Section id="quality-assistant" title="ИИ-помощник">
      <p className="mt-1 text-[13.5px] leading-[19px] meta-text">
        Помощник отвечает по базе и сам проверяет названные в ответе факты. Мы прогнали его на заранее подготовленных вопросах.
      </p>
      <dl className="mt-2 divide-y divide-[color:var(--hair)] text-[14px] leading-[19px]">
        <div className="flex justify-between gap-3 py-2">
          <dt>Модель</dt>
          <dd className="font-medium text-right break-all">{data.model}</dd>
        </div>
        {rows.map(([term, value]) =>
          value ? (
            <div key={term} className="flex justify-between gap-3 py-2">
              <dt>{term}</dt>
              <dd className="font-medium tabular-nums">{value}</dd>
            </div>
          ) : null,
        )}
      </dl>
      <p className="mt-3 text-[12.5px] leading-[17px] meta-text">
        {data.cases ? `Проверено на ${fmt(data.cases)} ${plural(data.cases, "вопросе", "вопросах", "вопросах")}` : "Проверено на наборе вопросов"}
        {date ? `, ${date}` : ""}. Это выборка: помощник может ошибиться, важные условия сверяй с документом вуза.
      </p>
    </Section>
  );
}

function FreshnessBlock({ data }: { data: Quality["freshness"] }) {
  const from = ruDate(data.documents_checked_from);
  const to = ruDate(data.documents_checked_to);
  const rows: [string, string | null][] = [
    ["База собрана", ruDate(data.built_at)],
    ["Перечень олимпиад РСОШ 2026/27 загружен", ruDate(data.rsosh_list)],
    ["Ссылки на документы вузов проверены", from && to ? (from === to ? to : `с ${from} по ${to}`) : (to ?? from)],
  ];
  return (
    <Section id="quality-freshness" title="Когда обновляли">
      <dl className="mt-2 divide-y divide-[color:var(--hair)] text-[14px] leading-[19px]">
        {rows.map(([term, value]) => (
          <div key={term} className="flex justify-between gap-4 py-2">
            <dt>{term}</dt>
            <dd className="font-medium text-right">{value ?? "нет данных"}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-[12.5px] leading-[17px] meta-text">
        Вузы меняют правила и документы в течение года. Перед подачей документов открой документ вуза по ссылке в карточке направления.
      </p>
    </Section>
  );
}

/** Страница «Качество данных»: чему и насколько можно верить, без рекламы. */
export function QualityView() {
  const q = useQuery({ queryKey: ["quality"], queryFn: getQuality });
  return (
    <>
      <header className="app-header">
        <div className="mx-auto max-w-5xl h-14 px-2 flex items-center">
          <a href="/" className="icon-btn" aria-label="На главную" title="На главную">
            <IconChevronLeft />
          </a>
          <div className="flex-1 text-center text-[17px] font-medium">Качество данных</div>
          <span className="w-10 shrink-0" aria-hidden="true" />
        </div>
      </header>
      <main className="mx-auto max-w-2xl px-4 pb-16">
        <h1 className="mt-4 text-[26px] leading-[32px] font-medium">Насколько можно верить данным</h1>
        <p className="mt-2 text-[14px] leading-[20px] meta-text">
          Здесь мы показываем, как проверяли данные «Олимпа» и где ошибаемся. Цифры считаются по реальным проверкам, а не по ощущениям.
        </p>
        {q.isPending ? <p className="mt-6 meta-text">Загружаем…</p> : null}
        {q.error ? (
          <div className="mt-6" role="alert">
            <p>{friendlyError(q.error)}</p>
            <button type="button" className="chip chip-lg mt-3" onClick={() => void q.refetch()}>
              Повторить
            </button>
          </div>
        ) : null}
        {q.data ? (
          <>
            <ExtractionBlock data={q.data.extraction} />
            <CoverageBlock data={q.data.coverage} />
            <ReportsBlock data={q.data.reports} />
            {q.data.assistant ? <AssistantBlock data={q.data.assistant} /> : null}
            {q.data.assistant?.models.length ? <ModelsBlock models={q.data.assistant.models} selected={q.data.assistant.model} /> : null}
            <FreshnessBlock data={q.data.freshness} />
          </>
        ) : null}
      </main>
    </>
  );
}
