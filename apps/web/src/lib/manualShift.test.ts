import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import { canAccept, parseDetail, rowLabel, sortRows, type AssignDetail, type DayRow } from "./manualShift";

const row = (o: Partial<DayRow>): DayRow => ({ shift_id: "s", assignment_id: null, slot_key: "k", site: "GVA3", start: "08:00:00", end: "17:00:00", effective_minutes: 480, brands: ["Ploom GVA3"], status: "available", locked: false, manual: false, assigned_to: null, mine: false, brand_ok: true, issues: [], ...o });

describe("gestion manuelle des shifts", () => {
  it("lit le détail structuré d'un refus du serveur, ignore les autres erreurs", () => {
    const d = { code: "needs_confirmation", issues: [], can_override: true, message: "m" };
    expect(parseDetail(new ApiError(409, d))).toMatchObject({ code: "needs_confirmation", can_override: true });
    expect(parseDetail(new ApiError(500, "Erreur interne"))).toBeNull();
    expect(parseDetail(new Error("x"))).toBeNull();
  });
  it("« Accepter quand même » : jamais si bloquant, jamais sans droit de dérogation", () => {
    const base: AssignDetail = { code: "needs_confirmation", can_override: true, message: "", issues: [{ code: "REST", level: "override", message: "", legal: true }] };
    expect(canAccept(base)).toBe(true);
    expect(canAccept({ ...base, can_override: false })).toBe(false);
    expect(canAccept({ ...base, issues: [{ code: "SAME_DAY", level: "blocking", message: "", legal: false }] })).toBe(false);
    expect(canAccept({ ...base, code: "blocked" })).toBe(false);
  });
  it("libres d'abord puis par boutique et heure", () => {
    const rows = [row({ shift_id: "a", status: "assigned", site: "GVA3" }), row({ shift_id: "b", site: "GVA9", start: "10:00:00" }), row({ shift_id: "c", site: "GVA3", start: "06:00:00" })];
    expect(sortRows(rows).map((r) => r.shift_id)).toEqual(["c", "b", "a"]);
  });
  it("libellés d'action", () => {
    expect(rowLabel(row({}), "Sahra")).toBe("Attribuer à Sahra");
    expect(rowLabel(row({ status: "assigned", assigned_to: { id: "k", name: "Kristina" } }), "Sahra")).toBe("Transférer de Kristina à Sahra");
    expect(rowLabel(row({ mine: true }), "Sahra")).toBe("Déjà attribué à Sahra");
  });
});
