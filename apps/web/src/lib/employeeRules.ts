export type MaxDaysPeriod = "week" | "month";
export type TimePref = "matin" | "middle" | "soir";

export type RulesDraft = {
  max_days_count: number | null; max_days_period: MaxDaysPeriod | null;
  time_pref: TimePref | null; time_pref_strict: boolean;
  sunday_quota: number | null; sunday_mode: "max" | "exact";
  /** jours travaillés par mois civil : null = « Pas de préférence » (le plafond mensuel d'heures reste appliqué) */
  min_days_month?: number | null; max_days_month?: number | null;
};

/** Contrôle d'un couple minimum / maximum de jours par mois (indépendants ; une journée compte une fois). */
export function validateDays(min: number | null | undefined, max: number | null | undefined, periodDays = 31): string[] {
  const errs: string[] = [];
  const n = Math.min(31, periodDays);
  if (min != null && (min < 1 || min > n)) errs.push(`Le minimum de jours doit être compris entre 1 et ${n} (ce mois compte ${n} jours).`);
  if (max != null && (max < 1 || max > n)) errs.push(`Le maximum de jours doit être compris entre 1 et ${n} (ce mois compte ${n} jours).`);
  if (min != null && max != null && min > max) errs.push(`Le minimum (${min} jours) dépasse le maximum (${max} jours) : corrigez l'un des deux.`);
  return errs;
}

export const NO_PREF = "";
export const PERIOD_LABEL: Record<MaxDaysPeriod, string> = { week: "Semaine", month: "Mois" };
export const TIME_PREF_LABEL: Record<TimePref, string> = { matin: "Matin", middle: "Middle shift", soir: "Soir" };
export const TIME_PREF_HELP: Record<TimePref, string> = {
  matin: "Ouvertures : shifts commençant avant 9 h (6 h, 7 h, 8 h).",
  middle: "Shifts intermédiaires : commençant entre 9 h et 11 h 59 (10 h, 11 h).",
  soir: "Fermetures : shifts commençant à partir de 12 h (12 h–21 h, 12 h 30–21 h 30).",
};

/** Valeurs possibles du nombre de jours : 1 à 7 pour une semaine, 1 à `periodDays` (31 au plus) pour le mois. */
export function dayCountOptions(period: MaxDaysPeriod | null, periodDays = 31): number[] {
  const max = period === "week" ? 7 : Math.min(31, Math.max(1, periodDays));
  return Array.from({ length: max }, (_, i) => i + 1);
}

/** Dimanches possibles : 0 à nombre de dimanches du calendrier de la période (5 en novembre 2026). */
export function sundayOptions(nSundays: number): number[] { return Array.from({ length: Math.max(0, nSundays) + 1 }, (_, i) => i); }

export function validateDraft(d: RulesDraft, nSundays = 5, periodDays = 31): string[] {
  const errs: string[] = [];
  if ((d.max_days_count === null) !== (d.max_days_period === null)) errs.push("Choisissez à la fois le nombre de jours et la période (ou « Pas de préférence » dans les deux).");
  if (d.max_days_period === "week" && (d.max_days_count ?? 0) > 7) errs.push("Une semaine compte au plus 7 jours.");
  if (d.max_days_period === "month" && (d.max_days_count ?? 0) > Math.min(31, periodDays)) errs.push(`Cette période compte ${Math.min(31, periodDays)} jours.`);
  if (d.time_pref_strict && d.time_pref === null) errs.push("Choisissez une préférence horaire avant de la rendre stricte.");
  if (d.sunday_quota !== null && (d.sunday_quota < 0 || d.sunday_quota > nSundays)) errs.push(`Cette période compte ${nSundays} dimanche(s).`);
  errs.push(...validateDays(d.min_days_month, d.max_days_month, periodDays));
  return errs;
}

/** « Pas de préférence » (valeur vide) <-> null. */
export const parseNum = (v: string): number | null => (v === NO_PREF ? null : Number(v));

export function summarize(d: RulesDraft): string[] {
  const out: string[] = [];
  if (d.min_days_month != null) out.push(`Min ${d.min_days_month} j / mois`);
  if (d.max_days_month != null) out.push(`Max ${d.max_days_month} j / mois`);
  if (d.max_days_count !== null && d.max_days_period) out.push(`Max ${d.max_days_count} j / ${d.max_days_period === "week" ? "semaine" : "mois"}`);
  if (d.time_pref) out.push(`${TIME_PREF_LABEL[d.time_pref]} ${d.time_pref_strict ? "(strict)" : "(souple)"}`);
  if (d.sunday_quota !== null) out.push(`${d.sunday_quota} dimanche${d.sunday_quota > 1 ? "s" : ""} ${d.sunday_mode === "exact" ? "(exact)" : "(max)"}`);
  return out;
}
