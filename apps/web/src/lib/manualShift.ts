import { ApiError } from "./api";

export type Issue = { code: string; level: "blocking" | "override" | "soft"; message: string; legal: boolean; needs_unlock?: boolean; rule?: string; limit?: string; reached?: string; consequence?: string };
export type AssignDetail = { code: "blocked" | "needs_confirmation" | "forbidden" | "locked" | "stale" | "gone"; issues?: Issue[]; can_override: boolean; message: string; refusal?: string | null };
export type DayRow = {
  shift_id: string; assignment_id: string | null; slot_key: string; site: string; start: string; end: string; effective_minutes: number; brands: string[];
  status: "available" | "assigned"; locked: boolean; manual: boolean; assigned_to: { id: string; name: string } | null; mine: boolean; brand_ok: boolean;
  issues: { code: string; level: Issue["level"]; message: string }[];
};
export type HistoryRow = {
  id: string; at: string; kind: string; by: string; day: string | null; site: string | null; start: string | null; end: string | null;
  from: string | null; to: string | null; forced: boolean; reason: string | null; issues: string[];
};

/** Lit le détail structuré d'un refus 409/403 du serveur (alertes de contraintes) ; null pour toute autre erreur. */
export function parseDetail(e: unknown): AssignDetail | null {
  if (!(e instanceof ApiError) || typeof e.detail !== "object" || e.detail === null) return null;
  const d = e.detail as Partial<AssignDetail>;
  return typeof d.code === "string" && typeof d.message === "string" ? { can_override: false, ...d } as AssignDetail : null;
}

/** Libres d'abord, puis par boutique et heure : l'ordre dans lequel on cherche un remplaçant. */
export function sortRows(rows: DayRow[]): DayRow[] {
  return [...rows].sort((a, b) => (a.status === b.status ? 0 : a.status === "available" ? -1 : 1) || a.site.localeCompare(b.site) || a.start.localeCompare(b.start));
}

export const blockingOf = (issues: Issue[] = []) => issues.filter((i) => i.level === "blocking");
/** « Accepter quand même » n'est proposé que si rien n'est bloquant et que le rôle peut déroger. */
export const canAccept = (d: AssignDetail) => d.code === "needs_confirmation" && d.can_override && blockingOf(d.issues).length === 0;

export const rowLabel = (r: DayRow, who: string) =>
  r.mine ? `Déjà attribué à ${who}` : r.status === "available" ? `Attribuer à ${who}` : `Transférer de ${r.assigned_to?.name ?? "?"} à ${who}`;
