import { describe, expect, it } from "vitest";
import { intakeLine } from "./intake";

const base = { year: 2024, source: "Мониторинг эффективности вузов" };

describe("intakeLine", () => {
  it("число олимпиадников и средний балл", () => {
    expect(intakeLine({ ...base, olympiad_students: 624, avg_score_budget: 98.67 })).toBe(
      "В 2024 по олимпиадам приняли 624 человека · средний балл бюджета 98,7",
    );
  });

  it("склоняет «человек»", () => {
    const line = (n: number) => intakeLine({ ...base, olympiad_students: n, avg_score_budget: 80 });
    expect(line(21)).toContain("приняли 21 человек ·");
    expect(line(12)).toContain("приняли 12 человек ·");
    expect(line(33)).toContain("приняли 33 человека ·");
  });

  it("без среднего балла остаётся только число", () => {
    expect(intakeLine({ ...base, olympiad_students: 300 })).toBe("В 2024 по олимпиадам приняли 300 человек");
  });

  it("малое число и пропуск не показываем: возможно, не заполнено", () => {
    expect(intakeLine({ ...base, olympiad_students: 3, avg_score_budget: 65.17 })).toBe(
      "Средний балл бюджета в 2024: 65,2",
    );
    expect(intakeLine({ ...base, olympiad_students: null, avg_score_budget: 69.12 })).toBe(
      "Средний балл бюджета в 2024: 69,1",
    );
    expect(intakeLine({ ...base, olympiad_students: null })).toBeNull();
  });

  it("нет данных панели — нет строки", () => {
    expect(intakeLine(null)).toBeNull();
    expect(intakeLine(undefined)).toBeNull();
  });
});
