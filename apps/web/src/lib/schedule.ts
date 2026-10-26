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

export const weekdayIdx = (iso: string) => (new Date(iso + "T12:00:00Z").getUTCDay() + 6) % 7; // 0 = lundi

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
