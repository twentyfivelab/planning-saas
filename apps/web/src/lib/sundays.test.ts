import { describe, expect, it } from "vitest";
import { computeCounter, type SundayEmployee } from "./sundays";
import { dayCountOptions, parseNum, sundayOptions, summarize, validateDraft, type RulesDraft } from "./employeeRules";

const SUNDAYS = ["2026-11-01", "2026-11-08", "2026-11-15", "2026-11-22", "2026-11-29"];
const base = { total: 35, planned: 0, sundays: SUNDAYS };
const emp = (code: string, q: number | null = null, mode: "max" | "exact" = "exact"): SundayEmployee => ({ code, sunday_quota: q, sunday_mode: mode });

describe("compteur des dimanches (novembre 2026 : 7 × 5 = 35)", () => {
  it("part de 35 shifts, tous restant à attribuer", () => {
    const c = computeCounter(base, [emp("mila"), emp("abdu")]);
    expect(c).toMatchObject({ total: 35, reserved: 0, remaining: 35, planned: 0, unplanned: 35 });
  });
  it("2 dimanches à Mila : 33 restants ; puis 3 à Abdu : 30 restants", () => {
    expect(computeCounter(base, [emp("mila", 2), emp("abdu")]).remaining).toBe(33);
    const c = computeCounter(base, [emp("mila", 2), emp("abdu", 3)]);
    expect(c.reserved).toBe(5); expect(c.remaining).toBe(30);
  });
  it("un quota « maximum » compte aussi comme attribué ; planifié et réservé ne sont pas confondus", () => {
    const c = computeCounter({ ...base, planned: 35 }, [emp("mila", 2), emp("sabrina", 4, "max")]);
    expect(c).toMatchObject({ reserved: 6, reservedExact: 2, reservedMax: 4, remaining: 29, planned: 35, unplanned: 0 });
  });
  it("modifier un quota met le restant à jour immédiatement", () => {
    expect(computeCounter(base, [emp("mila", 2, "max")]).remaining).toBe(33);
    expect(computeCounter(base, [emp("mila", 3, "max")]).remaining).toBe(32);
    expect(computeCounter(base, [emp("mila", null)]).remaining).toBe(35);
  });
  it("0 dimanche ne réserve rien ; un quota au-delà des 5 dimanches est plafonné", () => {
    expect(computeCounter(base, [emp("a", 0)]).reserved).toBe(0);
    expect(computeCounter(base, [emp("a", 9)]).reserved).toBe(5);
  });
  it("alerte d'avertissement quand les quotas ne peuvent pas couvrir les 35 shifts, information sinon", () => {
    const all = Array.from({ length: 6 }, (_, i) => emp(`e${i}`, 5));
    const w = computeCounter(base, all);
    expect(w.alerts[0]).toMatchObject({ level: "warning" }); expect(w.alerts[0].text).toContain("5 shift(s) du dimanche ne peuvent être couverts");
    const i = computeCounter(base, [emp("a", 2), emp("b")]);
    expect(i.alerts[0].level).toBe("info"); expect(i.alerts[0].text).toContain("33 shift(s) du dimanche restent à distribuer");
  });
  it("shifts non planifiés signalés après un calcul", () => {
    expect(computeCounter({ ...base, planned: 30 }, [emp("a")]).alerts.some((a) => a.text.includes("5 shift(s) du dimanche non planifié(s)"))).toBe(true);
  });
});

describe("paramètres de la fiche collaborateur", () => {
  const empty: RulesDraft = { max_days_count: null, max_days_period: null, time_pref: null, time_pref_strict: false, sunday_quota: null, sunday_mode: "max" };
  it("options : 1–7 par semaine, 1–31 par mois (selon la période), dimanches 0–5", () => {
    expect(dayCountOptions("week")).toEqual([1, 2, 3, 4, 5, 6, 7]);
    expect(dayCountOptions("month", 30)).toHaveLength(30); expect(dayCountOptions("month", 99)).toHaveLength(31);
    expect(sundayOptions(5)).toEqual([0, 1, 2, 3, 4, 5]);
  });
  it("« Pas de préférence » vaut null", () => { expect(parseNum("")).toBeNull(); expect(parseNum("4")).toBe(4); });
  it("validation : nombre et période vont ensemble, strict exige une préférence, bornes", () => {
    expect(validateDraft(empty)).toEqual([]);
    expect(validateDraft({ ...empty, max_days_count: 4 })).toHaveLength(1);
    expect(validateDraft({ ...empty, max_days_period: "week" })).toHaveLength(1);
    expect(validateDraft({ ...empty, max_days_count: 8, max_days_period: "week" })).toHaveLength(1);
    expect(validateDraft({ ...empty, time_pref_strict: true })).toHaveLength(1);
    expect(validateDraft({ ...empty, sunday_quota: 6 })).toHaveLength(1);
    expect(validateDraft({ ...empty, max_days_count: 4, max_days_period: "week", time_pref: "soir", sunday_quota: 2, sunday_mode: "exact" })).toEqual([]);
  });
  it("résumé lisible (Zaki 4/semaine, Sahra 20/mois)", () => {
    expect(summarize({ ...empty, max_days_count: 4, max_days_period: "week" })).toEqual(["Max 4 j / semaine"]);
    expect(summarize({ ...empty, max_days_count: 20, max_days_period: "month", time_pref: "matin", time_pref_strict: true, sunday_quota: 1, sunday_mode: "exact" }))
      .toEqual(["Max 20 j / mois", "Matin (strict)", "1 dimanche (exact)"]);
  });
});
