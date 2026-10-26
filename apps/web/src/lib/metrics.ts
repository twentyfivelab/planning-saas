import type { Assignment } from "./schedule";

export type BudgetRow = { brand_code: string; target_minutes: number; requirements_defined: boolean };

export function plannedByBrand(a: Assignment[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const x of a) for (const [b, m] of Object.entries(x.allocations)) out[b] = (out[b] ?? 0) + m;
  return out;
}

export function hoursByEmployee(a: Assignment[]): { id: string; name: string; minutes: number; days: number }[] {
  const m = new Map<string, { id: string; name: string; minutes: number; days: Set<string> }>();
  for (const x of a) {
    const e = m.get(x.employee_id) ?? { id: x.employee_id, name: x.employee, minutes: 0, days: new Set<string>() };
    e.minutes += x.effective_minutes; e.days.add(x.day); m.set(x.employee_id, e);
  }
  return [...m.values()].map((e) => ({ id: e.id, name: e.name, minutes: e.minutes, days: e.days.size })).sort((p, q) => q.minutes - p.minutes);
}

/** Taux de couverture des shifts : pourvus / (pourvus + non pourvus). null s'il n'y a aucun shift. */
export function coverageRate(assigned: number, uncovered: number): number | null {
  const total = assigned + uncovered;
  return total === 0 ? null : assigned / total;
}

/**
 * Indicateur d'équité INDICATIF : coefficient de variation des heures effectives (écart-type / moyenne).
 * Sans contrats renseignés il ne peut pas être relatif aux heures contractuelles : à présenter comme tel.
 * Retourne null s'il y a moins de 2 collaborateurs ou une moyenne nulle.
 */
export function equityIndicator(minutes: number[]): { cv: number; min: number; max: number } | null {
  if (minutes.length < 2) return null;
  const mean = minutes.reduce((s, v) => s + v, 0) / minutes.length;
  if (mean === 0) return null;
  const variance = minutes.reduce((s, v) => s + (v - mean) ** 2, 0) / minutes.length;
  return { cv: Math.sqrt(variance) / mean, min: Math.min(...minutes), max: Math.max(...minutes) };
}

export function budgetProgress(planned: number, target: number): number {
  return target <= 0 ? 0 : Math.min(100, Math.round((100 * planned) / target));
}

/** Parts (en %) de chaque marque dans une affectation co-brandée, somme = 100. */
export function splitShares(allocations: Record<string, number>): { brand: string; minutes: number; pct: number }[] {
  const total = Object.values(allocations).reduce((s, v) => s + v, 0);
  if (!total) return [];
  return Object.entries(allocations).map(([brand, minutes]) => ({ brand, minutes, pct: Math.round((100 * minutes) / total) }));
}
