/* Поток ответа помощника. Обычный прокси /api/v1/* (rewrites) может накапливать
   text/event-stream целиком, поэтому чат идёт через этот обработчик: он отдаёт тело ответа API
   как поток (F-02). Адрес API читается при запуске, а не при сборке. */

export const dynamic = "force-dynamic";

const apiUrl = () => process.env.OLYMP_API_URL ?? "http://localhost:8000";

export async function POST(request: Request): Promise<Response> {
  const headers = new Headers({ "content-type": "application/json" });
  const initData = request.headers.get("x-max-init-data");
  if (initData) headers.set("x-max-init-data", initData);
  // последний адрес цепочки поставил ближайший прокси, остальные мог подделать клиент
  const forwarded = request.headers.get("x-forwarded-for")?.split(",").pop()?.trim();
  if (forwarded) headers.set("x-forwarded-for", forwarded);

  let upstream: Response;
  try {
    upstream = await fetch(`${apiUrl()}/v1/assistant/chat`, {
      method: "POST",
      headers,
      body: await request.text(),
      signal: request.signal,
      cache: "no-store",
    });
  } catch {
    return Response.json(
      { title: "Помощник недоступен", status: 502 },
      { status: 502, headers: { "content-type": "application/problem+json" } },
    );
  }

  const out = new Headers({
    "content-type": upstream.headers.get("content-type") ?? "application/json",
    "cache-control": "no-cache, no-transform",
    "x-accel-buffering": "no",
  });
  const retry = upstream.headers.get("retry-after");
  if (retry) out.set("retry-after", retry);
  return new Response(upstream.body, { status: upstream.status, headers: out });
}
