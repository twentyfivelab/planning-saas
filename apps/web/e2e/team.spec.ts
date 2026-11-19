import { expect, test, type Page } from "@playwright/test";
import { API, getJson as j } from "./api";

// Ajout et suppression de collaborateurs, plannings qui conservent leurs paramètres, détail des incompatibilités, suivi du calcul.
// Tenant de test dédié uniquement (voir global-setup.ts).
test.skip(!process.env.E2E_EMAIL, "E2E_EMAIL non défini");
test.describe.configure({ mode: "serial" });

type Emp = { id: string; code: string; name: string; brands: Record<string, string>; allocation_weight: number; active: boolean; deleted_at?: string | null } & Record<string, unknown>;
const csrf = async (page: Page) => (await j(page, "/auth/me")).csrf_token as string;
const suffix = () => Array.from({ length: 5 }, () => "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[Math.floor(Math.random() * 26)]).join("");
let novId = "";

async function sched(page: Page, pid: string) {
  return (await j(page, `/periods/${pid}/schedule`)).assignments as { assignment_id: string; employee_id: string; employee: string; day: string; start: string; end: string }[];
}

test.beforeAll(async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: "e2e/.auth/state.json" });
  const page = await ctx.newPage();
  novId = ((await j(page, "/periods")) as { id: string; start_date: string }[]).find((p) => p.start_date === "2026-11-01")!.id;
  if (!(await sched(page, novId)).length) {
    await page.request.post(`${API}/periods/${novId}/runs`, { headers: { "X-CSRF-Token": await csrf(page), "Idempotency-Key": `t-${Date.now()}` }, data: { time_limit_s: 30 } });
    await expect.poll(async () => (await j(page, "/runs"))[0].status, { timeout: 60_000 }).toBe("termine");
  }
  await ctx.close();
});

test("ajout d'un collaborateur : fiche complète, message seul, doublon vérifié, puis suppression confirmée", async ({ page }) => {
  const last = `ESSAI-${suffix()}`;
  const full = `Camille ${last}`;
  await page.goto("/employees"); await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "Ajouter un collaborateur" }).click();
  const form = page.getByTestId("employee-add-form");
  await form.getByLabel("Prénom *").fill("Camille");
  await form.getByLabel("Nom *", { exact: true }).fill(last);
  await form.getByLabel("Date de naissance").fill("1995-06-01");
  await form.getByLabel("Rue et numéro").fill("Rue de test 1");
  await form.getByLabel("Code postal").fill("1200");
  await form.getByLabel("Ville").fill("Genève");
  await form.getByLabel("Pays").fill("Suisse");
  await form.getByLabel("Heures par mois").fill("120");
  await form.getByRole("checkbox", { name: "Lundi" }).first().check();
  await form.getByLabel("Préférence horaire", { exact: true }).selectOption("matin");
  await form.getByLabel("Minimum de jours par mois").selectOption("12");
  await form.getByLabel("Maximum de jours par mois").selectOption("10");
  await form.getByRole("button", { name: "Ajouter le collaborateur" }).click();
  await expect(form.getByText("Le minimum (12 jours) dépasse le maximum (10 jours)")).toBeVisible(); // jamais enregistré en silence
  await form.getByLabel("Maximum de jours par mois").selectOption("18");
  await form.getByRole("button", { name: "Ajouter le collaborateur" }).click();
  await expect(page.getByRole("status").filter({ hasText: `Le collaborateur ${full} a été ajouté avec succès.` })).toBeVisible();
  await expect(page.getByTestId("employee-add-form")).toBeHidden();
  const e = ((await j(page, "/employees")) as Emp[]).find((x) => x.name === full)!;
  // nouveau collaborateur : la fenêtre d'intégration propose les plannings existants concernés ; « Décider plus tard » ne modifie rien
  if (((await j(page, `/integrations/candidates?employee_id=${e.id}`)) as { periods: unknown[] }).periods.length) {
    await page.getByTestId("integration-modal").getByRole("button", { name: "Décider plus tard" }).click();
    await expect(page.getByTestId("integration-modal")).toBeHidden();
  }
  expect(e).toMatchObject({ first_name: "Camille", last_name: last, address_city: "Genève", min_days_month: 12, max_days_month: 18, time_pref: "matin" });
  // doublon : même prénom et même nom -> confirmation demandée, rien n'est créé
  await page.getByRole("button", { name: "Ajouter un collaborateur" }).click();
  await form.getByLabel("Prénom *").fill("Camille"); await form.getByLabel("Nom *", { exact: true }).fill(last);
  await form.getByRole("button", { name: "Ajouter le collaborateur" }).click();
  await expect(form.getByTestId("duplicate-matches")).toContainText("même prénom et même nom");
  await expect(form.getByRole("button", { name: /autre personne : ajouter quand même/ })).toBeVisible();
  await form.getByRole("button", { name: "Annuler" }).click();
  expect(((await j(page, "/employees")) as Emp[]).filter((x) => x.name === full)).toHaveLength(1);
  // suppression : question exacte, Annuler ne fait rien, Supprimer retire le collaborateur
  const row = page.getByRole("row", { name: new RegExp(`^${full} `) });
  await row.getByRole("button", { name: "Supprimer" }).click();
  const dlg = page.getByRole("dialog", { name: `Êtes-vous sûr de vouloir supprimer le collaborateur ${full} ?` });
  await expect(dlg).toBeVisible();
  await expect(dlg.getByRole("button")).toHaveText(["Annuler", "Supprimer"]);
  await dlg.getByRole("button", { name: "Annuler" }).click();
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Supprimer" }).click();
  await dlg.getByRole("button", { name: "Supprimer" }).click();
  await expect(page.getByRole("status").filter({ hasText: `Le collaborateur ${full} a été supprimé avec succès.` })).toBeVisible();
  await expect(row).toBeHidden();
  await expect(page.getByTestId("deleted-employees")).toContainText(full);
  expect(((await j(page, "/employees")) as Emp[]).some((x) => x.name === full)).toBe(false);
  expect(((await j(page, "/employees?include_deleted=true")) as Emp[]).find((x) => x.name === full)!.deleted_at).toBeTruthy();
});

