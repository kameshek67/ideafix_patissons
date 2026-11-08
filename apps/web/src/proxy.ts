import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Запросы /api/v1/* уходят в API через rewrite из next.config.ts. Сам rewrite не передаёт
// X-Forwarded-For, и лимит запросов API считал бы всех посетителей сайта одним клиентом —
// сервером Next. Перед вызовом proxy Next кладёт в x-forwarded-for адрес соединения
// (если клиент не прислал заголовок сам) — передаём его в API явно. Только последний адрес:
// его поставил ближайший прокси (на стенде — Caddy), всё левее мог дописать клиент (T-065).
export function proxy(request: NextRequest) {
  const forwardedFor = request.headers.get("x-forwarded-for")?.split(",").pop()?.trim();
  if (!forwardedFor) return NextResponse.next();
  const headers = new Headers(request.headers);
  headers.set("x-forwarded-for", forwardedFor);
  return NextResponse.next({ request: { headers } });
}

export const config = { matcher: "/api/v1/:path*" };
