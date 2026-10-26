import { describe, expect, it } from "vitest";
import { daysBetween, diffSchedules, History, weekdayIdx, weekStart, filterAssignments, Assignment } from "./schedule";

const mk = (slot: string, employee: string, extra: Partial<Assignment> = {}): Assignment => ({
  assignment_id: slot, shift_id: slot, slot_key: slot, day: "2026-11-02", site: "GVA3", start: "06:00:00", end: "15:00:00",
  presence_minutes: 540, break_minutes: 60, effective_minutes: 480, employee_id: employee, employee, locked: false,
  source: "solver", allocations: { "Ploom GVA3": 480 }, ...extra });

describe("schedule helpers", () => {
  it("compte 30 jours en novembre 2026 et place le 1er un dimanche", () => {
    expect(daysBetween("2026-11-01", "2026-11-30")).toHaveLength(30);
    expect(weekdayIdx("2026-11-01")).toBe(6);
    expect(weekStart("2026-11-04")).toBe("2026-11-02");
  });
  it("ne plante pas avant le chargement de la période (jour vide)", () => {
    expect(weekStart("")).toBe("");
  });
  it("filtre par texte, site et marque", () => {
    const a = [mk("a", "Jane"), mk("b", "Zaki", { site: "Cartier", allocations: { Cartier: 480 } })];
    expect(filterAssignments(a, { text: "jan" })).toHaveLength(1);
    expect(filterAssignments(a, { site: "Cartier" })[0].employee).toBe("Zaki");
    expect(filterAssignments(a, { brand: "Cartier" })).toHaveLength(1);
  });
  it("annuler / rétablir", () => {
    const h = new History(); h.push({ assignmentId: "1", from: "a", to: "b" });
    expect(h.undo()?.to).toBe("b"); expect(h.canUndo).toBe(false); expect(h.redo()?.from).toBe("a");
  });
  it("compare avant/après", () => {
    const d = diffSchedules([mk("a", "X"), mk("b", "Y")], [mk("a", "Z"), mk("c", "Y")]);
    expect(d.changed).toEqual([{ slot: "a", from: "X", to: "Z" }]); expect(d.added).toEqual(["c"]); expect(d.removed).toEqual(["b"]);
  });
});
