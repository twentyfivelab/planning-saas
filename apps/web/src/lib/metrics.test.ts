import { describe, expect, it } from "vitest";
import { brandIndex, brandVars, KNOWN_BRANDS } from "./brand";
import { budgetProgress, coverageRate, equityIndicator, hoursByEmployee, plannedByBrand, splitShares } from "./metrics";
import type { Assignment } from "./schedule";

const mk = (id: string, emp: string, day: string, min: number, alloc: Record<string, number>): Assignment => ({
  assignment_id: id, shift_id: id, slot_key: id, day, site: "S", start: "09:00:00", end: "18:00:00", presence_minutes: min + 60, break_minutes: 60,
  effective_minutes: min, employee_id: emp, employee: emp, locked: false, source: "solver", allocations: alloc });

describe("métriques du tableau de bord", () => {
  it("heures par marque : le co-branding impute 4 h + 4 h sans doubler les heures du collaborateur", () => {
    const a = [mk("1", "Jane", "2026-11-05", 480, { Cellcosmet: 240, Nuxe: 240 })];
    expect(plannedByBrand(a)).toEqual({ Cellcosmet: 240, Nuxe: 240 });
    expect(hoursByEmployee(a)).toEqual([{ id: "Jane", name: "Jane", minutes: 480, days: 1 }]);
    expect(splitShares(a[0].allocations).map((s) => s.pct)).toEqual([50, 50]);
  });
  it("taux de couverture et progression de budget", () => {
    expect(coverageRate(203, 0)).toBe(1); expect(coverageRate(0, 0)).toBeNull(); expect(coverageRate(90, 10)).toBe(0.9);
    expect(budgetProgress(1624 * 60, 1752 * 60)).toBe(93); expect(budgetProgress(10, 0)).toBe(0); expect(budgetProgress(200, 100)).toBe(100);
  });
  it("équité : indicateur indicatif (coefficient de variation), nul sans données exploitables", () => {
    expect(equityIndicator([480])).toBeNull(); expect(equityIndicator([0, 0])).toBeNull();
    expect(equityIndicator([100, 100, 100])?.cv).toBe(0);
    const e = equityIndicator([60, 120, 180])!; expect(e.min).toBe(60); expect(e.max).toBe(180); expect(e.cv).toBeGreaterThan(0.4);
  });
  it("palette marques : stable, bornée à 10 teintes, marques connues distinctes (Cellcosmet ≠ Nuxe)", () => {
    expect(brandIndex("Cellcosmet")).not.toBe(brandIndex("Nuxe"));
    expect(new Set(KNOWN_BRANDS.map(brandIndex)).size).toBe(KNOWN_BRANDS.length);
    const n = brandIndex("Marque inconnue"); expect(n).toBeGreaterThanOrEqual(1); expect(n).toBeLessThanOrEqual(10); expect(brandIndex("Marque inconnue")).toBe(n);
    expect(brandVars("Cartier")["--c"]).toBe("var(--brand-3)");
  });
});
