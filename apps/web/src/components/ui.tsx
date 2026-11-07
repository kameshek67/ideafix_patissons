/* Общие куски разметки прототипа: заглушки, пустые состояния, стили льгот. */

export const TYPES = ["Все", "БВИ", "100 баллов"] as const;

export const TYPE_STYLE: Record<string, { badge: string; section: string; title: string }> = {
  БВИ: { badge: "badge-bvi", section: "section-bvi", title: "БВИ — без вступительных испытаний" },
  "100 баллов": { badge: "badge-sto", section: "section-sto", title: "100 баллов за ЕГЭ / ДВИ" },
  "Особое право (БВИ/100)": {
    badge: "badge-alt",
    section: "section-alt",
    title: "Особое право: БВИ или 100 баллов",
  },
  "Фаст-трек": { badge: "badge-alt", section: "section-alt", title: "Фаст-трек грантового конкурса" },
  "ИД (доп. баллы)": { badge: "badge-alt", section: "section-alt", title: "Индивидуальные достижения" },
};

export const badgeClass = (type: string) => TYPE_STYLE[type]?.badge || "badge-soft";

export const UNI_START = "Выбери вуз и направление — получи таблицу льгот по олимпиадам";
export const OLYMP_START = "Введи название олимпиады. Выбери вуз из списка — получи таблицу льгот";

// стартовые экраны из макета: подпись + 3D-иллюстрация
const ILLU = {
  uni: ["/assets/illu-uni.png", 305, 319],
  olymp: ["/assets/illu-olymp.png", 214, 232],
} as const;

export function IlluState({ kind, text }: { kind: keyof typeof ILLU; text: string }) {
  const [src, width, height] = ILLU[kind];
  return (
    <div className="illu-state">
      <p>{text}</p>
      {/* обычный img, как в прототипе: next/image поменял бы разметку и загрузку */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt="" width={width} height={height} />
    </div>
  );
}

export function EmptyState({ icon, title, text }: { icon: string; title: string; text: string }) {
  return (
    <div className="empty-state">
      <div className="empty-icon" aria-hidden="true">
        {icon}
      </div>
      <p className="empty-title">{title}</p>
      <p className="empty-text">{text}</p>
    </div>
  );
}

export function Skeleton() {
  return (
    <div className="skeleton-stack">
      <div className="skeleton h-28 rounded-[15px]" />
      <div className="skeleton h-64 rounded-[15px]" />
    </div>
  );
}

/** Ошибка загрузки: понятный текст и «Повторить», экран не остаётся на скелетоне. */
export function LoadError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="empty-state col-span-full" role="alert">
      <div className="empty-icon" aria-hidden="true">
        ⚠️
      </div>
      <p className="empty-title">Не получилось загрузить</p>
      <p className="empty-text">{message}</p>
      {onRetry ? (
        <button type="button" className="btn-secondary mt-3" onClick={onRetry}>
          Повторить
        </button>
      ) : null}
    </div>
  );
}

/** Длинный текст в ячейке: не больше двух строк, полный текст в подсказке. */
export const Clamp2 = ({ value }: { value: string }) => (
  <span className="cell-clamp-2" title={value}>
    {value}
  </span>
);

/** Бейдж «по профилю» у строк, выведенных из правила вуза. */
export function DerivedMark({ derived }: { derived: boolean }) {
  if (!derived) return null;
  return (
    <>
      {" "}
      <span
        className="badge badge-soft"
        title="Строка выведена из правила вуза «любая олимпиада перечня с этим профилем»"
      >
        по профилю
      </span>
    </>
  );
}