test("fiche modifiée : novembre garde ses paramètres ; détail de ce que donnerait l'application des paramètres actuels", async ({ page }) => {
  const plan = await sched(page, novId);
  const emps = (await j(page, "/employees")) as Emp[];
  const target = emps.find((x) => plan.some((a) => a.employee_id === x.id))!;
  const token = await csrf(page);
  const put = (over: Record<string, unknown>) => page.request.put(`${API}/employees/${target.id}`, { headers: { "X-CSRF-Token": token }, data: { code: target.code, name: target.name, ...over } });
  const before = ((await j(page, `/periods/${novId}/compatibility`)) as { items: unknown[] }).items.length;
  try {
    expect((await put({ brands: {} })).ok()).toBe(true); // changement pour les prochains mois : plus aucune marque
    expect(((await j(page, `/periods/${novId}/compatibility`)) as { items: unknown[] }).items).toHaveLength(before); // novembre inchangé
    await page.goto("/employees"); await page.waitForLoadState("networkidle");
    await page.getByRole("row", { name: new RegExp(`^${target.name} `) }).getByRole("button", { name: "Fiche" }).click();
    const sheet = page.getByRole("dialog", { name: `Fiche — ${target.name}` });
    await sheet.getByLabel("Préférence horaire", { exact: true }).selectOption("soir");
    const impact = sheet.getByTestId("impact-list");
    await expect(impact).toContainText("Novembre 2026");
    await expect(impact).toContainText("si vous lui appliquez les paramètres actuels");
    await expect(sheet.getByText("Les plannings déjà créés conservent leurs paramètres")).toBeVisible();
    await impact.getByRole("button", { name: "Détail si appliqués" }).first().click();
    const detail = page.getByTestId("incompat-detail");
    await expect(detail.getByRole("heading", { name: "Contraintes obligatoires non respectées" })).toBeVisible();
    await expect(detail.getByRole("row").filter({ hasText: "Marques autorisées" }).first()).toContainText(target.name);
    await expect(detail.getByRole("row").filter({ hasText: "Marques autorisées" }).first()).toContainText(/\d{2}\/11\/2026/);
  } finally {
    expect((await put({ brands: target.brands, time_pref: null, time_pref_strict: false })).ok()).toBe(true);
  }
  expect(((await j(page, `/periods/${novId}/compatibility`)) as { items: unknown[] }).items).toHaveLength(before);
});

test("génération : durée maximale expliquée, choix des paramètres, temps écoulé et état du calcul", async ({ page }) => {
  await page.goto("/generate"); await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "Continuer", exact: true }).click();
  const help = page.getByTestId("time-limit-help");
  await expect(help).toContainText("C'est une limite, pas une durée fixe.");
  await expect(help).toContainText("si aucune solution n'a été trouvée, rien n'est enregistré");
  await expect(help).toContainText("n'est jamais enregistré ni présenté comme valide");
  const choice = page.getByTestId("params-choice");
  const mine = choice.getByRole("radio", { name: /Paramètres de ce planning/ });
  if (!(await mine.isChecked())) { // paramètres modifiés depuis la création : aucun choix présélectionné, la génération attend la décision
    await expect(page.getByRole("button", { name: "Générer automatiquement le planning" })).toBeDisabled();
    await mine.check();
  }
  await expect(mine).toBeChecked();
  await page.getByLabel("Durée maximale du calcul (secondes)").fill("12");
  await page.getByRole("button", { name: "Générer automatiquement le planning" }).click();
  await page.getByRole("button", { name: "Confirmer et lancer" }).click();
  await expect(page.getByTestId("run-progress")).toBeVisible();
  await expect(page.getByTestId("run-elapsed")).toContainText(/Temps écoulé depuis le début : \d+ s · durée maximale du calcul \(modèle et recherche\) : 12 s/);
  await expect(page.getByText(/Résultat :/)).toBeVisible({ timeout: 90_000 });
  const outcome = page.getByTestId("save-outcome"); // résultat d'enregistrement donné par le serveur, avec les temps mesurés
  await expect(outcome).toHaveAttribute("data-outcome", "replaced");
  // résultat en six blocs distincts : règles, couverture, budgets et volume, équité, shifts à compléter, état de l'optimisation
  const summary = page.getByTestId("generation-summary");
  for (const k of ["rules", "coverage", "budgets", "fairness", "remaining", "optimisation"]) await expect(summary.getByTestId(`summary-${k}`)).toBeVisible();
  await expect(summary.getByTestId("summary-rules")).toHaveAttribute("data-state", "ok");
  await expect(summary.getByTestId("summary-rules")).toContainText("contrôle indépendant");
  await expect(summary.getByTestId("summary-optimisation")).toContainText(/Meilleure solution prouvée|Planning valide et utilisable, mais optimisation non terminée/);
  await expect(summary.getByTestId("engine-priorities")).toContainText("Comment le moteur arbitre");
  await expect(outcome).toContainText(/Avant : \d+ affectation\(s\), version n° \d+ ; après : version n° \d+/);
  await expect(outcome.getByTestId("run-timing")).toContainText("(durée maximale 12 s pour ces deux étapes)");
  await expect(page.getByText(/Paramètres utilisés : ceux conservés par ce planning · plafond mensuel 176 h par collaborateur/)).toBeVisible();
});
