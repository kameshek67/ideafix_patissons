import { describe, expect, it } from "vitest";
import { duration, pct, ruDate } from "./quality";

describe("pct", () => {
  it("не округляет до крайних значений", () => {
    expect(pct(0.7385)).toBe("74%");
    expect(pct(0.9979)).toBe("99%");
    expect(pct(0.003)).toBe("меньше 1%");
    expect(pct(1)).toBe("100%");
    expect(pct(0)).toBe("0%");
  });
});

describe("ruDate", () => {
  it("читает дату в начале строки", () => {
    expect(ruDate("2026-11-26T07:20:50+0300")).toBe("26 ноября 2026");
    expect(ruDate("2026-09-04")).toBe("4 сентября 2026");
    expect(ruDate("вчера")).toBeNull();
    expect(ruDate(null)).toBeNull();
  });
});

describe("duration", () => {
  it("часы, дни, меньше часа", () => {
    expect(duration(0.4)).toBe("меньше часа");
    expect(duration(5.2)).toBe("5 ч");
    expect(duration(72)).toBe("3 дн.");
  });
});
