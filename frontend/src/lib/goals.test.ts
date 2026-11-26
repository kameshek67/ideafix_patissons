import { describe, expect, it } from "vitest";
import { coverageLabels, egeLabel, goalTitle, whoLabel } from "./goals";

describe("подписи цели", () => {
  it("считает направления из выбранных", () => {
    expect(
      coverageLabels({ bvi_programs: [1, 2], hundred_programs: [3] }, 3).map(
        (l) => l.text,
      ),
    ).toEqual(["БВИ в 2 из 3", "100 баллов в 1 из 3"]);
    expect(
      coverageLabels({ bvi_programs: [1], hundred_programs: [] }, 1).map(
        (l) => l.text,
      ),
    ).toEqual(["БВИ"]);
  });

  it("порог и предмет ЕГЭ", () => {
    expect(egeLabel({ ege_subject: "математика", ege_min_score: 75 })).toBe(
      "ЕГЭ: математика, от 75",
    );
    expect(egeLabel({ ege_subject: "", ege_min_score: 70 })).toBe("ЕГЭ: от 70");
    expect(egeLabel({ ege_subject: "", ege_min_score: null })).toBeNull();
  });

  it("кому и название с профилем", () => {
    expect(whoLabel({ who: "winners_prizes" })).toBe(
      "Кому: победителям и призёрам",
    );
    expect(
      goalTitle({ short_name: "НТО", profile_name: "Робототехника" }),
    ).toBe("НТО — Робототехника");
    expect(goalTitle({ short_name: "ВсОШ", profile_name: "" })).toBe("ВсОШ");
  });
});
