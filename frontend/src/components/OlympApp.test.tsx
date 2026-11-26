import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OlympApp } from "./OlympApp";

const university = {
  id: 19,
  name: "НИУ ВШЭ (Москва)",
  short_name: "НИУ ВШЭ (Москва)",
  region: "Москва",
  city: "Москва",
  note: "",
  region_group: "Москва",
  programs: 67,
  bvi: 3001,
  sto: 2000,
  benefits: 5001,
};

const responses: Record<string, unknown> = {
  "/api/v1/universities": { count: 1, items: [university], regions: ["Москва"] },
  "/api/v1/olympiads": {
    count: 1,
    items: [
      {
        id: 5,
        canonical_name: "Всероссийская олимпиада школьников «Высшая проба»",
        short_name: "«Высшая проба»",
        kind: "rsosh",
        mentions: 3314,
        bvi_count: 1907,
        sto_count: 1376,
        uni_count: 18,
        rank: null,
        is_featured: 1,
        profiles: 34,
      },
    ],
  },
};

beforeEach(() => {
  // онбординг первого запуска проверяется в Onboarding.test.tsx
  localStorage.setItem("olymp.onboarding.v1", "done-2");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request | string) => {
      const url = new URL(typeof input === "string" ? input : input.url, "http://localhost");
      // как в браузере: список вузов (самый тяжёлый ответ) приходит последним
      if (url.pathname.endsWith("/universities")) await new Promise((r) => setTimeout(r, 30));
      const body = responses[url.pathname];
      return new Response(JSON.stringify(body ?? {}), {
        status: body ? 200 : 404,
        headers: { "content-type": "application/json" },
      });
    }),
  );
});

afterEach(() => {
  delete responses["/api/v1/assistant/config"];
  cleanup();
  vi.unstubAllGlobals();
});

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <OlympApp />
    </QueryClientProvider>,
  );
}

