/* Онбординг: показывается один раз — при первом запуске (флаг на устройстве). Кто прошёл его
   до появления новых функций (флаг «done»), один раз видит только экран «Что нового». */

import type { MaxWebApp } from "./max";

export const ONBOARDING_KEY = "olymp.onboarding.v1";
/** Значение флага после текущей версии онбординга; «done» — версия до ИИ-помощника и «Баллов». */
export const ONBOARDING_DONE = "done-2";

export type OnboardingMode = "full" | "news";

function read(): string | null {
  try {
    return localStorage.getItem(ONBOARDING_KEY);
  } catch {
    return null;
  }
}

export function markOnboardingDone(): void {
  try {
    localStorage.setItem(ONBOARDING_KEY, ONBOARDING_DONE);
  } catch {
    /* хранилище недоступно — онбординг покажется ещё раз, это не страшно */
  }
}

/** Показать ли онбординг: только при первом запуске и не тогда, когда приложение открыли
 *  ссылкой на конкретный экран (startapp=… или ссылка «Поделиться» /s/<token>) — человек
 *  пришёл за этим экраном. ?onboarding в адресе показывает его принудительно (для демонстрации). */
export function onboardingMode(app: MaxWebApp | null, url: URL): OnboardingMode | null {
  if (url.searchParams.has("onboarding")) return "full";
  const seen = read();
  const startParam = app?.initDataUnsafe.start_param || url.searchParams.get("WebAppStartParam");
  if (seen === ONBOARDING_DONE) return null;
  if (startParam || url.pathname.startsWith("/s/")) {
    markOnboardingDone();
    return null;
  }
  return seen ? "news" : "full";
}

export function shouldShowOnboarding(app: MaxWebApp | null, url: URL): boolean {
  return onboardingMode(app, url) !== null;
}
