"use client";

import { type ReactNode, useEffect, useRef, useState } from "react";
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
type ListState<T> = { kind: "idle" } | { kind: "loading" } | { kind: "items"; items: ComboItem<T>[] };

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
    setList({ kind: "loading" });
    const items = await onSearch(q);
    if (current === seq.current) setList({ kind: "items", items });
  }

  function toggle() {
    if (open) return setOpen(false);
    setOpen(true);
    setSearch("");
    void refresh("");
  }

  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);

  // клик мимо комбобокса закрывает панель
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, []);

  return (
    <div className="combo" id={id} ref={root}>
      <button
        className="combo-btn"
        type="button"
        aria-label={ariaLabel}
        aria-expanded={open}
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
        <div className="combo-list">
          {list.kind === "idle" ? null : list.kind === "loading" ? (
            <div className="suggest-empty">Загрузка…</div>
          ) : list.items.length ? (
            list.items.map((item) => (
              <button
                key={item.key}
                className="combo-item"
                onClick={() => {
                  setOpen(false);
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
