import { describe, expect, it } from "vitest";
import { daysInMonth, defaultMonthKey, isMonthKey, monthLabel, shiftMonthKey } from "./months";

describe("mois et années", () => {
  it("change d'année automatiquement", () => {
    expect(shiftMonthKey("2026-11", 1)).toBe("2026-12");
    expect(shiftMonthKey("2026-12", 1)).toBe("2027-01");
    expect(shiftMonthKey("2027-01", -1)).toBe("2026-12");
    expect(shiftMonthKey("2026-11", 14)).toBe("2028-01");
    expect(shiftMonthKey("2026-01", -13)).toBe("2024-12");
  });
  it("libellés, validité et nombre de jours exacts", () => {
    expect(monthLabel("2026-12")).toBe("Décembre 2026");
    expect(isMonthKey("2026-13")).toBe(false); expect(isMonthKey("2026-1")).toBe(false); expect(isMonthKey("2026-02")).toBe(true);
    expect([daysInMonth("2026-11"), daysInMonth("2026-12"), daysInMonth("2027-02"), daysInMonth("2028-02")]).toEqual([30, 31, 28, 29]);
  });
  it("mois par défaut : mois courant, sinon le planning le plus proche", () => {
    const ps = [{ start_date: "2026-11-01" }, { start_date: "2027-01-01" }, { start_date: "2026-12-01" }];
    expect(defaultMonthKey(ps, new Date(2026, 11, 15))).toBe("2026-12");
    expect(defaultMonthKey([{ start_date: "2026-11-01" }], new Date(2026, 4, 1))).toBe("2026-11");
    expect(defaultMonthKey([{ start_date: "2026-11-01" }], new Date(2027, 2, 1))).toBe("2026-11");
    expect(defaultMonthKey([], new Date(2030, 4, 12))).toBe("2030-05");
    expect(defaultMonthKey(null, new Date(2030, 4, 12))).toBe("2030-05");
  });
});
