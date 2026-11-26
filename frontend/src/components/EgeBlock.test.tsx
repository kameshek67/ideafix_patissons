import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EGE_SUBJECTS, type EgeScores } from "@/lib/ege";
import { EgeBlock } from "./EgeBlock";

function Harness({
  initial = { scores: {}, mock: false },
  onChange = vi.fn(),
}: {
  initial?: EgeScores;
  onChange?: (next: EgeScores) => void;
} = {}) {
  const [ege, setEge] = useState<EgeScores>(initial);
  return (
    <EgeBlock
      ege={ege}
      onChange={(next) => {
        setEge(next);
        onChange(next);
      }}
    />
  );
}

afterEach(() => {
  cleanup();
});

describe("EgeBlock", () => {
  it("без баллов свёрнут и открывается по кнопке", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: /Мои баллы ЕГЭ — проверить/ }));
    expect(screen.getByRole("heading", { name: "Мои баллы ЕГЭ" })).toBeTruthy();
    expect(screen.getAllByLabelText(/^Балл ЕГЭ:/).length).toBe(EGE_SUBJECTS.length);
    expect(screen.getByText(/Вузы засчитывают диплом/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Очистить баллы" })).toBeNull();
  });

  it("баллы из профиля сразу видны, блок раскрыт", () => {
    render(<Harness initial={{ scores: { inf: 82 }, mock: true }} />);
    expect(screen.queryByRole("button", { name: /Мои баллы ЕГЭ — проверить/ })).toBeNull();
    expect((screen.getByLabelText("Балл ЕГЭ: Информатика") as HTMLInputElement).value).toBe("82");
    expect((screen.getByLabelText("Это пробные баллы") as HTMLInputElement).checked).toBe(true);
    expect(screen.getByRole("button", { name: "Очистить баллы" })).toBeTruthy();
  });

  it("балл сохраняется при уходе с поля, а пустое поле удаляет его", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /Мои баллы ЕГЭ — проверить/ }));
    const math = screen.getByLabelText("Балл ЕГЭ: Математика (профиль)") as HTMLInputElement;

    fireEvent.change(math, { target: { value: "72" } });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.blur(math);
    expect(onChange).toHaveBeenCalledWith({ scores: { math: 72 }, mock: false });
    expect(math.value).toBe("72");

    fireEvent.change(math, { target: { value: "" } });
    fireEvent.blur(math);
    expect(onChange).toHaveBeenLastCalledWith({ scores: {}, mock: false });
    expect(math.value).toBe("");
  });

  it("Enter сохраняет балл, неверные значения возвращают прежнее", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /Мои баллы ЕГЭ — проверить/ }));
    const inf = screen.getByLabelText("Балл ЕГЭ: Информатика") as HTMLInputElement;

    inf.focus();
    fireEvent.change(inf, { target: { value: "90" } });
    fireEvent.keyDown(inf, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith({ scores: { inf: 90 }, mock: false });

    fireEvent.change(inf, { target: { value: "140" } });
    fireEvent.blur(inf);
    expect(inf.value).toBe("90");
    fireEvent.change(inf, { target: { value: "12.5" } });
    fireEvent.blur(inf);
    expect(inf.value).toBe("90");
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("переключает пробные баллы и очищает весь блок", () => {
    const onChange = vi.fn();
    render(<Harness initial={{ scores: { rus: 95 }, mock: false }} onChange={onChange} />);
    const mock = screen.getByLabelText("Это пробные баллы") as HTMLInputElement;
    fireEvent.click(mock);
    expect(onChange).toHaveBeenCalledWith({ scores: { rus: 95 }, mock: true });
    expect(mock.checked).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Очистить баллы" }));
    expect(onChange).toHaveBeenLastCalledWith({ scores: {}, mock: false });
    expect((screen.getByLabelText("Балл ЕГЭ: Русский язык") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Это пробные баллы") as HTMLInputElement).checked).toBe(false);
    expect(screen.queryByRole("button", { name: "Очистить баллы" })).toBeNull();
  });
});
