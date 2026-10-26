/** Libellés français des codes de diagnostic renvoyés par le solveur (le code brut reste affiché en second plan). */
export const ISSUE_TITLES: Record<string, string> = {
  CONTRACT_MISSING: "Contrats non renseignés", AVAILABILITY_INCOMPLETE: "Disponibilités incomplètes", LEAVES_MISSING: "Congés et absences non saisis",
  BRAND_REQUIREMENTS_MISSING: "Besoins de marque non définis", LEGAL_REVIEW: "Règles légales : validation requise", HYPOTHESIS: "Hypothèse non validée",
  NO_CANDIDATE: "Aucun candidat pour un shift", COMBINED_CONSTRAINTS: "Contraintes combinées", INFEASIBLE_CORE: "Besoins incompatibles",
};
export const issueTitle = (code: string) => ISSUE_TITLES[code] ?? code;
