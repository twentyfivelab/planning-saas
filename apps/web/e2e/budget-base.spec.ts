import { expect, test, type Page } from "@playwright/test";
import { API, getJson as j } from "./api";

// Budget du mois prérempli depuis le budget de base : 88 h affichées, ajustées à 96 h avec les flèches, total recalculé, conservé après
// actualisation, sans effet sur les autres mois. Mois dédié (octobre 2027) ; données remises en l'état.
test.skip(!process.env.E2E_EMAIL || !process.env.E2E_PASSWORD, "E2E_EMAIL / E2E_PASSWORD non définis");

const csrf = async (page: Page) => (await j(page, "/auth/me")).csrf_token as string;
type B = { code: string; budget_minutes: number | null; base_minutes: number | null; active: boolean };

test("88 h préremplies, ajustées à 96 h, conservées après actualisation ; autres mois intacts", async ({ page }) => {
  const token = await csrf(page);
  const H = { "X-CSRF-Token": token };
  const brand = ((await j(page, "/catalog")) as { brands: { code: string; base_budget_minutes: number | null }[] }).brands.find((b) => b.code === "Nuxe")!;
  const baseBefore = brand.base_budget_minutes;
  const nov = ((await j(page, "/periods")) as { id: string; start_date: string }[]).find((p) => p.start_date === "2026-11-01")!.id;
  const novBefore = ((await j(page, `/periods/${nov}/brands`)) as B[]).map((b) => [b.code, b.budget_minutes]);
  expect((await page.request.patch(`${API}/catalog/brands/Nuxe`, { headers: H, data: { base_budget_hours: 88 } })).status()).toBe(200);
  let pid = "";
  try {
    pid = (await (await page.request.post(`${API}/periods/ensure`, { headers: H, data: { year: 2027, month: 10 } })).json()).id;
    // précondition vérifiée plutôt que supposée : aucun budget Nuxe déjà saisi pour octobre 2027 (sinon il serait conservé, à juste titre)
    expect(((await j(page, `/periods/${pid}/brands`)) as B[]).find((b) => b.code === "Nuxe")!.budget_minutes, "budget d'octobre 2027 laissé par une exécution précédente").toBe(88 * 60);
    await page.goto(`/plannings/new?period=${pid}`); await page.waitForLoadState("networkidle");
    await page.getByRole("list", { name: "Étapes de création" }).getByRole("button", { name: /Marques et sites$/ }).click();
    const field = page.getByLabel("Budget Nuxe (heures)");
    await expect(field).toHaveValue("88"); // prérempli depuis le budget de base
    await expect(page.getByTestId("base-Nuxe")).toHaveText("Budget de base : 88 h");
    const card = page.getByText(/^Budget total actif : /).first();
    const totalBefore = await card.textContent();
    await field.focus();
    for (let i = 0; i < 16; i++) await field.press("ArrowUp"); // petites flèches : +0,5 h à chaque pas
    await expect(field).toHaveValue("96");
    await expect(card).not.toHaveText(totalBefore!); // total recalculé immédiatement
    await expect.poll(async () => ((await j(page, `/periods/${pid}/brands`)) as B[]).find((b) => b.code === "Nuxe")!.budget_minutes).toBe(96 * 60);
    await page.reload(); await page.waitForLoadState("networkidle");
    await page.getByRole("list", { name: "Étapes de création" }).getByRole("button", { name: /Marques et sites$/ }).click();
    await expect(page.getByLabel("Budget Nuxe (heures)")).toHaveValue("96"); // jamais réécrasé par le préremplissage
    await expect(page.getByTestId("base-Nuxe")).toContainText("Ajusté pour ce mois · budget de base : 88 h");
    // « Revenir au budget de base » : confirmation avant de remplacer la valeur modifiée ; « Annuler » ne change rien
    await page.getByRole("button", { name: "Revenir au budget de base" }).click();
    const dlg = page.getByRole("dialog");
    await expect(dlg).toContainText("Revenir au budget de base pour Nuxe ?");
    await expect(dlg).toContainText("passera de 96 h à 88 h");
    await dlg.getByRole("button", { name: "Annuler" }).click();
    await expect(dlg).toBeHidden();
    await expect(page.getByLabel("Budget Nuxe (heures)")).toHaveValue("96");
    expect(((await j(page, `/periods/${pid}/brands`)) as B[]).find((b) => b.code === "Nuxe")!.budget_minutes).toBe(96 * 60);
    await page.getByRole("button", { name: "Revenir au budget de base" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Remplacer par 88 h" }).click();
    await expect(page.getByLabel("Budget Nuxe (heures)")).toHaveValue("88");
    await expect.poll(async () => ((await j(page, `/periods/${pid}/brands`)) as B[]).find((b) => b.code === "Nuxe")!.budget_minutes).toBe(88 * 60);
    await expect(page.getByTestId("base-Nuxe")).toHaveText("Budget de base : 88 h");
    // autres mois et budget de base inchangés
    expect(((await j(page, `/periods/${nov}/brands`)) as B[]).map((b) => [b.code, b.budget_minutes])).toEqual(novBefore);
    expect(((await j(page, "/catalog")) as { brands: { code: string; base_budget_minutes: number | null }[] }).brands.find((b) => b.code === "Nuxe")!.base_budget_minutes).toBe(88 * 60);
  } finally {
    await page.request.patch(`${API}/catalog/brands/Nuxe`, { headers: H, data: baseBefore === null ? { clear_base_budget: true } : { base_budget_hours: baseBefore / 60 } });
    // le budget du mois appartient au MOIS (il survit à la suppression d'un planning) : retiré explicitement pour la prochaine exécution
    if (pid) await page.request.put(`${API}/periods/${pid}/brands/Nuxe`, { headers: H, data: { clear_budget: true } });
    if (pid) await page.request.post(`${API}/periods/${pid}/delete`, { headers: H, data: { password: process.env.E2E_PASSWORD } });
  }
});
