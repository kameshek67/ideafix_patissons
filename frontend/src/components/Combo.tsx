"use client";

import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { IconChevronDown } from "./icons";

export interface ComboItem<T> {
  key: string | number;
  value: T;
  label: string;
  content: ReactNode;
}

interface Props<T> {
  id: string;
  ariaLabel: string;
  placeholder: string;
  searchPlaceholder: string;
  /** выбранное значение; null — показывается placeholder */
  value: string | null;
  disabled?: boolean;
  disabledTitle?: string;
  onSearch: (q: string) => Promise<ComboItem<T>[]> | ComboItem<T>[];
  onPick: (item: ComboItem<T>) => void;
}

// idle — панель ещё ни разу не открывали: список пустой, как в прототипе
type ListState<T> =
  | { kind: "idle" }
  | { kind: "loading"; previous: ComboItem<T>[] | null }
  | { kind: "error"; query: string }
  | { kind: "items"; items: ComboItem<T>[] };

/** Комбобокс с поиском: кнопка-поле, выпадающая панель, список с подсказками. */
export function Combo<T>({
  id,
  ariaLabel,
  placeholder,
  searchPlaceholder,
  value,
  disabled = false,
  disabledTitle,
  onSearch,
  onPick,
}: Props<T>) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [list, setList] = useState<ListState<T>>({ kind: "idle" });
  const root = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const seq = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  async function refresh(q: string) {
    const current = ++seq.current;
    // прежние подсказки остаются, пока ищем новые: список не схлопывается на каждой букве
    setList((state) => ({ kind: "loading", previous: state.kind === "items" ? state.items : state.kind === "loading" ? state.previous : null }));
    try {
      const items = await onSearch(q);
      if (current === seq.current) setList({ kind: "items", items });
    } catch {
      if (current === seq.current) setList({ kind: "error", query: q });
    }
  }

  const close = useCallback(() => {
    clearTimeout(timer.current);
    ++seq.current;
    setOpen(false);
  }, []);

  function toggle() {
    if (open) return close();
    // панель появляется синхронно, и фокус уходит в поле в том же касании: на телефоне иначе не покажется клавиатура
    flushSync(() => setOpen(true));
    input.current?.focus();
    setSearch("");
    // при открытии старый список не показываем: он мог быть для другого вуза
    setList({ kind: "idle" });
    void refresh("");
  }

  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);

  // клик мимо комбобокса закрывает панель
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) close();
    };
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, [close]);

  const items = list.kind === "items" ? list.items : list.kind === "loading" ? (list.previous ?? []) : [];

  return (
    <div className="combo" id={id} ref={root}>
      <button
        className="combo-btn"
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={`${id}-list`}
        disabled={disabled}
        title={disabled ? disabledTitle : undefined}
        onClick={toggle}
      >
        <span className={value === null ? "combo-value is-placeholder" : "combo-value"}>
          {value ?? placeholder}
        </span>
        <IconChevronDown />
      </button>
      <div className={open ? "combo-panel" : "combo-panel hidden"}>
        <input
          ref={input}
          className="combo-search"
          placeholder={searchPlaceholder}
          autoComplete="off"
          value={search}
          onChange={(e) => {
            const q = e.target.value;
            setSearch(q);
            clearTimeout(timer.current);
            timer.current = setTimeout(() => void refresh(q.trim()), 180);
          }}
        />
        <div
          id={`${id}-list`}
          role={items.length ? "listbox" : undefined}
          aria-label={items.length ? ariaLabel : undefined}
          className={list.kind === "loading" && list.previous ? "combo-list is-loading" : "combo-list"}
        >
          {list.kind === "idle" ? null : list.kind === "loading" && !list.previous ? (
            <div className="suggest-empty">Загрузка…</div>
          ) : list.kind === "error" ? (
            <div className="suggest-empty" role="alert">
              Не получилось загрузить.{" "}
              <button type="button" className="underline" onClick={() => void refresh(list.query)}>
                Повторить
              </button>
            </div>
          ) : items.length ? (
            items.map((item) => (
              <button
                key={item.key}
                type="button"
                role="option"
                aria-selected={item.label === value}
                className="combo-item"
                aria-busy={list.kind === "loading" || undefined}
                onClick={() => {
                  close();
                  onPick(item);
                }}
              >
                {item.content}
              </button>
            ))
          ) : (
            <div className="suggest-empty">Ничего не найдено</div>
          )}
        </div>
      </div>
    </div>
  );
}
