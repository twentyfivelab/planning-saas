import { expect, test, type Page } from "@playwright/test";
import { API, getJson as j } from "./api";

// Suppression d'un planning généré : fenêtre d'aperçu, Annuler, mauvais mot de passe, accès non autorisé, suppression réussie, trace
// persistante. Mois dédié (juin 2027) : aucun autre test n'en dépend.
test.skip(!process.env.E2E_EMAIL || !process.env.E2E_PASSWORD, "E2E_EMAIL / E2E_PASSWORD non définis");
test.describe.configure({ mode: "serial" });

const csrf = async (page: Page) => (await j(page, "/auth/me")).csrf_token as string;
let pid = "";

test.beforeAll(async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: "e2e/.auth/state.json" });
  const page = await ctx.newPage();
  const token = await csrf(page);
  const r = await page.request.post(`${API}/periods/ensure`, { headers: { "X-CSRF-Token": token }, data: { year: 2027, month: 6 } });
  pid = (await r.json()).id;
  if (!((await j(page, `/periods/${pid}/schedule`)).assignments as unknown[]).length) {
    const run = await page.request.post(`${API}/periods/${pid}/runs`, { headers: { "X-CSRF-Token": token, "Idempotency-Key": `del-${Date.now()}` }, data: { time_limit_s: 10 } });
    expect(run.status(), await run.text()).toBe(202);
    await expect.poll(async () => ((await j(page, `/periods/${pid}/schedule`)).assignments as unknown[]).length, { timeout: 90_000 }).toBeGreaterThan(0);
  }
  await ctx.close();
});

async function openJune(page: Page) {
  await page.goto("/planning");
  await page.evaluate(() => { try { localStorage.setItem("planning:month", "2027-06"); } catch { /* ignoré */ } });
  await page.reload(); await page.waitForLoadState("networkidle");
}

test("fenêtre d'aperçu, Annuler et mot de passe incorrect : le planning reste intact", async ({ page }) => {
  const n = ((await j(page, `/periods/${pid}/schedule`)).assignments as unknown[]).length;
  await openJune(page);
  await page.getByRole("button", { name: "Supprimer ce planning" }).click();
  const dlg = page.getByRole("dialog", { name: "Supprimer le planning de juin 2027 ?" });
  await expect(dlg).toContainText("Ce planning sera retiré des plannings actifs. Cette action sera enregistrée dans l'historique avec votre identité.");
  const sum = dlg.getByTestId("delete-summary");
  await expect(sum).toContainText("Juin 2027");
  await expect(sum).toContainText(String(n));
  await expect(sum).toContainText("Versions associées");
  await expect(dlg.getByRole("button", { name: "Confirmer la suppression" })).toBeDisabled(); // mot de passe requis
  await dlg.getByRole("button", { name: "Annuler" }).click();
  await expect(dlg).toBeHidden();
  expect(((await j(page, "/periods")) as { id: string }[]).some((p) => p.id === pid)).toBe(true);
  // mauvais mot de passe : erreur affichée, rien de supprimé, champ vidé
  await page.getByRole("button", { name: "Supprimer ce planning" }).click();
  await dlg.getByLabel("Mot de passe de votre compte").fill("pas-le-bon-mot-de-passe");
  await dlg.getByRole("button", { name: "Confirmer la suppression" }).click();
  await expect(dlg.getByTestId("delete-error")).toHaveText("Mot de passe incorrect. Le planning n'a pas été modifié.");
  await expect(dlg.getByLabel("Mot de passe de votre compte")).toHaveValue("");
  expect(((await j(page, `/periods/${pid}/schedule`)).assignments as unknown[]).length).toBe(n);
});

