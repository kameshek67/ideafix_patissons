import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AssistantText } from "./AssistantText";

afterEach(() => {
  cleanup();
});

describe("AssistantText", () => {
  it("показывает абзац и перенос строки внутри него", () => {
    const { container } = render(<AssistantText text={"Первая строка\nВторая строка"} />);
    expect(container.querySelectorAll("p").length).toBe(1);
    expect(container.querySelectorAll("br").length).toBe(1);
    expect(container.textContent).toContain("Первая строка");
    expect(container.textContent).toContain("Вторая строка");
  });

  it("пустой текст не создаёт блоков", () => {
    const { container } = render(<AssistantText text="" />);
    expect(container.textContent).toBe("");
    expect(container.querySelectorAll("p, ul, ol").length).toBe(0);
  });

  it("выделяет жирный в тексте и заголовке", () => {
    const { container } = render(<AssistantText text={"Это **важно**\n\n# Заголовок"} />);
    expect(screen.getByText("важно").tagName).toBe("STRONG");
    expect(screen.getByText("Заголовок").tagName).toBe("STRONG");
    expect(container.querySelectorAll("p").length).toBe(2);
    expect(screen.queryByText(/\*\*/)).toBeNull();
  });

  it("собирает маркированный список, включая жирный пункт", () => {
    const { container } = render(<AssistantText text={"- **НТО**\n* «Высшая проба»\n• МОШ"} />);
    expect(container.querySelectorAll("ul").length).toBe(1);
    expect(container.querySelectorAll("ul li").length).toBe(3);
    expect(screen.getByText("НТО").tagName).toBe("STRONG");
    expect(screen.getByText("«Высшая проба»")).toBeTruthy();
  });

  it("собирает нумерованный список и отдельный абзац после него", () => {
    const { container } = render(<AssistantText text={"1. Первый\n2) Второй\n\nФинальный текст"} />);
    expect(container.querySelectorAll("ol li").length).toBe(2);
    expect(screen.getByText("Финальный текст")).toBeTruthy();
    expect(screen.getAllByRole("listitem").length).toBe(2);
  });

  it("не делает ссылки и HTML из текста модели", () => {
    const { container } = render(<AssistantText text={"[жми](https://evil.example) <script>alert(1)</script>"} />);
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain("жми");
    expect(container.textContent).toContain("<script>alert(1)</script>");
  });
});
