import { expect, test, type Page } from "@playwright/test";

// Prérequis : pile lancée + tenant de démonstration (E2E_EMAIL / E2E_PASSWORD, rôle planificateur ou supérieur).
test.skip(!process.env.E2E_EMAIL, "E2E_EMAIL non défini");
test.describe.configure({ mode: "serial" });
const API = process.env.API_URL ?? "http://localhost:8000";

type Emp = { id: string; code: string; name: string; brands: object; allocation_weight: number; active: boolean };
let periodId = "";

async function csrf(page: Page) { return (await (await page.request.get(`${API}/auth/me`)).json()).csrf_token as string; }
async function emps(page: Page): Promise<Record<string, Emp & Record<string, unknown>>> {
  return Object.fromEntries(((await (await page.request.get(`${API}/employees`)).json()) as (Emp & Record<string, unknown>)[]).map((e) => [e.code, e]));
}
async function resetAll(page: Page) {
  const token = await csrf(page);
  for (const e of Object.values(await emps(page))) {
    await page.request.put(`${API}/employees/${e.id}`, { headers: { "X-CSRF-Token": token }, data: { code: e.code, name: e.name, brands: e.brands, allocation_weight: e.allocation_weight, active: e.active,
      max_days_count: null, max_days_period: null, time_pref: null, time_pref_strict: false, sunday_quota: null, sunday_mode: "max" } });
  }
}
async function openSheet(page: Page, name: string) {
  await page.goto("/employees");
  const row = page.getByRole("row", { name: new RegExp(`^${name} `) });
  await row.getByRole("button", { name: "Fiche" }).click();
  const dlg = page.getByRole("dialog", { name: `Fiche — ${name}` });
  await expect(dlg).toBeVisible();
  return dlg;
}
const counterText = (page: Page) => page.getByRole("group", { name: "Compteur des dimanches" });

test.beforeAll(async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: "e2e/.auth/state.json" });
  const page = await ctx.newPage();
  periodId = (await (await page.request.get(`${API}/periods`)).json()).at(-1).id;
  await resetAll(page);
  const token = await csrf(page);
  await page.request.post(`${API}/periods/${periodId}/runs`, { headers: { "X-CSRF-Token": token, "Idempotency-Key": `e2e-${Date.now()}` }, data: { time_limit_s: 30 } });
  await expect.poll(async () => (await (await page.request.get(`${API}/runs`)).json())[0].status, { timeout: 60_000 }).toBe("termine");
  await ctx.close();
});
test.afterAll(async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: "e2e/.auth/state.json" });
  await resetAll(await ctx.newPage());
  await ctx.close();
});

test("accent #C61160 : bouton principal et navigation active", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/employees");
  const nav = page.getByRole("navigation", { name: "Navigation principale" }).locator('[aria-current="page"]');
  await expect(nav).toHaveCSS("background-color", "rgb(198, 17, 96)");
});

test("fiche : deux listes côte à côte, « Pas de préférence » par défaut, options 1–7 (semaine) et 1–30 (mois de novembre)", async ({ page }) => {
  const dlg = await openSheet(page, "Zaki");
  const count = dlg.getByLabel("Nombre de jours"), period = dlg.getByLabel("Période");
  await expect(count).toHaveValue(""); await expect(period).toHaveValue("");
  const [a, b] = [await count.boundingBox(), await period.boundingBox()];
  expect(Math.abs(a!.y - b!.y)).toBeLessThan(4); expect(b!.x).toBeGreaterThan(a!.x + a!.width - 2); // même ligne, côte à côte
  await period.selectOption("week");
  expect(await count.locator("option").allTextContents()).toEqual(["Pas de préférence", "1", "2", "3", "4", "5", "6", "7"]);
  await period.selectOption("month");
  const month = await count.locator("option").allTextContents();
  expect(month).toHaveLength(31); expect(month.at(-1)).toBe("30");
  expect(await dlg.getByLabel("Préférence horaire", { exact: true }).locator("option").allTextContents()).toEqual(["Pas de préférence", "Matin", "Middle shift", "Soir"]);
  expect(await dlg.getByLabel("Nombre de dimanches").locator("option").allTextContents()).toEqual(["Pas de préférence", "0 dimanche", "1 dimanche", "2 dimanches", "3 dimanches", "4 dimanches", "5 dimanches"]);
});

test("fiche : incohérence bloquée (nombre sans période) puis enregistrement persistant sans rechargement", async ({ page }) => {
  const dlg = await openSheet(page, "Zaki");
  await dlg.getByLabel("Nombre de jours").selectOption("4");
  await expect(dlg.getByText("Choisissez à la fois le nombre de jours et la période")).toBeVisible();
  await expect(dlg.getByRole("button", { name: "Enregistrer la fiche" })).toBeDisabled();
  await dlg.getByLabel("Période").selectOption("week");
  await page.evaluate(() => { (window as unknown as { __marker: number }).__marker = 1; });
  await dlg.getByRole("button", { name: "Enregistrer la fiche" }).click();
  await expect(page.getByText("Fiche de Zaki enregistrée.")).toBeVisible();
  const row = page.getByRole("row", { name: /^Zaki / });
  await expect(row.getByText("Max 4 j / semaine")).toBeVisible(); // mis à jour tout de suite
  expect(await page.evaluate(() => (window as unknown as { __marker?: number }).__marker)).toBe(1); // aucune navigation
  expect((await emps(page)).zaki).toMatchObject({ max_days_count: 4, max_days_period: "week" }); // et en base
  await page.reload();
  await expect(page.getByRole("row", { name: /^Zaki / }).getByText("Max 4 j / semaine")).toBeVisible();
});