test.describe("accès non autorisé", () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  test("un planificateur ne voit pas l'action et le serveur refuse", async ({ page }) => {
    const r = await page.request.post(`${API}/auth/login`, { data: { email: (process.env.E2E_EMAIL ?? "").replace(/^[^@]+/, "planner"), password: process.env.E2E_PASSWORD } });
    test.skip(r.status() !== 200, "compte planificateur absent");
    await openJune(page);
    await expect(page.getByRole("button", { name: "Supprimer ce planning" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^Options de / })).toHaveCount(0); // ni le menu « ⋯ » du menu latéral
    const token = (await j(page, "/auth/me")).csrf_token as string;
    const del = await page.request.post(`${API}/periods/${pid}/delete`, { headers: { "X-CSRF-Token": token }, data: { password: process.env.E2E_PASSWORD } });
    expect(del.status()).toBe(403);
  });
});

test("suppression réussie : message, planning retiré, trace dans l'historique après actualisation", async ({ page }) => {
  const me = (await j(page, "/auth/me")) as { name: string; id: string };
  const n = ((await j(page, `/periods/${pid}/schedule`)).assignments as unknown[]).length;
  await openJune(page);
  await page.getByRole("button", { name: "Supprimer ce planning" }).click();
  const dlg = page.getByRole("dialog", { name: "Supprimer le planning de juin 2027 ?" });
  await dlg.getByLabel("Mot de passe de votre compte").fill(process.env.E2E_PASSWORD!);
  await dlg.getByRole("button", { name: "Confirmer la suppression" }).click();
  await expect(page.getByTestId("deleted-message")).toBeVisible();
  await expect(page.getByText("Le planning de juin 2027 a été supprimé avec succès.").first()).toBeVisible();
  expect(((await j(page, "/periods")) as { id: string }[]).some((p) => p.id === pid)).toBe(false);
  expect((await page.request.get(`${API}/periods/${pid}/schedule`)).status()).toBe(404);
  await page.goto("/history?kind=deletion"); await page.waitForLoadState("networkidle");
  const ev = page.getByTestId("history-event").filter({ hasText: "juin 2027" }).first();
  await expect(ev).toContainText("Suppression d'un planning");
  await expect(ev).toContainText(`${n} affectation(s)`);
  await expect(ev).toContainText(`Supprimé par ${me.name} (compte ${me.id})`);
  await page.reload(); await page.waitForLoadState("networkidle");
  await expect(page.getByTestId("history-event").filter({ hasText: "juin 2027" }).first()).toBeVisible(); // persiste
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
});

test("après suppression : nouveau planning du même mois, distinct, l'ancien reste supprimé avec son historique", async ({ page }) => {
  const token = await csrf(page);
  const fresh = await (await page.request.post(`${API}/periods/ensure`, { headers: { "X-CSRF-Token": token }, data: { year: 2027, month: 6 } })).json();
  expect(fresh.id).not.toBe(pid);
  const run = await page.request.post(`${API}/periods/${fresh.id}/runs`, { headers: { "X-CSRF-Token": token, "Idempotency-Key": `regen-${Date.now()}` }, data: { time_limit_s: 10 } });
  expect(run.status()).toBe(202);
  await expect.poll(async () => ((await j(page, `/periods/${fresh.id}/schedule`)).assignments as unknown[]).length, { timeout: 90_000 }).toBeGreaterThan(0);
  expect((await page.request.get(`${API}/periods/${pid}/schedule`)).status()).toBe(404); // l'ancien n'est pas réactivé
  await openJune(page);
  await expect(page.getByRole("button", { name: "Supprimer ce planning" })).toBeVisible(); // le nouveau planning est actif
  await expect(page.locator(".shift").first()).toBeVisible();
  await page.goto("/history?kind=deletion"); await page.waitForLoadState("networkidle");
  await expect(page.getByTestId("history-event").filter({ hasText: "juin 2027" }).first()).toContainText("Planning : Juin 2027 (planning supprimé le ");
  pid = fresh.id; // pour une exécution suivante du fichier
});

