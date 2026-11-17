import { ApiError } from "./api";

/** Message lisible d'une erreur de l'API (détail texte ou objet structuré). */
export function errText(e: unknown, fallback = "Opération impossible"): string {
  if (e instanceof ApiError) {
    if (typeof e.detail === "string") return e.detail;
    const d = e.detail as { message?: unknown } | Array<{ msg?: string }> | null;
    if (Array.isArray(d)) return d.map((x) => x.msg).filter(Boolean).join(" ; ") || fallback;
    if (d && typeof d.message === "string") return d.message;
  }
  return e instanceof Error ? e.message : fallback;
}
export const errCode = (e: unknown): string | null => {
  if (e instanceof ApiError && typeof e.detail === "object" && e.detail !== null) { const c = (e.detail as { code?: unknown }).code; return typeof c === "string" ? c : null; }
  return null;
};

/** Heures, minutes omises si nulles. */
export const fmtH = (min: number | null | undefined) => {
  if (min === null || min === undefined) return "—";
  const sign = min < 0 ? "−" : ""; const a = Math.abs(Math.round(min)); const h = Math.floor(a / 60); const m = a % 60;
  return `${sign}${h} h${m ? ` ${String(m).padStart(2, "0")}` : ""}`;
};
/** Montant en francs à partir de centimes ; jamais de valeur inventée : « Non renseigné » si inconnu. */
export const fmtCHF = (c: number | null | undefined) => (c === null || c === undefined ? null : `${(c / 100).toLocaleString("fr-CH", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} CHF`);
export const rateInput = (c: number | null | undefined) => (c === null || c === undefined ? "" : String(c / 100));
export const parseRate = (v: FormDataEntryValue | null): number | null => { const s = String(v ?? "").trim().replace(",", "."); if (!s) return null; const n = Number(s); return Number.isFinite(n) && n >= 0 ? Math.round(n * 100) : null; };

export type RunStatus = "en_attente" | "en_cours" | "termine" | "annule" | "erreur";
export const STATUS_RESULT: Record<string, string> = { optimal: "Optimum prouvé", faisable: "Solution valide (optimalité non prouvée)", partiellement_couvert: "Solution partielle", infaisable: "Problème impossible", interrompu: "Calcul interrompu ou expiré" };
export const resultLabel = (s: string | null | undefined, proved?: boolean) => {
  if (!s) return "—";
  if (s === "partiellement_couvert") return proved ? "Partielle : couverture maximale prouvée" : "Partielle (optimalité non prouvée)";
  return STATUS_RESULT[s] ?? s;
};
export const MISSION_STATUS: Record<string, { label: string; tone: "neutral" | "ok" | "warn" | "bad" | "info" }> = {
  draft: { label: "Brouillon", tone: "warn" }, confirmed: { label: "Confirmée", tone: "ok" }, cancelled: { label: "Annulée", tone: "bad" }, completed: { label: "Terminée", tone: "neutral" },
};
export const PRIORITY_LABEL: Record<number, string> = { 1: "Basse", 2: "Modérée", 3: "Normale", 4: "Haute", 5: "Critique" };
export const SKILL_CATEGORY: Record<string, string> = { competence: "Compétence", formation: "Formation", langue: "Langue", certification: "Certification", qualification: "Qualification" };
export const RELATION_SCOPE: Record<string, string> = { site_day: "même jour, même site", day: "même jour, tous sites", overlap: "horaires qui se chevauchent, tous sites" };
export const RELATION_LABEL: Record<string, string> = { opposite_shifts: "Horaires opposés", avoid_together: "À séparer", work_together: "Binôme (même jour, même site)", mentor: "Tuteur présent (même jour, même site)" };
export const WEEKDAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
export const SOFT_LABEL: Record<string, string> = { preferences: "Préférences individuelles", preferences_horaires: "Préférences horaires", renforts: "Shifts en renfort", quotas_dimanches_non_atteints: "Objectifs de dimanches non atteints", horaires_opposes: "Horaires opposés non respectés" };
