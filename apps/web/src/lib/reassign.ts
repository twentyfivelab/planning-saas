import type { Assignment } from "./schedule";
import { MONTHS_FR, weekdayIdx } from "./schedule";

export type Preview = { kind: "overlap" | "rest" | "consecutive" | "brand"; text: string };

const DAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"];
/** « Lundi 2 novembre 2026 » */
export function longDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const w = DAYS_FR[weekdayIdx(iso)];
  return `${w[0].toUpperCase()}${w.slice(1)} ${d === 1 ? "1er" : d} ${MONTHS_FR[m - 1]} ${y}`;
}
/** « 06h00 à 15h00 » */
export const hourRange = (start: string, end: string) => `${start.slice(0, 2)}h${start.slice(3, 5)} à ${end.slice(0, 2)}h${end.slice(3, 5)}`;

const ms = (day: string, t: string, plusDays = 0) => Date.UTC(+day.slice(0, 4), +day.slice(5, 7) - 1, +day.slice(8, 10) + plusDays, +t.slice(0, 2), +t.slice(3, 5));
const span = (x: Assignment): [number, number] => [ms(x.day, x.start), ms(x.day, x.end, x.end <= x.start ? 1 : 0)];

/**
 * Avertissements détectables AVANT enregistrement, côté client : chevauchement, repos < `restHours`, jours consécutifs > `maxDays`,
 * marque non déclarée pour le collaborateur. Indicatif : le serveur recalcule et enregistre les conflits réels après sauvegarde.
 */
export function previewConflicts(a: Assignment, toEmployeeId: string, all: Assignment[], toBrands?: Record<string, string>, restHours = 11, maxDays = 6): Preview[] {
  const out: Preview[] = [];
  const mine = all.filter((x) => x.employee_id === toEmployeeId && x.assignment_id !== a.assignment_id);
  const [s, e] = span(a);
  for (const b of mine) {
    const [bs, be] = span(b);
    if (bs < e && s < be) out.push({ kind: "overlap", text: `Chevauchement : déjà affecté·e le ${b.day.slice(8)}/${b.day.slice(5, 7)} de ${b.start.slice(0, 5)} à ${b.end.slice(0, 5)} (${b.site}).` });
    else {
      const gap = s >= be ? s - be : bs - e;
      if (gap < restHours * 3_600_000) out.push({ kind: "rest", text: `Repos de ${Math.floor(gap / 3_600_000)} h seulement avec le shift du ${b.day.slice(8)}/${b.day.slice(5, 7)} (minimum ${restHours} h).` });
    }
  }
  const days = new Set(mine.map((x) => x.day)); days.add(a.day);
  const shift = (iso: string, n: number) => new Date(ms(iso, "00:00", n)).toISOString().slice(0, 10);
  let run = 1;
  for (let d = shift(a.day, -1); days.has(d); d = shift(d, -1)) run++;
  for (let d = shift(a.day, 1); days.has(d); d = shift(d, 1)) run++;
  if (run > maxDays) out.push({ kind: "consecutive", text: `${run} jours consécutifs travaillés (maximum ${maxDays}).` });
  if (toBrands) for (const br of Object.keys(a.allocations)) if (!(br in toBrands)) out.push({ kind: "brand", text: `${br} ne figure pas dans les marques déclarées de ce collaborateur.` });
  return out;
}
