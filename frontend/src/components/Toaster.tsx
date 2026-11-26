"use client";

import { useEffect, useState } from "react";
import { onToast, type ToastMessage } from "@/lib/toast";

/** Место для тостов: тёмная пилюля внизу экрана на 3 секунды. */
export function Toaster() {
  const [message, setMessage] = useState<ToastMessage | null>(null);
  useEffect(() => onToast(setMessage), []);
  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(() => setMessage(null), 3000);
    return () => clearTimeout(timer);
  }, [message]);
  return (
    <div role="status" aria-live="polite">
      {message ? (
        <div key={message.id} className="toast">
          {message.text}
        </div>
      ) : null}
    </div>
  );
}
