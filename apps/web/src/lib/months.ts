export const MONTHS_FR = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"];

/** Clé de mois « AAAA-MM ». */
export const monthKey = (y: number, m: number) => `${y}-${String(m).padStart(2, "0")}`;
export const parseMonthKey = (k: string): { y: number; m: number } => ({ y: Number(k.slice(0, 4)), m: Number(k.slice(5, 7)) });
export const isMonthKey = (k: unknown): k is string => typeof k === "string" && /^\d{4}-(0[1-9]|1[0-2])$/.test(k);

/** Mois précédent / suivant (le changement d'année est automatique : décembre 2026 + 1 = janvier 2027). */
export function shiftMonthKey(k: string, delta: number): string {
  const { y, m } = parseMonthKey(k);
  const idx = y * 12 + (m - 1) + delta;
  return monthKey(Math.floor(idx / 12), (idx % 12) + 1);
}
export const monthLabel = (k: string) => { const { y, m } = parseMonthKey(k); return `${MONTHS_FR[m - 1]} ${y}`; };

/** Mois affiché par défaut : le mois courant ; s'il n'a pas de planning, le planning existant le plus proche ; sinon le mois courant. */
export function defaultMonthKey(periods: { start_date: string }[] | null | undefined, today = new Date()): string {
  const cur = monthKey(today.getFullYear(), today.getMonth() + 1);
  if (!periods || !periods.length || periods.some((p) => p.start_date.slice(0, 7) === cur)) return cur;
  const idx = (k: string) => { const { y, m } = parseMonthKey(k); return y * 12 + m; };
  return periods.map((p) => p.start_date.slice(0, 7)).sort((a, b) => Math.abs(idx(a) - idx(cur)) - Math.abs(idx(b) - idx(cur)) || b.localeCompare(a))[0];
}

/** Nombre de jours d'un mois (années bissextiles comprises). */
export const daysInMonth = (k: string) => { const { y, m } = parseMonthKey(k); return new Date(Date.UTC(y, m, 0)).getUTCDate(); };
