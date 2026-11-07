/* MAX Bridge — связь мини-приложения с клиентом MAX (https://dev.max.ru/docs/webapps/bridge).
   Скрипт Bridge подключается только при запуске из MAX (см. MAX_BRIDGE_LOADER в layout):
   обычные посетители сайта его не загружают. */

export interface MaxUserUnsafe {
  id: number;
  first_name?: string;
  last_name?: string;
  username?: string | null;
  language_code?: string;
  photo_url?: string | null;
}

type Status<T extends string> = Promise<{ status: T }>;

/** Часть window.WebApp, которой пользуется сайт. */
export interface MaxWebApp {
  /** подписанные данные запуска — их проверяет API (заголовок X-Max-Init-Data) */
  initData: string | null;
  initDataUnsafe: { user?: MaxUserUnsafe; start_param?: string; query_id?: string };
  platform: "ios" | "android" | "desktop" | "web" | null;
  version: string | null;
  ready(): void;
  close(): void;
  openLink(url: string): void;
  openMaxLink(url: string): void;
  shareMaxContent(params: { text?: string; link?: string }): Status<"shared" | "cancelled">;
  enableClosingConfirmation(): void;
  disableClosingConfirmation(): void;
  BackButton: {
    isVisible: boolean;
    show(): void;
    hide(): void;
    onClick(callback: () => void): void;
    offClick(callback: () => void): void;
  };
  HapticFeedback: {
    impactOccurred(style: "soft" | "light" | "medium" | "heavy" | "rigid"): Status<string>;
    notificationOccurred(type: "error" | "success" | "warning"): Status<string>;
    selectionChanged(): Status<string>;
  };
}

declare global {
  interface Window {
    WebApp?: MaxWebApp;
    /** состояние загрузки Bridge: loading — скрипт ещё грузится, done — загрузился или упал */
    __olympMax?: "loading" | "done";
  }
}

export const MAX_BRIDGE_URL = "https://st.max.ru/js/max-web-app.js";
export const MAX_BRIDGE_EVENT = "olymp:max-bridge";

/* Встраивается в <head>: MAX передаёт данные запуска во фрагменте адреса (#WebAppData=…),
   а Bridge сохраняет их в sessionStorage — так он работает и после перезагрузки страницы. */
export const MAX_BRIDGE_LOADER = `(function(){try{var h=location.hash||"";
if(h.indexOf("WebAppData=")<0&&!sessionStorage.getItem("WebAppData"))return;
window.__olympMax="loading";var s=document.createElement("script");s.src=${JSON.stringify(MAX_BRIDGE_URL)};
s.onload=s.onerror=function(){window.__olympMax="done";window.dispatchEvent(new Event(${JSON.stringify(MAX_BRIDGE_EVENT)}));};
document.head.appendChild(s);}catch(e){}})();`;

/** Bridge загружен и передал подписанные данные запуска — значит, сайт открыт внутри MAX. */
export function maxApp(): MaxWebApp | null {
  if (typeof window === "undefined") return null;
  const app = window.WebApp;
  return app && app.initData ? app : null;
}

/** Дождаться Bridge: при запуске из MAX скрипт ещё может грузиться. */
export function whenMax(timeout = 5000): Promise<MaxWebApp | null> {
  if (typeof window === "undefined") return Promise.resolve(null);
  if (window.__olympMax !== "loading") return Promise.resolve(maxApp());
  return new Promise((resolve) => {
    const done = () => {
      window.removeEventListener(MAX_BRIDGE_EVENT, done);
      clearTimeout(timer);
      resolve(maxApp());
    };
    const timer = setTimeout(done, timeout);
    window.addEventListener(MAX_BRIDGE_EVENT, done);
  });
}

/** Вызов Bridge, который не должен ронять интерфейс: метод может быть не поддержан платформой. */
export function safely(call: () => unknown): void {
  try {
    const result = call();
    if (result instanceof Promise) result.catch(() => undefined);
  } catch {
    /* платформа не поддерживает метод — интерфейс работает и без него */
  }
}

/** Тактильный отклик (на телефонах; на компьютере и в вебе MAX его нет). */
export function haptic(app: MaxWebApp | null, kind: "success" | "warning" | "select" | "tap"): void {
  if (!app || (app.platform !== "ios" && app.platform !== "android")) return;
  safely(() => {
    const h = app.HapticFeedback;
    if (kind === "select") return h.selectionChanged();
    if (kind === "tap") return h.impactOccurred("light");
    return h.notificationOccurred(kind);
  });
}

/** Ссылка на мини-приложение: https://max.ru/<бот>?startapp=<payload>. */
export function startAppLink(botName: string, payload = ""): string {
  const safe = payload.replace(/[^A-Za-z0-9_-]/g, "").slice(0, 512);
  return `https://max.ru/${botName}?startapp${safe ? `=${safe}` : ""}`;
}
