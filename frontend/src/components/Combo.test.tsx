import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Combo, type ComboItem } from "./Combo";

interface University {
  id: number;
}

const items: ComboItem<University>[] = [
  { key: 1, value: { id: 1 }, label: "УрФУ", content: "Уральский федеральный университет" },
  { key: 2, value: { id: 2 }, label: "ВШЭ", content: "НИУ ВШЭ" },
];

function renderCombo({
  value = null,
  onSearch = () => items,
  onPick = vi.fn(),
  disabled = false,
  disabledTitle,
}: {
  value?: string | null;
  onSearch?: (q: string) => ComboItem<University>[] | Promise<ComboItem<University>[]>;
  onPick?: (item: ComboItem<University>) => void;
  disabled?: boolean;
  disabledTitle?: string;
} = {}) {
  render(
    <Combo<University>
      id="university"
      ariaLabel="Вуз"
      placeholder="Выберите вуз"
      searchPlaceholder="Поиск вуза"
      value={value}
      disabled={disabled}
      disabledTitle={disabledTitle}
      onSearch={onSearch}
      onPick={onPick}
    />,
  );
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Combo", () => {
  it("показывает placeholder, загружает список при открытии и закрывается кликом вне", async () => {
    const onSearch = vi.fn(() => items);
    renderCombo({ onSearch });
    const button = screen.getByRole("button", { name: "Вуз" });
    expect(button.textContent).toContain("Выберите вуз");
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("Уральский федеральный университет")).toBeNull();

    fireEvent.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("true");
    expect(onSearch).toHaveBeenCalledWith("");
    expect(await screen.findByText("Уральский федеральный университет")).toBeTruthy();
    expect(screen.getByText("НИУ ВШЭ")).toBeTruthy();

    fireEvent.click(document.body);
    expect(button.getAttribute("aria-expanded")).toBe("false");
  });

  it("показывает выбранное значение, а заблокированная кнопка не открывает панель", () => {
    renderCombo({ value: "НИУ ВШЭ" });
    const selected = screen.getByRole("button", { name: "Вуз" });
    expect(selected.textContent).toContain("НИУ ВШЭ");
    expect(selected.textContent).not.toContain("Выберите вуз");
    cleanup();

    const onSearch = vi.fn(() => items);
    renderCombo({ onSearch, disabled: true, disabledTitle: "Нет прав" });
    const button = screen.getByRole("button", { name: "Вуз" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.title).toBe("Нет прав");
    fireEvent.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(onSearch).not.toHaveBeenCalled();
  });

  it("ищет с задержкой, обрезая пробелы, и сообщает о пустом результате", async () => {
    vi.useFakeTimers();
    const onSearch = vi.fn((q: string) => (q ? [] : items));
    renderCombo({ onSearch });
    fireEvent.click(screen.getByRole("button", { name: "Вуз" }));
    expect(onSearch).toHaveBeenCalledWith("");

    fireEvent.change(screen.getByPlaceholderText("Поиск вуза"), { target: { value: "  проба  " } });
    act(() => vi.advanceTimersByTime(179));
    expect(onSearch).not.toHaveBeenCalledWith("проба");
    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(onSearch).toHaveBeenLastCalledWith("проба");
    expect(screen.getByText("Ничего не найдено")).toBeTruthy();
  });

  it("выбор подсказки закрывает панель и передаёт весь элемент", async () => {
    const onPick = vi.fn();
    renderCombo({ onPick });
    const button = screen.getByRole("button", { name: "Вуз" });
    fireEvent.click(button);
    fireEvent.click(await screen.findByText("Уральский федеральный университет"));
    expect(onPick).toHaveBeenCalledWith(items[0]);
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByPlaceholderText("Поиск вуза").parentElement?.className).toContain("hidden");
  });

  it("при ошибке загрузки предлагает повторить тот же запрос", async () => {
    let attempts = 0;
    const onSearch = vi.fn(async (_q: string) => {
      attempts += 1;
      if (attempts === 1) throw new Error("network");
      return items;
    });
    renderCombo({ onSearch });
    fireEvent.click(screen.getByRole("button", { name: "Вуз" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Не получилось загрузить");
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByText("НИУ ВШЭ")).toBeTruthy();
    expect(onSearch.mock.calls).toEqual([[""], [""]]);
  });

  it("отложенный поиск не применяется после закрытия и повторного открытия", async () => {
    vi.useFakeTimers();
    const onSearch = vi.fn((q: string) => (q ? [] : items));
    renderCombo({ onSearch });
    const button = screen.getByRole("button", { name: "Вуз" });
    fireEvent.click(button);
    fireEvent.change(screen.getByPlaceholderText("Поиск вуза"), { target: { value: "проба" } });
    fireEvent.click(button);
    fireEvent.click(button);

    await act(async () => {
      vi.advanceTimersByTime(200);
      await Promise.resolve();
    });
    expect(onSearch).not.toHaveBeenCalledWith("проба");
  });
});
