import { describe, expect, it } from "vitest";
import { parseStartParam } from "./startParam";

describe("parseStartParam", () => {
  it("экраны по ссылке startapp", () => {
    expect(parseStartParam("diplomas")).toEqual({ kind: "diplomas" });
    expect(parseStartParam("program-12")).toEqual({ kind: "program", id: 12 });
    expect(parseStartParam("olympiad-5")).toEqual({ kind: "olympiad", id: 5 });
    expect(parseStartParam("s_AbCdE12345")).toEqual({ kind: "share", token: "AbCdE12345" });
  });

  it("мусор и пустой payload — обычный запуск", () => {
    for (const value of [undefined, null, "", "program-", "program-0", "olympiad-x", "s_short", "s_AbCdE12345!", "other"]) {
      expect(parseStartParam(value)).toBeNull();
    }
  });
});
