export type Assignment = {
  assignment_id: string; shift_id: string; slot_key: string; day: string; site: string; start: string; end: string;
  presence_minutes: number; break_minutes: number; effective_minutes: number; employee_id: string; employee: string;
  locked: boolean; source: string; allocations: Record<string, number>;
};

export const hours = (min: number) => `${+(min / 60).toFixed(2)} h`;

/** Jours de la période (ISO), calculés sans fuseau pour éviter tout décalage. */
export function daysBetween(start: string, end: string): string[] {
  const out: string[] = [];
  const d = new Date(start + "T12:00:00Z");
  const e = new Date(end + "T12:00:00Z");
  for (; d <= e; d.setUTCDate(d.getUTCDate() + 1)) out.push(d.toISOString().slice(0, 10));
  return out;
}

export const weekdayIdx = (iso: string) => !iso ? 0 : (new Date(iso + "T12:00:00Z").getUTCDay() + 6) % 7; // 0 = lundi

export function weekStart(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso + "T12:00:00Z");
  d.setUTCDate(d.getUTCDate() - weekdayIdx(iso));
  return d.toISOString().slice(0, 10);
}

export function filterAssignments(a: Assignment[], q: { text?: string; employee?: string; site?: string; brand?: string }) {
  const t = q.text?.trim().toLowerCase();
  return a.filter((x) =>
    (!t || x.employee.toLowerCase().includes(t) || x.site.toLowerCase().includes(t) || x.slot_key.toLowerCase().includes(t)) &&
    (!q.employee || x.employee_id === q.employee) && (!q.site || x.site === q.site) &&
    (!q.brand || q.brand in x.allocations));
}

/** Pile annuler/rétablir pour les réaffectations manuelles. */
export type Move = { assignmentId: string; from: string; to: string };
export class History {
  private undoStack: Move[] = []; private redoStack: Move[] = [];
  push(m: Move) { this.undoStack.push(m); this.redoStack = []; }
  undo(): Move | undefined { const m = this.undoStack.pop(); if (m) this.redoStack.push(m); return m; }
  redo(): Move | undefined { const m = this.redoStack.pop(); if (m) this.undoStack.push(m); return m; }
  get canUndo() { return this.undoStack.length > 0; }
  get canRedo() { return this.redoStack.length > 0; }
}

export function diffSchedules(before: Assignment[], after: Assignment[]) {
  const b = new Map(before.map((x) => [x.slot_key, x.employee])); const a = new Map(after.map((x) => [x.slot_key, x.employee]));
  const changed: { slot: string; from: string; to: string }[] = [];
  for (const [k, v] of a) if (b.has(k) && b.get(k) !== v) changed.push({ slot: k, from: b.get(k)!, to: v });
  return { added: [...a.keys()].filter((k) => !b.has(k)), removed: [...b.keys()].filter((k) => !a.has(k)), changed };
}

export type ShiftKind = "open" | "day" | "close";
export const KIND_LABEL: Record<ShiftKind, string> = { open: "Ouverture", day: "Journée", close: "Fermeture" };

/** Type de shift déduit des horaires (présentation uniquement) : début avant 9 h = ouverture, fin à 20 h 30 ou après = fermeture. */
export function shiftKind(start: string, end: string): ShiftKind {
  const toH = (t: string) => Number(t.slice(0, 2)) + Number(t.slice(3, 5)) / 60;
  if (toH(end) >= 20.5) return "close";
  if (toH(start) < 9 && toH(start) < toH(end)) return "open";
  return "day";
}

/** Marque principale d'une affectation (plus grande imputation). */
export function mainBrand(allocations: Record<string, number>): string {
  const e = Object.entries(allocations).sort((a, b) => b[1] - a[1]);
  return e[0]?.[0] ?? "";
}

/** Les 7 jours (lundi → dimanche) de la semaine contenant `iso`. */
export function weekOf(iso: string): string[] {
  const start = weekStart(iso);
  return start ? daysBetween(start, addDays(start, 6)) : [];
}

export function addDays(iso: string, n: number): string {
  if (!iso) return "";
  const d = new Date(iso + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10);
}

/** Semaine proposée par défaut : la première qui contient au moins 5 jours de la période (évite une semaine d'un seul jour). */
export function defaultWeek(days: string[]): string {
  if (!days.length) return "";
  const first = days.find((d) => weekOf(d).filter((x) => days.includes(x)).length >= 5);
  return first ?? days[0];
}

/** Associe chaque conflit du vérificateur aux affectations dont la clé de slot y figure. */
export function conflictsBySlot(conflicts: string[], assignments: Assignment[]): Map<string, string[]> {
  const out = new Map<string, string[]>();
  for (const c of conflicts) for (const a of assignments) if (c.includes(a.slot_key)) out.set(a.assignment_id, [...(out.get(a.assignment_id) ?? []), c]);
  return out;
}

export const fmtHM = (min: number) => { const h = Math.floor(min / 60), m = min % 60; return m ? `${h} h ${String(m).padStart(2, "0")}` : `${h} h`; };
export const timeShort = (t: string) => t.slice(0, 5);
export const DOW_SHORT = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
export const MONTHS_SHORT = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
export const MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];
export function dayLabel(iso?: string): string { if (!iso) return ""; const [, m, d] = iso.split("-").map(Number); return `${DOW_SHORT[weekdayIdx(iso)]} ${d} ${MONTHS_SHORT[m - 1]}`; }
