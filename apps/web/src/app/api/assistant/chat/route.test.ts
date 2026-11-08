import { afterEach, describe, expect, it, vi } from "vitest";
import { POST } from "./route";

const call = () => vi.mocked(fetch).mock.calls[0] as unknown as [string, RequestInit];

afterEach(() => vi.unstubAllGlobals());

function request(headers: Record<string, string> = {}) {
  return new Request("http://site/api/assistant/chat", {
    method: "POST",
    headers,
    body: JSON.stringify({ messages: [] }),
  });
}

describe("POST /api/assistant/chat", () => {
  it("отдаёт поток API и не кэширует его", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("event: done\n\n", { headers: { "content-type": "text/event-stream" } })),
    );
    const response = await POST(request({ "x-max-init-data": "signed" }));
    expect(response.headers.get("content-type")).toBe("text/event-stream");
    expect(response.headers.get("cache-control")).toBe("no-cache, no-transform");
    expect(await response.text()).toBe("event: done\n\n");
    const [url, init] = call();
    expect(url).toMatch(/\/v1\/assistant\/chat$/);
    expect(new Headers(init.headers).get("x-max-init-data")).toBe("signed");
  });

  it("передаёт только последний адрес цепочки", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}")));
    await POST(request({ "x-forwarded-for": "6.6.6.6, 10.0.0.1" }));
    expect(new Headers(call()[1].headers).get("x-forwarded-for")).toBe("10.0.0.1");
  });

  it("передаёт статус и Retry-After при лимите", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 429, headers: { "retry-after": "30" } })));
    const response = await POST(request());
    expect(response.status).toBe(429);
    expect(response.headers.get("retry-after")).toBe("30");
  });

  it("отвечает 502, если API недоступен", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("fetch failed"))));
    expect((await POST(request())).status).toBe(502);
  });
});