describe("OlympApp", () => {
  it("стартовый экран как в прототипе", () => {
    renderApp();
    expect(screen.getByText("Выбери вуз и направление — получи таблицу льгот по олимпиадам")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Вузы" }).className).toBe("tab-btn tab-active");
    expect(screen.getByLabelText("Направление").hasAttribute("disabled")).toBe(true);
  });

  it("список вузов виден с первого открытия, как только данные пришли", async () => {
    renderApp();
    // дождаться загрузки справочников (популярные олимпиады рисуются в разметке)
    await waitFor(() => expect(screen.getByText("Популярные:")).toBeTruthy());
    await new Promise((r) => setTimeout(r, 100)); // список вузов уже пришёл
    fireEvent.click(screen.getByLabelText("Вуз"));
    await waitFor(() => expect(screen.getAllByText("НИУ ВШЭ (Москва)").length).toBeGreaterThan(0));
    expect(screen.queryByText("Ничего не найдено")).toBeNull();
  });

  it("выбор вуза открывает выбор направления", async () => {
    renderApp();
    await waitFor(() => expect(screen.getByText("Популярные:")).toBeTruthy());
    await new Promise((r) => setTimeout(r, 100)); // список вузов уже пришёл
    fireEvent.click(screen.getByLabelText("Вуз"));
    await waitFor(() =>
      expect(document.querySelector("#combo-university .combo-list")?.textContent).toContain("НИУ ВШЭ"),
    );
    fireEvent.click(document.querySelector("#combo-university .combo-item")!);
    expect(screen.getByText("Теперь выбери направление: в НИУ ВШЭ (Москва) их 67 в базе")).toBeTruthy();
    expect(screen.getByLabelText("Направление").hasAttribute("disabled")).toBe(false);
  });

  it("помощник выключен: кнопка на месте, по нажатию — пояснение, чат не открывается", async () => {
    responses["/api/v1/assistant/config"] = { enabled: false, suggestions: [] };
    renderApp();
    const fab = await screen.findByRole("button", { name: /Спросить ИИ/ });
    await waitFor(() => expect(screen.getByText("Популярные:")).toBeTruthy());
    fireEvent.click(fab);
    expect(await screen.findByText("Помощник сейчас выключен на этом стенде.")).toBeTruthy();
    expect(screen.getByText(/вкладка «Дипломы» работают без него/)).toBeTruthy();
    expect(document.getElementById("assistant-sheet")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Понятно" }));
    expect(screen.queryByText("Помощник сейчас выключен на этом стенде.")).toBeNull();
    expect(screen.getByRole("button", { name: /Спросить ИИ/ })).toBeTruthy();
  });

  /** чат отвечает фиксированным потоком: текст и кнопки под ответом */
  function answerWith(actions: unknown[]) {
    const plain = vi.mocked(fetch).getMockImplementation()!;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: Request | string, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.url;
        if (!url.includes("/assistant/chat")) return plain(input, init);
        const body = [
          'event: delta\ndata: {"text": "Попробуй «Высшую пробу»"}\n\n',
          `event: actions\ndata: ${JSON.stringify({ actions })}\n\n`,
          'event: done\ndata: {"message_id": "m"}\n\n',
        ].join("");
        return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
      }),
    );
  }

  async function askAssistant() {
    responses["/api/v1/assistant/config"] = { enabled: true, suggestions: [] };
    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: /Спросить ИИ/ }));
    await waitFor(() => expect(screen.getByLabelText("Сообщение помощнику")).toBeTruthy());
    fireEvent.change(screen.getByLabelText("Сообщение помощнику"), { target: { value: "Куда мне?" } });
    fireEvent.click(screen.getByLabelText("Отправить"));
  }

  it("кнопка «Добавить диплом» из ответа открывает форму с олимпиадой и профилем", async () => {
    responses["/api/v1/achievements/olympiads/5"] = {
      olympiad: { id: 5, key: "высшаяпроба", short_name: "«Высшая проба»", canonical_name: "Высшая проба", in_rsosh_2026_27: null },
      profiles: [
        { id: 8, key: "математика", name: "Математика", level: "1", level_2026_27: "1", mentions: 1 },
        { id: 9, key: "физика", name: "Физика", level: "1", level_2026_27: "1", mentions: 1 },
      ],
    };
    answerWith([
      { kind: "add_diploma", label: "Добавить диплом: «Высшая проба»", olympiad_id: 5, profile_id: 9, name: "«Высшая проба»" },
    ]);
    await askAssistant();
    fireEvent.click(await screen.findByText("Добавить диплом: «Высшая проба»"));
    await waitFor(() => expect(document.getElementById("diploma-sheet")).not.toBeNull());
    expect((await screen.findAllByText("«Высшая проба»")).length).toBeGreaterThan(0);
    expect(document.getElementById("assistant-sheet")!.hasAttribute("hidden")).toBe(true);
    // профиль уже выбран: форма просит только степень диплома
    await waitFor(() => expect(screen.getByRole("button", { name: "Выбери степень диплома" })).toBeTruthy());
    delete responses["/api/v1/achievements/olympiads/5"];
  });

  it("кнопка «Предложить вуз или документ» открывает окно предложения с вузом из действия", async () => {
    answerWith([{ kind: "suggest", label: "Предложить вуз или документ", name: "МГУ" }]);
    await askAssistant();
    // такая же кнопка есть и в «О приложении»: берём ту, что под ответом
    fireEvent.click(await within(document.getElementById("assistant-sheet")!).findByText("Предложить вуз или документ"));
    expect(await screen.findByRole("dialog", { name: "Предложить вуз или документ" })).toBeTruthy();
    expect(document.querySelector("#suggest-university")?.textContent).toContain("МГУ");
  });

  it("помощник включён: кнопка открывает чат", async () => {
    responses["/api/v1/assistant/config"] = { enabled: true, suggestions: ["Какие олимпиады дают БВИ?"] };
    renderApp();
    const fab = await screen.findByRole("button", { name: /Спросить ИИ/ });
    await waitFor(() => expect(document.getElementById("assistant-sheet")).not.toBeNull());
    fireEvent.click(fab);
    expect(document.getElementById("assistant-sheet")!.hasAttribute("hidden")).toBe(false);
    expect(screen.queryByText("Помощник сейчас выключен на этом стенде.")).toBeNull();
  });
});
