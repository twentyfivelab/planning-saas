import { expect, test, type Page } from "@playwright/test";
import { API, getJson as j } from "./api";

// Brouillon supprimé depuis un autre onglet : l'onglet resté ouvert n'enregistre plus rien et le dit. Mois dédié (avril 2028), créé puis
// supprimé par le test ; aucun autre test n'en dépend.
test.skip(!process.env.E2E_EMAIL || !process.env.E2E_PASSWORD, "E2E_EMAIL / E2E_PASSWORD non définis");
test.describe.configure({ mode: "serial" });

const csrf = async (page: Page) => (await j(page, "/auth/me")).csrf_token as string;
const draft = async (page: Page) => (await (await page.request.post(`${API}/periods/ensure`, { headers: { "X-CSRF-Token": await csrf(page) }, data: { year: 2028, month: 4 } })).json()).id as string;
const april2028 = async (page: Page) => ((await j(page, "/periods")) as { id: string; start_date: string }[]).filter((p) => p.start_date === "2028-04-01");

async function openRoster(page: Page, pid: string) {
  await page.goto(`/plannings/new?period=${pid}`); await page.waitForLoadState("networkidle");
  await page.getByRole("list", { name: "Étapes de création" }).getByRole("button", { name: /Collaborateurs$/ }).click();
  await expect(page.getByRole("heading", { name: "Collaborateurs du mois" })).toBeVisible();
}

test("onglet sans temps réel : la suppression est découverte à l'enregistrement, qui s'arrête et le dit ; plus aucun envoi", async ({ page, browser }) => {
  const pid = await draft(page);
  // l'onglet A n'apprend rien par le temps réel ni par l'empreinte : seule sa tentative d'enregistrement révèle la suppression
  await page.route("**/events", (r) => r.abort()); await page.route("**/revision", (r) => r.abort());
  await openRoster(page, pid);
  const status = page.locator("[data-save-confirmed]").first();
  const box = page.getByRole("list", { name: "Effectif du mois" }).getByRole("checkbox").first();
  const initial = await box.isChecked();
  await box.setChecked(!initial);
  await expect(status).toHaveAttribute("data-save-state", "saved", { timeout: 15_000 });
  // onglet B : suppression confirmée par le mot de passe
  const ctxB = await browser.newContext({ storageState: "e2e/.auth/state.json" });
  const b = await ctxB.newPage();
  const del = await b.request.post(`${API}/periods/${pid}/delete`, { headers: { "X-CSRF-Token": await csrf(b) }, data: { password: process.env.E2E_PASSWORD } });
  expect(del.status(), await del.text()).toBe(200);
  await ctxB.close();
  const puts: string[] = [];
  page.on("request", (r) => { if (r.method() === "PUT" && r.url().includes("/roster")) puts.push(r.url()); });
  await box.setChecked(initial);
  await expect(status).toHaveAttribute("data-save-state", "stopped", { timeout: 15_000 });
  await expect(status).toContainText("Enregistrement arrêté");
  await expect(status.getByRole("button", { name: "Réessayer" })).toHaveCount(0); // erreur définitive : pas de « Réessayer »
  const sent = puts.length;
  expect(sent).toBe(1); // une seule tentative, refusée par le serveur
  await box.setChecked(!initial); await page.waitForTimeout(1500); // nouvelle modification : plus rien n'est envoyé
  expect(puts.length).toBe(sent);
  expect(await april2028(page)).toEqual([]); // rien n'a été recréé
});

test("onglet avec temps réel : le brouillon supprimé ailleurs est signalé sans action de l'utilisateur", async ({ page, browser }) => {
  const pid = await draft(page);
  await openRoster(page, pid);
  const ctxB = await browser.newContext({ storageState: "e2e/.auth/state.json" });
  const b = await ctxB.newPage();
  expect((await b.request.post(`${API}/periods/${pid}/delete`, { headers: { "X-CSRF-Token": await csrf(b) }, data: { password: process.env.E2E_PASSWORD } })).status()).toBe(200);
  await ctxB.close();
  await expect(page.getByTestId("wizard-deleted")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("list", { name: "Effectif du mois" })).toHaveCount(0); // plus de formulaire : rien ne peut être enregistré
  expect(await april2028(page)).toEqual([]);
});
