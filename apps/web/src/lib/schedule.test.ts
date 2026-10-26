import { describe, expect, it } from "vitest";
import { addDays, dayLabel, defaultWeek, weekOf, conflictsBySlot, shiftKind, daysBetween, diffSchedules, History, weekdayIdx, weekStart, filterAssignments, Assignment } from "./schedule";

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
  it("helpers de dates robustes à une valeur vide", () => {
    expect(addDays("", 3)).toBe(""); expect(dayLabel("")).toBe(""); expect(weekOf("")).toEqual([]); expect(defaultWeek([])).toBe("");
  });
  it("semaine par défaut : évite la semaine d'un seul jour (1er novembre 2026 = dimanche)", () => {
    const days = daysBetween("2026-11-01", "2026-11-30");
    expect(defaultWeek(days)).toBe("2026-11-02");
    expect(weekOf("2026-11-04")).toHaveLength(7); expect(weekOf("2026-11-04")[0]).toBe("2026-11-02");
    expect(addDays("2026-11-30", 1)).toBe("2026-12-01"); expect(dayLabel("2026-11-06")).toBe("Ven 6 nov.");
  });
  it("type de shift déduit des horaires", () => {
    expect(shiftKind("06:00:00", "15:00:00")).toBe("open"); expect(shiftKind("10:00:00", "19:00:00")).toBe("day");
    expect(shiftKind("12:00:00", "21:00:00")).toBe("close"); expect(shiftKind("12:30:00", "21:30:00")).toBe("close");
  });
  it("associe les conflits aux affectations par clé de slot", () => {
    const a = [mk("GVA3|2026-11-03|x", "Jane"), mk("GVA9|y", "Zaki")];
    const m = conflictsBySlot(["OVERLAP: Jane GVA3|2026-11-03|x / z"], a);
    expect(m.get("GVA3|2026-11-03|x")).toHaveLength(1); expect(m.has("GVA9|y")).toBe(false);
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
