import { expect, test, type Locator, type Page } from "@playwright/test";

// Prérequis : pile lancée + comptes de démo (E2E_EMAIL / E2E_PASSWORD). Les tests restaurent l'état initial.
test.skip(!process.env.E2E_EMAIL, "E2E_EMAIL non défini");
const API = process.env.API_URL ?? "http://localhost:8000";
test.describe.configure({ mode: "serial" });

type A = { assignment_id: string; slot_key: string; day: string; site: string; start: string; end: string; employee_id: string; employee: string };
let target: A; let other: { id: string; name: string }; let periodId = "";

async function schedule(page: Page): Promise<A[]> {
  const r = await page.request.get(`${API}/periods/${periodId}/schedule`);
  return (await r.json()).assignments as A[];
}
const owner = async (page: Page) => (await schedule(page)).find((a) => a.assignment_id === target.assignment_id)!.employee_id;
async function force(page: Page, empId: string) {
  const me = await (await page.request.get(`${API}/auth/me`)).json();
  await page.request.put(`${API}/assignments/${target.assignment_id}`, { data: { employee_id: empId }, headers: { "X-CSRF-Token": me.csrf_token } });
}

test.beforeAll(async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: "e2e/.auth/state.json" });
  const page = await ctx.newPage();
  periodId = (await (await page.request.get(`${API}/periods`)).json()).find((p: { start_date: string }) => p.start_date === "2026-11-01").id;
  const all = await schedule(page);
  target = all.find((a) => a.day === "2026-11-02" && a.site === "GVA3" && a.start.startsWith("06:00"))!;
  const emps = (await (await page.request.get(`${API}/employees`)).json()) as { id: string; name: string }[];
  // remplaçant autorisé, libre ce jour-là et avec de la marge sous le plafond mensuel de 176 h (sinon le remplacement est refusé, à juste titre)
  const used = (id: string) => all.filter((a) => a.employee_id === id).reduce((s, a) => s + ((a as unknown as { effective_minutes: number }).effective_minutes ?? 0), 0);
  const eff = (target as unknown as { effective_minutes: number }).effective_minutes ?? 480;
  other = emps.find((e) => e.id !== target.employee_id && !(e as unknown as { deleted_at?: string | null }).deleted_at && (e as unknown as { brands: Record<string, string> }).brands["Ploom GVA3"]
    && !all.some((a) => a.employee_id === e.id && a.day === target.day) && used(e.id) + eff <= 176 * 60)!;
  await ctx.close();
});
test.afterEach(async ({ page }) => { if ((await owner(page)) !== target.employee_id) await force(page, target.employee_id); });

async function openDay(page: Page): Promise<Locator> {
  await page.goto("/planning");
  await page.getByRole("tab", { name: "Jour", exact: true }).click();
  // en-tête de la vue « Jour » (annoncé aux lecteurs d'écran) ; d'autres panneaux peuvent citer la même date
  await expect(page.locator('strong[aria-live="polite"]').filter({ hasText: /^Lun 2 nov\.$/ })).toBeVisible();
  return page.getByLabel(`Collaborateur pour GVA3 06:00–15:00`);
}
const dialog = (page: Page) => page.getByRole("dialog", { name: "Confirmer le remplacement ?" });
async function pick(page: Page) { const sel = await openDay(page); await sel.selectOption(other.id); return sel; }

test("1. choisir un autre collaborateur n'enregistre rien et ouvre la confirmation complète", async ({ page }) => {
  const sel = await pick(page);
  const d = dialog(page);
  await expect(d).toBeVisible();
  for (const t of [target.employee, other.name, "Lundi 2 novembre 2026", "06h00 à 15h00", "GVA3", "Ploom GVA3", "8 h", "Confirmer le remplacement"]) await expect(d).toContainText(t);
  expect(await owner(page)).toBe(target.employee_id);
  await expect(sel).toHaveValue(target.employee_id); // le sélecteur n'a pas changé
});

test("2. Annuler conserve l'affectation", async ({ page }) => {
  await pick(page);
  await dialog(page).getByRole("button", { name: "Annuler", exact: true }).click();
  await expect(dialog(page)).toBeHidden();
  expect(await owner(page)).toBe(target.employee_id);
});

test("3. Échap annule", async ({ page }) => {
  await pick(page);
  await expect(dialog(page)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog(page)).toBeHidden();
  expect(await owner(page)).toBe(target.employee_id);
});

test("4. cliquer à l'extérieur ne valide pas", async ({ page }) => {
  await pick(page);
  await expect(dialog(page)).toBeVisible();
  await page.mouse.click(4, 4);
  await expect(dialog(page)).toBeHidden();
  expect(await owner(page)).toBe(target.employee_id);
});

test("5. Confirmer applique la modification et propose d'annuler", async ({ page }) => {
  await pick(page);
  await dialog(page).getByRole("button", { name: "Confirmer le remplacement" }).click();
  await expect(dialog(page)).toBeHidden();
  await expect(page.getByText(/Shift réaffecté à/)).toBeVisible();
  await expect(page.getByRole("region", { name: "Notifications" }).getByRole("button", { name: "Annuler" })).toBeVisible();
  expect(await owner(page)).toBe(other.id);
});

