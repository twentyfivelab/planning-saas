import { describe, expect, it } from "vitest";
import { addRange, isBlockedByRule, monthOf, shiftMonth, toggleDate } from "./calendar";

describe("calendrier d'indisponibilités", () => {
  it("novembre 2026 : 30 jours, commence un dimanche (6 cases vides avant), 6 semaines", () => {
    const m = monthOf("2026-11-15");
    expect(m.label).toBe("Novembre 2026");
    expect(m.weeks.flat().filter(Boolean)).toHaveLength(30);
    expect(m.weeks[0].slice(0, 6).every((c) => c === null)).toBe(true); expect(m.weeks[0][6]).toEqual({ iso: "2026-11-01", day: 1 });
    expect(m.weeks).toHaveLength(6); expect(m.weeks.every((w) => w.length === 7)).toBe(true);
  });
  it("navigation de mois, y compris le changement d'année", () => {
    expect(shiftMonth("2026-11-15", 1)).toBe("2026-12-01"); expect(shiftMonth("2026-12-10", 1)).toBe("2027-01-01"); expect(shiftMonth("2026-01-31", -1)).toBe("2025-12-01");
  });
  it("Zaki indisponible les 5, 12 et 18 novembre : sélection, retrait, tri, pas de doublon", () => {
    let d: string[] = [];
    for (const x of ["2026-11-12", "2026-11-05", "2026-11-18", "2026-11-05"]) d = toggleDate(d, x);
    expect(d).toEqual(["2026-11-12", "2026-11-18"]); // le 5 a été retiré (2e clic)
    d = toggleDate(d, "2026-11-05");
    expect(d).toEqual(["2026-11-05", "2026-11-12", "2026-11-18"]);
  });
  it("plage Maj + clic", () => {
    expect(addRange(["2026-11-02"], "2026-11-05", "2026-11-03")).toEqual(["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"]);
  });
  it("jours déjà bloqués par une règle (mardi récurrent, congé approuvé)", () => {
    expect(isBlockedByRule("2026-11-03", [1], [])).toBe(true); expect(isBlockedByRule("2026-11-04", [1], [])).toBe(false);
    expect(isBlockedByRule("2026-11-10", [], [{ start: "2026-11-09", end: "2026-11-11" }])).toBe(true);
  });
});
