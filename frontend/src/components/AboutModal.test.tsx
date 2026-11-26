import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AboutModal } from "./AboutModal";

const campaign = { campaign_year: 2027, valid_years: [2024, 2025, 2026, 2027] };

afterEach(cleanup);

describe("«О приложении»", () => {
  it("рассказывает о сценариях и льготах, а не о сборке базы", () => {
    render(<AboutModal open onClose={vi.fn()} campaign={campaign} />);
    expect(screen.getByRole("dialog", { name: "О приложении" })).toBeTruthy();
    expect(screen.getByText("БВИ")).toBeTruthy();
    expect(screen.getByText("100 баллов")).toBeTruthy();
    expect(screen.getByText("Как пользоваться")).toBeTruthy();
    expect(screen.getByText("Олимпиады")).toBeTruthy();
    expect(screen.getByText("От чего зависит льгота")).toBeTruthy();
    // статистики и таблиц сборки базы больше нет
    expect(document.querySelector("#about-modal table")).toBeNull();
    expect(screen.queryByText(/Строк таблиц|парсер/)).toBeNull();
  });

  it("годы действия дипломов — из приёмной кампании", () => {
    render(<AboutModal open onClose={vi.fn()} campaign={campaign} />);
    expect(screen.getByText("Засчитываются олимпиады 2024–2027 годов")).toBeTruthy();
  });

  it("закрывается крестиком и по фону", () => {
    const onClose = vi.fn();
    render(<AboutModal open onClose={onClose} campaign={campaign} />);
    fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));
    fireEvent.click(document.querySelector("#about-modal > div")!);
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
