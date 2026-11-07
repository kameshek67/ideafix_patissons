/* Онбординг: показывается один раз — при первом запуске (флаг на устройстве). */

import type { MaxWebApp } from "./max";

export const ONBOARDING_KEY = "olymp.onboarding.v1";

function read(): string | null {
  try {
    return localStorage.getItem(ONBOARDING_KEY);
  } catch {
    return null;
  }
}

export function markOnboardingDone(): void {
  try {
    localStorage.setItem(ONBOARDING_KEY, "done");
  } catch {
    /* хранилище недоступно — онбординг покажется ещё раз, это не страшно */
  }
}

/** Показать ли онбординг: только при первом запуске и не тогда, когда приложение открыли
 *  ссылкой на конкретный экран (startapp=… или ссылка «Поделиться» /s/<token>) — человек
 *  пришёл за этим экраном. ?onboarding в адресе показывает его принудительно (для демонстрации). */
export function shouldShowOnboarding(app: MaxWebApp | null, url: URL): boolean {
  if (url.searchParams.has("onboarding")) return true;
  if (read()) return false;
  const startParam = app?.initDataUnsafe.start_param || url.searchParams.get("WebAppStartParam");
  if (startParam || url.pathname.startsWith("/s/")) {
    markOnboardingDone();
    return false;
  }
  return true;
}
