import type { Source } from "@/lib/api";
import { IconDocument } from "./icons";

export interface SourceLink {
  url: string;
  title?: string | null;
  types?: string[];
  kind?: string;
}

/* Источник — главный способ перепроверить автоматически разобранную таблицу,
   поэтому показываем его кнопкой с названием документа, а не мелкой ссылкой. */
function SourceButton({ url, title, types = [], kind = "file" }: SourceLink) {
  const isPdf = /\.pdf($|[?#])/i.test(url);
  const label =
    kind === "page"
      ? "Документы приёмной комиссии"
      : types.length === 1
        ? `Документ вуза: ${types[0]}`
        : "Открыть документ вуза";
  return (
    <a className="source-btn" href={url} target="_blank" rel="noopener">
      <IconDocument />
      <span className="source-btn-text">
        <b>{`${label}${isPdf ? " (PDF)" : ""}`}</b>
        {title ? <span>{title}</span> : null}
      </span>
    </a>
  );
}

/* Первой идёт страница раздела вуза: её адрес живёт годами, а файлы на ней
   обновляются каждый сезон. Дальше — конкретные документы с этой страницы. */
export function SourceBlock({ sources }: { sources: (Source | SourceLink)[] }) {
  const list = sources.filter((s) => s && (s.url || "").trim());
  if (!list.length) return null;
  const page = list.find((s) => s.kind === "page");
  // у части вузов файлы называются одинаково (перечни по кампусам и годам) —
  // в карточке от них нет пользы, полный список всегда есть на странице раздела
  const byTitle = new Map<string, SourceLink>();
  list
    .filter((s) => s !== page)
    .forEach((s) => byTitle.has(s.title ?? "") || byTitle.set(s.title ?? "", s));
  const files = [...byTitle.values()].slice(0, 3);
  const shown = [page, ...files].filter((s): s is SourceLink => Boolean(s));
  return (
    <>
      <div className="mt-3 flex flex-wrap gap-2">
        {shown.map((s, i) => (
          <SourceButton key={`${s.url}-${i}`} {...s} />
        ))}
      </div>
      <p className="mt-2 text-[12px] leading-snug meta-text">
        {`Таблица собрана автоматически из документов вуза — перед подачей сверьтесь с оригиналом.${
          page ? " Актуальные файлы всегда лежат на странице приёмной комиссии." : ""
        }`}
      </p>
    </>
  );
}
