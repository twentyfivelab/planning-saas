import { MONTHS_FR, daysBetween, weekdayIdx } from "./schedule";

export type CalCell = { iso: string; day: number } | null;
export type Month = { key: string; label: string; weeks: CalCell[][] };

/** Mois (grille lundi → dimanche) à partir d'un jour ISO quelconque. */
export function monthOf(anchorIso: string): Month {
  const [y, m] = anchorIso.split("-").map(Number);
  const first = `${y}-${String(m).padStart(2, "0")}-01`;
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const days = daysBetween(first, `${y}-${String(m).padStart(2, "0")}-${String(last).padStart(2, "0")}`);
  const cells: CalCell[] = [...Array(weekdayIdx(first)).fill(null), ...days.map((iso) => ({ iso, day: Number(iso.slice(8)) }))];
  while (cells.length % 7) cells.push(null);
  return { key: first.slice(0, 7), label: `${MONTHS_FR[m - 1][0].toUpperCase()}${MONTHS_FR[m - 1].slice(1)} ${y}`, weeks: Array.from({ length: cells.length / 7 }, (_, i) => cells.slice(i * 7, i * 7 + 7)) };
}
export function shiftMonth(anchorIso: string, delta: number): string {
  const [y, m] = anchorIso.split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 1 + delta, 1));
  return d.toISOString().slice(0, 10);
}
/** Ajoute ou retire une date (bascule) ; résultat trié, sans doublon. */
export function toggleDate(dates: string[], iso: string): string[] {
  const s = new Set(dates); if (s.has(iso)) s.delete(iso); else s.add(iso);
  return [...s].sort();
}
/** Sélection d'une plage (Maj + clic) : toutes les dates entre `a` et `b` incluses sont ajoutées. */
export function addRange(dates: string[], a: string, b: string): string[] {
  const [from, to] = a <= b ? [a, b] : [b, a];
  return [...new Set([...dates, ...daysBetween(from, to)])].sort();
}
export const isBlockedByRule = (iso: string, weekdays: number[], leaves: { start: string; end: string }[]) =>
  weekdays.includes(weekdayIdx(iso)) || leaves.some((l) => iso >= l.start && iso <= l.end);