test("menu latéral : supprimer un brouillon jamais généré, le mois disparaît, redirection, trace", async ({ page }) => {
  const token = await csrf(page);
  const draft = await (await page.request.post(`${API}/periods/ensure`, { headers: { "X-CSRF-Token": token }, data: { year: 2027, month: 8 } })).json();
  await page.goto("/planning");
  await page.evaluate(() => { try { localStorage.setItem("planning:month", "2027-08"); } catch { /* ignoré */ } }); // le brouillon est consulté
  await page.reload(); await page.waitForLoadState("networkidle");
  const nav = page.getByRole("navigation", { name: "Navigation principale" });
  const row = nav.getByTestId("period-row").filter({ hasText: "Août 2027" });
  await expect(row).toContainText("Brouillon");
  await row.getByRole("button", { name: "Options de Août 2027" }).click();
  await row.getByRole("menuitem", { name: "Supprimer ce planning" }).click();
  const dlg = page.getByRole("dialog", { name: "Supprimer le planning de août 2027 ?" });
  await expect(dlg.getByTestId("delete-summary")).toContainText("Brouillon");
  await dlg.getByRole("button", { name: "Annuler" }).click(); // annulation : rien ne change
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Options de Août 2027" }).click();
  await row.getByRole("menuitem", { name: "Supprimer ce planning" }).click();
  await dlg.getByLabel("Mot de passe de votre compte").fill(process.env.E2E_PASSWORD!);
  await dlg.getByRole("button", { name: "Confirmer la suppression" }).click();
  await expect(page.getByText("Le planning de août 2027 a été supprimé avec succès.").first()).toBeVisible();
  await expect(nav.getByTestId("period-row").filter({ hasText: "Août 2027" })).toHaveCount(0); // disparaît immédiatement du menu
  await expect(page).toHaveURL(/\/planning$/);
  expect(await page.evaluate(() => localStorage.getItem("planning:month"))).not.toBe("2027-08"); // redirigé vers un autre mois
  expect(((await j(page, "/periods")) as { id: string }[]).some((p) => p.id === draft.id)).toBe(false);
  // un ancien onglet qui enregistre encore : refusé, rien de recréé
  expect((await page.request.put(`${API}/periods/${draft.id}/roster`, { headers: { "X-CSRF-Token": token }, data: { employees: [] } })).status()).toBe(404);
  expect(((await j(page, "/periods")) as { start_date: string }[]).some((p) => p.start_date === "2027-08-01")).toBe(false);
  // trace : y compris pour un brouillon sans affectation
  const me = (await j(page, "/auth/me")) as { name: string; id: string };
  await page.goto("/history?kind=deletion"); await page.waitForLoadState("networkidle");
  const ev = page.getByTestId("history-event").filter({ hasText: "août 2027" }).first();
  await expect(ev).toContainText("(brouillon) supprimé : 0 affectation(s)");
  await expect(ev).toContainText(`Supprimé par ${me.name} (compte ${me.id})`);
});

test("menu latéral sur mobile : le bouton « ⋯ » est accessible", async ({ page }) => {
  const token = await csrf(page);
  const draft = await (await page.request.post(`${API}/periods/ensure`, { headers: { "X-CSRF-Token": token }, data: { year: 2027, month: 9 } })).json();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/"); await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "Menu" }).click();
  const row = page.getByRole("navigation", { name: "Navigation principale" }).getByTestId("period-row").filter({ hasText: "Septembre 2027" });
  await row.scrollIntoViewIfNeeded();
  await row.getByRole("button", { name: "Options de Septembre 2027" }).click();
  await row.getByRole("menuitem", { name: "Supprimer ce planning" }).click();
  const dlg = page.getByRole("dialog", { name: "Supprimer le planning de septembre 2027 ?" });
  await dlg.getByLabel("Mot de passe de votre compte").fill(process.env.E2E_PASSWORD!);
  await dlg.getByRole("button", { name: "Confirmer la suppression" }).click();
  await expect(page.getByText("Le planning de septembre 2027 a été supprimé avec succès.").first()).toBeVisible();
  expect(((await j(page, "/periods")) as { id: string }[]).some((p) => p.id === draft.id)).toBe(false);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
});
