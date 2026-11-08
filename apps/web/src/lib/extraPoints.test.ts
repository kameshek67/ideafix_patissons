import { describe, expect, it } from "vitest";
import type { ExtraUniversity, UniversityItem } from "./api";
import { filterUniversities, pointsUniversities } from "./extraPoints";

const uni = (id: number, name: string) => ({ id, name }) as UniversityItem;
const extra = (id: number, name: string, rules: number) => ({ id, name, short_name: name, rules }) as ExtraUniversity;

describe("вузы вкладки «Баллы»", () => {
  it("все вузы каталога, сначала с разобранными правилами", () => {
    const list = pointsUniversities(
      [uni(1, "Уральский"), uni(2, "Бауманка"), uni(3, "ВШЭ")],
      [extra(3, "ВШЭ", 16)],
    );
    expect(list.map((u) => [u.name, u.rules])).toEqual([
      ["ВШЭ", 16],
      ["Бауманка", 0],
      ["Уральский", 0],
    ]);
  });

  it("вуз с правилами, которого нет в каталоге, не теряется", () => {
    expect(pointsUniversities([], [extra(7, "МИФИ", 2)])).toEqual([{ id: 7, name: "МИФИ", rules: 2 }]);
  });

  it("поиск без учёта регистра и «ё»", () => {
    const list = [
      { id: 1, name: "Сибирский федеральный" },
      { id: 2, name: "Псковский государственный" },
    ].map((u) => ({ ...u, rules: 0 }));
    expect(filterUniversities(list, "СИБИР").map((u) => u.id)).toEqual([1]);
    expect(filterUniversities(list, "  ").length).toBe(2);
    expect(filterUniversities([{ id: 3, name: "Орёл", rules: 0 }], "орел").length).toBe(1);
  });
});
