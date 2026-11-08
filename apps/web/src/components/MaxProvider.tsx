"use client";

import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { type MaxWebApp, safely, whenMax } from "@/lib/max";

interface MaxContextValue {
  /** Bridge MAX, если сайт открыт как мини-приложение; иначе null */
  app: MaxWebApp | null;
  /** добавить шаг «назад» (верхний срабатывает по кнопке в шапке MAX); возвращает отписку */
  pushBack: (run: () => void) => () => void;
}

const MaxContext = createContext<MaxContextValue>({ app: null, pushBack: () => () => undefined });

/** Подготовка страницы к работе внутри MAX. */
function prepare(app: MaxWebApp): () => void {
  document.documentElement.dataset.max = app.platform || "web";

  // iOS увеличивает страницу при фокусе на поле с шрифтом меньше 16px — в мини-приложении
  // это выглядит как поломка, поэтому масштаб фиксируем только здесь, а не на сайте
  const viewport = document.querySelector('meta[name="viewport"]');
  const content = viewport?.getAttribute("content") || "";
  if (viewport && !content.includes("maximum-scale")) {
    viewport.setAttribute("content", `${content}, maximum-scale=1`);
  }

  // документы вузов открываются ссылками target=_blank — во встроенном браузере MAX
  // их нужно открывать через Bridge (внешний браузер, ссылки max.ru — внутри MAX)
  const onClick = (event: MouseEvent) => {
    const link = (event.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
    if (!link || link.target !== "_blank" || !/^https?:/i.test(link.href)) return;
    event.preventDefault();
    const url = link.href;
    safely(() => (/^https:\/\/max\.ru\//i.test(url) ? app.openMaxLink(url) : app.openLink(url)));
  };
  document.addEventListener("click", onClick);
  safely(() => app.ready());
  return () => document.removeEventListener("click", onClick);
}

export function MaxProvider({ children }: { children: ReactNode }) {
  const [app, setApp] = useState<MaxWebApp | null>(null);
  const stack = useRef<{ run: () => void }[]>([]);

  useEffect(() => {
    let alive = true;
    let cleanup: (() => void) | undefined;
    void whenMax().then((found) => {
      if (!alive || !found) return;
      cleanup = prepare(found);
      setApp(found);
    });
    return () => {
      alive = false;
      cleanup?.();
    };
  }, []);

  // На сайте тот же стек работает через историю браузера (кнопка «Назад», жест на Android):
  // пока есть шаги, сверху истории лежит одна наша запись; «Назад» снимает её и выполняет шаг.
  const guard = useRef(false);
  const skipPop = useRef(false);

  const syncBackButton = useCallback(() => {
    if (app) {
      safely(() => (stack.current.length ? app.BackButton.show() : app.BackButton.hide()));
      return;
    }
    if (typeof window === "undefined") return;
    if (stack.current.length && !guard.current) {
      window.history.pushState({ olympBack: true }, "");
      guard.current = true;
    } else if (!stack.current.length && guard.current) {
      // шаги закрыли кнопками на странице — убираем и нашу запись, иначе «Назад» сработал бы вхолостую
      guard.current = false;
      skipPop.current = true;
      window.history.back();
    }
  }, [app]);

  useEffect(() => {
    if (app) return;
    const onPop = () => {
      if (skipPop.current) {
        skipPop.current = false;
        return;
      }
      guard.current = false;
      stack.current.at(-1)?.run();
      // шаг выполнен; если остались ещё — запись истории для следующего «Назад»
      queueMicrotask(syncBackButton);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [app, syncBackButton]);

  useEffect(() => {
    if (!app) return;
    const onBack = () => stack.current.at(-1)?.run();
    safely(() => app.BackButton.onClick(onBack));
    syncBackButton();
    return () => safely(() => app.BackButton.offClick(onBack));
  }, [app, syncBackButton]);

  const pushBack = useCallback(
    (run: () => void) => {
      const entry = { run };
      stack.current.push(entry);
      syncBackButton();
      return () => {
        stack.current = stack.current.filter((e) => e !== entry);
        syncBackButton();
      };
    },
    [syncBackButton],
  );

  const value = useMemo(() => ({ app, pushBack }), [app, pushBack]);
  return <MaxContext.Provider value={value}>{children}</MaxContext.Provider>;
}

/** Bridge MAX или null, если сайт открыт в обычном браузере. */
export const useMax = () => useContext(MaxContext).app;

/** Кнопка «Назад» в шапке MAX: видна, пока handler не null; срабатывает последний открытый шаг. */
export function useMaxBackButton(handler: (() => void) | null): void {
  const { pushBack } = useContext(MaxContext);
  const ref = useRef(handler);
  useEffect(() => {
    ref.current = handler;
  });
  const active = handler !== null;
  useEffect(() => {
    if (!active) return;
    return pushBack(() => ref.current?.());
  }, [active, pushBack]);
}

/** Пока true, MAX спрашивает подтверждение перед закрытием мини-приложения. */
export function useMaxClosingConfirmation(active: boolean): void {
  const app = useMax();
  useEffect(() => {
    if (!app || !active) return;
    safely(() => app.enableClosingConfirmation());
    return () => safely(() => app.disableClosingConfirmation());
  }, [app, active]);
}
