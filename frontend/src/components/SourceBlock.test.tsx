import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { Source } from "@/lib/api";
import { SourceBlock } from "./SourceBlock";

afterEach(() => {
  cleanup();
});

describe("SourceBlock", () => {
  it("не показывает ничего для пустого списка и адресов из пробелов", () => {
    const { container, rerender } = render(<SourceBlock sources={[]} />);
    expect(container.textContent).toBe("");
    rerender(<SourceBlock sources={[{ url: "   " }]} />);
    expect(container.textContent).toBe("");
  });

  it("показывает страницу приёмной комиссии и пояснение про неё", () => {
    render(
      <SourceBlock
        sources={[{ url: "https://hse.ru/priem", title: "Приём 2027", kind: "page", types: [] }]}
      />,
    );
    const link = screen.getByRole("link");
    expect(link.textContent).toContain("Документы приёмной комиссии");
    expect(link.textContent).toContain("Приём 2027");
    expect(link.getAttribute("href")).toBe("https://hse.ru/priem");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener");
    expect(screen.getByText(/Актуальные файлы всегда лежат на странице приёмной комиссии/)).toBeTruthy();
  });

  it("подписывает файлы по типам и помечает PDF в адресе", () => {
    render(
      <SourceBlock
        sources={[
          { url: "https://hse.ru/rules.PDF?year=2027", title: "Правила приёма", types: ["Правила приёма"] },
          { url: "https://hse.ru/list", title: "Перечни", types: ["БВИ", "СТО"] },
        ]}
      />,
    );
    expect(screen.getByText("Документ вуза: Правила приёма (PDF)")).toBeTruthy();
    expect(screen.getByText("Открыть документ вуза")).toBeTruthy();
    expect(screen.getByText("Правила приёма")).toBeTruthy();
  });

  it("склеивает одинаковые названия и оставляет не больше трёх файлов", () => {
    render(
      <SourceBlock
        sources={[
          { url: "https://hse.ru/priem", kind: "page", title: "Приём" },
          { url: "https://hse.ru/1.pdf", title: "Перечень 1" },
          { url: "https://hse.ru/2.pdf", title: "Перечень 1" },
          { url: "https://hse.ru/3.pdf", title: "Перечень 2" },
          { url: "https://hse.ru/4.pdf", title: "Перечень 3" },
          { url: "https://hse.ru/5.pdf", title: "Перечень 4" },
        ]}
      />,
    );
    expect(screen.getAllByRole("link").length).toBe(4);
    expect(screen.getByText("Перечень 3")).toBeTruthy();
    expect(screen.queryByText("Перечень 4")).toBeNull();
  });

  it("не добавляет фразу про страницу, когда её нет, и принимает источник из API", () => {
    const source: Source = {
      url: "https://urfu.ru/docs",
      title: "Правила приёма",
      types: [],
      kind: "file",
      checked_at: null,
    };
    render(<SourceBlock sources={[source]} />);
    expect(screen.getByRole("link").textContent).toContain("Открыть документ вуза");
    expect(screen.getByText("Правила приёма")).toBeTruthy();
    expect(screen.queryByText(/Актуальные файлы всегда лежат/)).toBeNull();
  });
});
