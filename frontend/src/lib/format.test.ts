import { describe, expect, it } from "vitest";
import { codesOf, dash, fmt, place, plural } from "./format";

describe("format", () => {
  it("склоняет по числу", () => {
    const vuz = (n: number) => plural(n, "вуз", "вуза", "вузов");
    expect([1, 2, 5, 11, 21, 22, 25, 111].map(vuz)).toEqual([
      "вуз",
      "вуза",
      "вузов",
      "вузов",
      "вуз",
      "вуза",
      "вузов",
      "вузов",
    ]);
  });

  it("форматирует числа по-русски", () => {
    expect(fmt(48963)).toBe("48 963");
    expect(fmt(undefined)).toBe("0");
  });

  it("город или регион вуза", () => {
    expect(place({ city: "Казань", region: "Приволжский ФО" })).toBe("Казань");
    expect(place({ city: "", region: "Москва" })).toBe("Москва");
  });

  it("прочерк для пустых значений и коды направлений", () => {
    expect(dash("")).toBe("—");
    expect(codesOf("09.03.04, 01.03.02")).toBe("01.03.02,09.03.04");
  });
});
