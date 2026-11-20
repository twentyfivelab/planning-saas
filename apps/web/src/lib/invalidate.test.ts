import { describe, expect, it } from "vitest";
import { PLANNING_ACTIONS, PLANNING_VIEWS } from "./invalidate";

describe("rafraîchissement ciblé après une modification d'un autre manager", () => {
  it("reconnaît les actions qui ne touchent que le contenu du planning", () => {
    for (const a of ["assignment.reassign", "assignment.bulk_transfer", "shift.edit", "shift.placed", "need.placed", "replacement.accepted"]) expect(PLANNING_ACTIONS.test(a)).toBe(true);
    for (const a of ["employees.update", "settings.weights", "period.roster", "catalog.brand_update", "budgets.create", "optimization.finished"]) expect(PLANNING_ACTIONS.test(a)).toBe(false);
  });
  it("relit les vues qui dépendent du planning, pas les référentiels ni les paramètres", () => {
    for (const p of ["/periods/x/schedule", "/periods/x/conflicts", "/periods/x/sunday-summary", "/periods/x/optional-needs", "/periods/x/regularizations",
      "/periods/x/replacement-requests", "/periods/x/integrations", "/runs/r/summary", "/employees/e/month?month=2026-12", "/notifications?unread=true&limit=1", "/periods", "/me/planning", "/periods/x/compatibility"])
      expect(PLANNING_VIEWS.test(p)).toBe(true);
    for (const p of ["/employees?include_deleted=true", "/budgets", "/brands", "/sites", "/catalog?month=2026-12", "/calendar?year=2026&month=12",
      "/periods/x/params", "/site-travel", "/clients"]) expect(PLANNING_VIEWS.test(p)).toBe(false);
  });
});