test("fiche : préférence horaire souple/stricte (boutons désactivés sans préférence) et « Pas de préférence » efface", async ({ page }) => {
  const dlg = await openSheet(page, "Kristina");
  await expect(dlg.getByRole("radio", { name: /Stricte/ })).toBeDisabled();
  await dlg.getByLabel("Préférence horaire", { exact: true }).selectOption("soir");
  await expect(dlg.getByText("Fermetures : shifts commençant à partir de 12 h")).toBeVisible();
  await dlg.getByRole("radio", { name: /Stricte/ }).check();
  await dlg.getByRole("button", { name: "Enregistrer la fiche" }).click();
  await expect(page.getByRole("row", { name: /^Kristina / }).getByText("Soir (strict)")).toBeVisible();
  expect((await emps(page)).kristina).toMatchObject({ time_pref: "soir", time_pref_strict: true });
  const again = await openSheet(page, "Kristina");
  await again.getByLabel("Préférence horaire", { exact: true }).selectOption("");
  await expect(again.getByRole("radio", { name: /Stricte/ })).toBeDisabled();
  await again.getByRole("button", { name: "Enregistrer la fiche" }).click();
  await expect(page.getByRole("row", { name: /^Kristina / }).getByText("Pas de préférence")).toBeVisible();
  expect((await emps(page)).kristina).toMatchObject({ time_pref: null, time_pref_strict: false });
});

test("compteur des dimanches : 35 → 33 → 30 en direct, sans rechargement", async ({ page }) => {
  await page.goto("/employees");
  const counter = counterText(page);
  await expect(counter).toContainText("35"); await expect(counter.getByText("Restant à attribuer").locator("..")).toContainText("35");
  await expect(counter).toContainText("GVA3 15 · Pilar 10 · GVA9 10");
  await page.evaluate(() => { (window as unknown as { __marker: number }).__marker = 7; });
  const restant = () => counter.getByText("Restant à attribuer").locator("..").locator(".kpi-value");
  // brouillon : le compteur du formulaire est projeté avant l'enregistrement
  let dlg = await openSheet(page, "Mila");
  await page.evaluate(() => { (window as unknown as { __marker: number }).__marker = 7; });
  await dlg.getByLabel("Nombre de dimanches").selectOption("2");
  await dlg.getByRole("radio", { name: /Objectif exact/ }).check();
  await expect(dlg.getByText("33", { exact: true })).toBeVisible();
  await dlg.getByRole("button", { name: "Enregistrer la fiche" }).click();
  await expect(restant()).toHaveText("33");
  dlg = await openSheet(page, "Abdu");
  await page.evaluate(() => { (window as unknown as { __marker: number }).__marker = 7; });
  await dlg.getByLabel("Nombre de dimanches").selectOption("3");
  await dlg.getByRole("radio", { name: /Objectif exact/ }).check();
  await dlg.getByRole("button", { name: "Enregistrer la fiche" }).click();
  await expect(restant()).toHaveText("30");
  await expect(counter.getByText("Réservés aux collaborateurs").locator("..").locator(".kpi-value")).toHaveText("5");
  expect(await page.evaluate(() => (window as unknown as { __marker?: number }).__marker)).toBe(7);
  const s = await (await page.request.get(`${API}/periods/${periodId}/sunday-summary`)).json();
  expect(s).toMatchObject({ total: 35, reserved: 5, remaining_to_reserve: 30 });
  await expect(counter).toContainText("quotas « objectif exact »");
});

test("alertes : information tant qu'il reste des dimanches à distribuer, avertissement si les quotas ne peuvent pas tout couvrir", async ({ page }) => {
  await page.goto("/employees");
  await expect(page.getByText(/30 shift\(s\) du dimanche restent à distribuer/)).toBeVisible();
  const token = await csrf(page);
  for (const e of Object.values(await emps(page))) {
    await page.request.put(`${API}/employees/${e.id}`, { headers: { "X-CSRF-Token": token }, data: { code: e.code, name: e.name, brands: e.brands, allocation_weight: e.allocation_weight, active: e.active,
      max_days_count: null, max_days_period: null, time_pref: null, time_pref_strict: false, sunday_quota: 1, sunday_mode: "exact" } });
  }
  await page.reload();
  const n = Object.keys(await emps(page)).length;
  await expect(page.getByText(new RegExp(`${35 - n} shift\\(s\\) du dimanche ne peuvent être couverts`))).toBeVisible();
  await resetAll(page);
});

test("planning : compteur visible, horaires proposés selon la boutique (Cartier 08h–17h seulement)", async ({ page }) => {
  await page.goto("/planning");
  await expect(counterText(page).first()).toContainText("à couvrir");
  await page.getByRole("tab", { name: "Semaine" }).click();
  await page.getByRole("button", { name: "Semaine suivante" }).click(); // 9–15 nov. : Cartier le vendredi 13
  await page.locator('.shift[aria-label*=", Cartier, Cartier"]').first().click();
  const sel = page.getByLabel("Horaire autorisé");
  await expect(sel).toBeVisible();
  expect(await sel.locator("option").allTextContents()).toEqual(["08:00–17:00"]);
});
