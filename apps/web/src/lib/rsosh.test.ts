import { describe, expect, it } from "vitest";
import { levelChange, NOT_IN_LIST_HINT, notInList } from "./rsosh";

describe("перечень РСОШ 2026/27", () => {
  it("«нет в перечне» только при явном false: null — перечень не применим", () => {
    expect(notInList({ in_rsosh_2026_27: false })).toBe(true);
    expect(notInList({ in_rsosh_2026_27: true })).toBe(false);
    expect(notInList({ in_rsosh_2026_27: null })).toBe(false);
    expect(notInList({})).toBe(false);
    expect(notInList(null)).toBe(false);
  });

  it("уровень показывается, только если он изменился", () => {
    expect(levelChange({ level: "II", level_2026_27: "I" })).toBe("уровень в 2026/27: I");
    expect(levelChange({ level: "", level_2026_27: "III" })).toBe("уровень в 2026/27: III");
    expect(levelChange({ level: "II", level_2026_27: "II" })).toBeNull();
    expect(levelChange({ level: "II", level_2026_27: "" })).toBeNull();
    expect(levelChange({ level: "II" })).toBeNull();
    expect(levelChange(null)).toBeNull();
  });

  it("подсказка говорит про диплом этого года", () => {
    expect(NOT_IN_LIST_HINT).toBe("Диплом 2026/27 года по ней не даст льгот при поступлении");
  });
});
