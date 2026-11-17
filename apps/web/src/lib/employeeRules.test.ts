import { describe, expect, it } from "vitest";
import { summarize, validateDays, validateDraft, type RulesDraft } from "./employeeRules";

const base: RulesDraft = { max_days_count: null, max_days_period: null, time_pref: null, time_pref_strict: false, sunday_quota: null, sunday_mode: "max" };

describe("jours minimum / maximum par mois", () => {
  it("« Pas de préférence » des deux côtés : aucune erreur", () => expect(validateDays(null, null, 30)).toEqual([]));
  it("chaque limite est indépendante", () => {
    expect(validateDays(12, null, 30)).toEqual([]);
    expect(validateDays(null, 20, 30)).toEqual([]);
  });
  it("le minimum ne dépasse pas le maximum", () => expect(validateDays(20, 10, 30)).toEqual(["Le minimum (20 jours) dépasse le maximum (10 jours) : corrigez l'un des deux."]));
  it("limité aux jours du mois", () => expect(validateDays(null, 31, 30)[0]).toContain("ce mois compte 30 jours"));
  it("contrôlé avec le reste de la fiche", () => expect(validateDraft({ ...base, min_days_month: 5, max_days_month: 4 })).toHaveLength(1));
  it("résumé lisible", () => expect(summarize({ ...base, min_days_month: 8, max_days_month: 18 })).toEqual(["Min 8 j / mois", "Max 18 j / mois"]));
});