test("8. l'action « Annuler » de la notification restaure l'affectation précédente", async ({ page }) => {
  await pick(page);
  await dialog(page).getByRole("button", { name: "Confirmer le remplacement" }).click();
  await expect(page.getByText(/Shift réaffecté à/)).toBeVisible();
  expect(await owner(page)).toBe(other.id);
  await page.getByRole("region", { name: "Notifications" }).getByRole("button", { name: "Annuler" }).click();
  await expect(page.getByText(/Modification annulée/)).toBeVisible();
  await expect.poll(() => owner(page)).toBe(target.employee_id);
});

test("6. le glisser-déposer demande aussi une confirmation", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 2400 }); // source et cible visibles ensemble : un glisser-déposer natif ne défile pas
  await page.goto("/planning");
  await expect(page.getByRole("region", { name: /Planning général/ })).toBeVisible();
  await expect(page.getByRole("group", { name: "Compteur des dimanches" })).toBeVisible(); // mise en page stable avant de glisser
  const cell = (name: string) => page.locator(`.cal-cell[aria-label="${name}, Lun 2 nov."]`);
  // carte repérée par son texte visible (horaire, marque), comme le voit le manager
  const card = cell(target.employee).locator(".shift").filter({ hasText: "06:00–15:00" }).filter({ hasText: "Ploom GVA3" }).first();
  await card.dragTo(cell(other.name));
  await expect(dialog(page)).toBeVisible();
  await expect(dialog(page)).toContainText(other.name);
  expect(await owner(page)).toBe(target.employee_id); // rien n'est enregistré avant confirmation
  await dialog(page).getByRole("button", { name: "Annuler", exact: true }).click();
  expect(await owner(page)).toBe(target.employee_id);
  await card.dragTo(cell(other.name));
  await dialog(page).getByRole("button", { name: "Confirmer le remplacement" }).click();
  await expect.poll(() => owner(page)).toBe(other.id);
});

test("fiche détaillée : « Réaffecter » passe aussi par la confirmation", async ({ page }) => {
  await page.goto("/planning");
  await page.locator(`.cal-cell[aria-label^="${target.employee}, "]`).locator(".shift").filter({ hasText: "06:00–15:00" }).filter({ hasText: "Ploom GVA3" }).first().click();
  await page.getByLabel("Réaffecter à").selectOption(other.id);
  await page.getByRole("button", { name: "Réaffecter", exact: true }).click();
  await expect(dialog(page)).toBeVisible();
  expect(await owner(page)).toBe(target.employee_id);
  await dialog(page).getByRole("button", { name: "Annuler", exact: true }).click();
  expect(await owner(page)).toBe(target.employee_id);
});

test("7. une erreur de sauvegarde conserve l'ancien collaborateur et s'affiche en français", async ({ page }) => {
  await pick(page);
  await page.route("**/assignments/*", (r) => (r.request().method() === "PUT" ? r.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "Erreur interne" }) }) : r.continue()));
  await dialog(page).getByRole("button", { name: "Confirmer le remplacement" }).click();
  const alert = dialog(page).getByRole("alert");
  await expect(alert).toContainText("n'a pas pu être enregistré");
  await expect(alert).toContainText("conservée");
  await expect(dialog(page)).toBeVisible(); // reste ouverte : réessayer ou annuler
  expect(await owner(page)).toBe(target.employee_id);
  await page.unroute("**/assignments/*");
  await dialog(page).getByRole("button", { name: "Annuler", exact: true }).click();
  expect(await owner(page)).toBe(target.employee_id);
});

test("9a. clavier : focus initial sur Annuler ; Entrée n'y confirme jamais ; Tab puis Entrée confirme", async ({ page }) => {
  await pick(page);
  const cancel = dialog(page).getByRole("button", { name: "Annuler", exact: true });
  await expect(cancel).toBeFocused();
  const confirmBtn = dialog(page).getByRole("button", { name: "Confirmer le remplacement" });
  await expect(async () => { await cancel.focus(); await page.keyboard.press("Tab"); await expect(confirmBtn).toBeFocused({ timeout: 1000 }); }).toPass(); // Tab depuis « Annuler » -> « Confirmer »
  await page.keyboard.press("Shift+Tab");
  await expect(cancel).toBeFocused();
  await page.keyboard.press("Enter"); // Entrée sur « Annuler » = annuler
  await expect(dialog(page)).toBeHidden();
  expect(await owner(page)).toBe(target.employee_id);
  await pick(page);
  await expect(dialog(page).getByRole("button", { name: "Annuler", exact: true })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(dialog(page).getByRole("button", { name: "Confirmer le remplacement" })).toBeFocused();
  await page.keyboard.press("Enter"); // focus explicite sur « Confirmer »
  await expect.poll(() => owner(page)).toBe(other.id);
});

test("9b. mobile : la modale tient dans l'écran, boutons atteignables, annulation et confirmation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await pick(page);
  const d = dialog(page);
  await expect(d).toBeVisible();
  const box = (await d.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x + box.width).toBeLessThanOrEqual(390.5);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await d.getByRole("button", { name: "Annuler", exact: true }).click();
  expect(await owner(page)).toBe(target.employee_id);
  await pick(page);
  await d.getByRole("button", { name: "Confirmer le remplacement" }).tap().catch(() => d.getByRole("button", { name: "Confirmer le remplacement" }).click());
  await expect.poll(() => owner(page)).toBe(other.id);
});
