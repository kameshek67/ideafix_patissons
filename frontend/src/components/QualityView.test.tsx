import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QualityView } from "./QualityView";

const score = (over: object) => ({ documents: 6, records: 543, precision: 0.9, recall: 0.74, who: 1, ...over });
const period = { received: 0, fixed: 0, correct: 0, median_hours: null };

const full = {
  extraction: {
    development: {
      old_table: score({ documents: 10, records: 1000, precision: 0.15, recall: 0.13, who: 0.92 }),
      extraction: score({ documents: 10, records: 1000, precision: 0.9979, recall: 0.953 }),
    },
    holdout: {
      old_table: score({ precision: 0.004, recall: 0.018 }),
      extraction: score({}),
    },
  },
  coverage: {
    universities: 39,
    with_table: 36,
    without_table: [
      { id: 1, name: "Вуз без таблицы А" },
      { id: 2, name: "Вуз без таблицы Б" },
      { id: 3, name: "Вуз без таблицы В" },
    ],
    layers: { detailed: 5000, derived: 2000 },
  },
  freshness: {
    built_at: "2026-11-26T10:00:00",
    rsosh_list: "2026-11-26",
    documents_checked_from: "2026-09-24",
    documents_checked_to: "2026-10-30",
  },
  reports: {
    total: { received: 10, fixed: 4, correct: 3, median_hours: 5.2 },
    days_30: period,
  },
  assistant: null as unknown,
};

let body: unknown = full;
let status = 200;

beforeEach(() => {
  body = structuredClone(full);
  status = 200;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }),
    ),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <QualityView />
    </QueryClientProvider>,
  );
}

async function findById(id: string): Promise<HTMLElement> {
  return waitFor(() => {
    const el = document.getElementById(id);
    if (!el) throw new Error(`нет #${id}`);
    return el;
  });
}

describe("QualityView", () => {
  it("показывает старую таблицу и извлечение на отложенных страницах, с оговоркой про выборку", async () => {
    renderView();
    const section = await findById("quality-extraction");
    expect(within(section).getByLabelText("Старая таблица").getAttribute("aria-valuenow")).toBe("2");
    expect(within(section).getByLabelText("Извлечение из документов").getAttribute("aria-valuenow")).toBe("74");
    const note = document.getElementById("quality-extraction-note")!;
    expect(note.textContent).toContain("Проверено на 6 документах, 543 записях");
    expect(note.textContent).toContain("Это выборка");
    expect(note.textContent).toContain("95%");
  });

  it("вузы без таблицы свёрнуты, слои названы по-русски", async () => {
    renderView();
    await screen.findByText("Вузы с таблицей льгот");
    expect(screen.getByText("36 из 39")).toBeTruthy();
    const details = document.getElementById("quality-without-table") as HTMLDetailsElement;
    expect(details.open).toBe(false);
    expect(details.textContent).toContain("Без таблицы: 3 вуза");
    expect(screen.getByText("таблицы вузов (олимпиада × профиль)")).toBeTruthy();
  });

  it("жалобы: числа и время; нет жалоб — так и пишем", async () => {
    renderView();
    const reports = await findById("quality-reports");
    expect(reports.textContent).toContain("Решаем обычно за 5 ч.");
    expect(reports.textContent).toContain("Жалоб не было.");
  });

  it("блок помощника есть только при наличии оценки", async () => {
    renderView();
    await screen.findByText("Когда обновляли");
    expect(document.getElementById("quality-assistant")).toBeNull();
    cleanup();
    (body as { assistant: unknown }).assistant = {
      model: "vendor/model-x",
      date: "2026-11-27",
      cases: 120,
      passed_share: 0.93,
      error_share: 0.02,
      fabrication: 0,
      answer_p50: 6.5,
      cost_per_answer: null,
    };
    renderView();
    const block = await findById("quality-assistant");
    expect(block.textContent).toContain("vendor/model-x");
    expect(block.textContent).toContain("93%");
    expect(block.textContent).toContain("Проверено на 120 вопросах, 27 ноября 2026");
  });

  it("без файлов оценки страница работает и честно говорит об этом", async () => {
    const empty = { old_table: null, extraction: null };
    (body as typeof full).extraction = { development: empty, holdout: empty } as never;
    (body as { freshness: unknown }).freshness = { built_at: null, rsosh_list: null, documents_checked_from: null, documents_checked_to: null };
    renderView();
    await screen.findByText(/Оценки точности пока нет/);
    expect(screen.getAllByText("нет данных").length).toBe(3);
  });

  it("ошибка загрузки — понятный текст и повтор", async () => {
    status = 500;
    renderView();
    await screen.findByText(/Сервер сейчас не отвечает/);
    expect(screen.getByRole("button", { name: "Повторить" })).toBeTruthy();
  });
});
