import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AboutModal } from "./AboutModal";

const campaign = { campaign_year: 2027, valid_years: [2024, 2025, 2026, 2027] };

afterEach(cleanup);

describe("«О приложении»", () => {
  it("рассказывает о сценариях и льготах, а не о сборке базы", () => {
    render(<AboutModal open onClose={vi.fn()} campaign={campaign} />);
    expect(screen.getByRole("dialog", { name: "О приложении" })).toBeTruthy();
    expect(screen.getByText("Вузы → олимпиады.")).toBeTruthy();
    expect(screen.getByText("Мои дипломы → все льготы.")).toBeTruthy();
    expect(screen.getByText("БВИ — без вступительных испытаний")).toBeTruthy();
    expect(screen.getByText("100 баллов за ЕГЭ или ДВИ")).toBeTruthy();
    expect(screen.getByText("Подтверждение ЕГЭ.")).toBeTruthy();
    // статистики и таблиц сборки базы больше нет
    expect(document.querySelector("#about-modal table")).toBeNull();
    expect(screen.queryByText(/Строк таблиц|парсер/)).toBeNull();
  });

  it("годы действия дипломов — из приёмной кампании", () => {
    render(<AboutModal open onClose={vi.fn()} campaign={campaign} />);
    expect(screen.getByText(/в 2027 году засчитывают олимпиады 2024–2027/)).toBeTruthy();
  });

  it("в браузере дипломы хранятся на устройстве; закрывается крестиком", () => {
    const onClose = vi.fn();
    render(<AboutModal open onClose={onClose} campaign={campaign} />);
    expect(screen.getByText(/Список хранится на этом устройстве/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
