"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { createShare, type ShareRequest } from "@/lib/api";
import { haptic } from "@/lib/max";
import { sendShare } from "@/lib/share";
import { showToast } from "@/lib/toast";
import { IconShare } from "./icons";
import { useMax } from "./MaxProvider";

interface Props {
  /** что сохранить в ссылке: экран по id текущей сборки */
  request: ShareRequest;
  title: string;
  text: string;
  label?: string;
  /** кнопка во всю ширину (итоги дипломов), иначе — компактная пилюля в шапке карточки */
  wide?: boolean;
  /** готовить ссылку заранее — только пока экран на виду (скрытая вкладка не создаёт ссылок) */
  prefetch?: boolean;
  id?: string;
}

/** «Поделиться». Ссылку готовим заранее, пока экран открыт: MAX и браузеры показывают
 *  меню «поделиться» только сразу в ответ на нажатие, а запрос к API — это задержка. */
export function ShareButton({
  request,
  title,
  text,
  label = "Поделиться",
  wide = false,
  prefetch = true,
  id,
}: Props) {
  const app = useMax();
  // POST идемпотентен: тот же экран — та же ссылка, повторный показ карточки берёт её из кэша
  const link = useQuery({
    queryKey: ["share", request],
    queryFn: () => createShare(request),
    enabled: prefetch,
    staleTime: Infinity,
    retry: false,
  });
  const [busy, setBusy] = useState(false);

  async function share() {
    if (busy) return;
    let created = link.data;
    if (!created) {
      // ссылка ещё не готова (или не создалась заранее) — создаём сейчас
      setBusy(true);
      try {
        created = (await link.refetch({ throwOnError: true })).data;
      } catch {
        created = undefined;
      } finally {
        setBusy(false);
      }
      if (!created) return showToast("Не получилось создать ссылку — попробуй ещё раз");
    }
    // ответа меню «поделиться» кнопка не ждёт: меню модальное, а клиент MAX может и не ответить
    const outcome = await sendShare(app, {
      title,
      text,
      url: new URL(created.web_path, window.location.origin).toString(),
      maxUrl: created.max_url,
    });
    if (outcome === "shared") haptic(app, "success");
    else if (outcome === "copied") showToast("Ссылка скопирована");
    else if (outcome === "failed") showToast("Не получилось поделиться — попробуй ещё раз");
  }

  return (
    <button
      id={id}
      type="button"
      className={wide ? "btn-secondary w-full" : "share-btn"}
      onClick={() => void share()}
      disabled={busy}
      aria-busy={busy}
    >
      <IconShare />
      {busy ? "Готовим ссылку…" : label}
    </button>
  );
}
