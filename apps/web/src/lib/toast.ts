/* Тост — короткое сообщение внизу экрана («Ссылка скопирована»); одно за раз. */

export interface ToastMessage {
  id: number;
  text: string;
}

type Listener = (message: ToastMessage) => void;

const listeners = new Set<Listener>();
let seq = 0;

export function showToast(text: string): void {
  const message = { id: ++seq, text };
  listeners.forEach((listener) => listener(message));
}

/** Подписка на тосты; возвращает отписку. */
export function onToast(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
