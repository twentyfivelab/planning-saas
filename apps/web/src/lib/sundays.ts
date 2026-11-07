export type SundayMode = "max" | "exact";
export type SundayEmployee = { code: string; name?: string; sunday_quota: number | null; sunday_mode: SundayMode };
export type SundaySummary = {
  sundays: string[]; per_sunday: number; total: number; by_site: Record<string, number>; by_day: Record<string, number>;
  reserved: number; reserved_exact: number; reserved_max: number; capacity_max: number; planned: number; remaining_to_reserve: number; unplanned: number; flexible_employees: number;
  employees: Record<string, { name: string; quota: number | null; mode: SundayMode | null; available_sundays: number; planned: number; warnings: string[] }>;
  alerts: { level: "info" | "warning"; text: string }[];
};

export type Counter = { total: number; reserved: number; reservedExact: number; reservedMax: number; planned: number; remaining: number; unplanned: number; capacity: number; flexible: number; alerts: { level: "info" | "warning"; text: string }[] };

/**
 * Compteur recalculé côté client à partir des quotas ACTUELS (y compris un brouillon non enregistré) et des chiffres serveur
 * (total de shifts, shifts réellement planifiés). Même règles que le serveur :
 * - réservés = somme des quotas « objectif exact » ; un quota « maximum » plafonne sans réserver ;
 * - restant à attribuer = total - réservés ; non planifiés = total - planifiés (deux notions distinctes, pas de double comptage).
 */
export function computeCounter(base: Pick<SundaySummary, "total" | "planned" | "sundays">, employees: SundayEmployee[]): Counter {
  const nSun = base.sundays.length;
  let reservedExact = 0, reservedMax = 0, flexible = 0;
  for (const e of employees) {
    if (e.sunday_quota === null || e.sunday_quota === undefined) { flexible++; continue; }
    const eff = Math.min(e.sunday_quota, nSun);
    if (e.sunday_mode === "exact") reservedExact += eff; else reservedMax += eff;
  }
  const reserved = reservedExact + reservedMax;
  const remaining = Math.max(0, base.total - reserved);
  const alerts: Counter["alerts"] = [];
  if (remaining > 0) {
    if (flexible === 0) alerts.push({ level: "warning", text: `${base.total - reserved} shift(s) du dimanche ne peuvent être couverts : tous les collaborateurs ont un quota et la capacité cumulée est de ${reserved} pour ${base.total} shifts.` });
    else alerts.push({ level: "info", text: `${remaining} shift(s) du dimanche restent à distribuer : le moteur les répartira entre les collaborateurs sans quota.` });
  }
  if (reserved > base.total) alerts.push({ level: "warning", text: `Les quotas réservés (${reserved}) dépassent les ${base.total} shifts du dimanche.` });
  if (base.total - base.planned > 0 && base.planned > 0) alerts.push({ level: "warning", text: `${base.total - base.planned} shift(s) du dimanche non planifié(s).` });
  return { total: base.total, reserved, reservedExact, reservedMax, planned: base.planned, remaining, unplanned: base.total - base.planned, capacity: reserved, flexible, alerts };
}
