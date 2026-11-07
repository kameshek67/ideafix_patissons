import { describe, expect, it } from "vitest";
import { conditionsLine } from "./conditions";

describe("conditionsLine", () => {
  it("собирает кому, класс и ЕГЭ с предметом и порогом", () => {
    expect(
      conditionsLine({ role: "победители и призёры", grade: "11 класс", confirm: "математика", min_ege: "75 и более" }),
    ).toBe("Победители и призёры · 11 класс · ЕГЭ математика ≥75");
  });

  it("не дублирует порог, если он уже в подтверждении", () => {
    expect(conditionsLine({ role: "только победители", confirm: "информатика ≥75" })).toBe(
      "Только победители · ЕГЭ информатика ≥75",
    );
  });

  it("пропускает пустые значения и прочерки", () => {
    expect(conditionsLine({ role: "—", grade: "", confirm: "—", min_ege: "—" })).toBe("");
    expect(conditionsLine({ grade: "10, 11 класс" })).toBe("10, 11 класс");
  });

  it("порог без предмета остаётся с пометкой ЕГЭ", () => {
    expect(conditionsLine({ min_ege: "80 и более" })).toBe("ЕГЭ ≥80");
  });
});
