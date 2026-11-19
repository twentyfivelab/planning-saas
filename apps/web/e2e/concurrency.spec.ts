import { expect, test, type Page } from "@playwright/test";
import { API, getJson as j } from "./api";

// Deux managers : l'écran d'un manager affiche une situation périmée (un collègue a modifié le shift entre-temps). Sa réaffectation et
// sa modification d'horaire sont refusées avec un message clair, rien n'est écrasé, et le planning affiche la nouvelle situation.
// Mois dédié (mai 2028), supprimé à la fin.
test.skip(!process.env.E2E_EMAIL || !process.env.E2E_PASSWORD, "E2E_EMAIL / E2E_PASSWORD non définis");
test.describe.configure({ mode: "serial" });

const csrf = async (page: Page) => (await j(page, "/auth/me")).csrf_token as string;
type A = { assignment_id: string; shift_id: string; employee_id: string; day: string; start: string; end: string; break_minutes: number; locked: boolean; allocations: Record<string, number> };
let pid = "";

test.beforeAll(async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: "e2e/.auth/state.json" });
  const page = await ctx.newPage();
  const token = await csrf(page);
  pid = (await (await page.request.post(`${API}/periods/ensure`, { headers: { "X-CSRF-Token": token }, data: { year: 2028, month: 5 } })).json()).id;
  if (!((await j(page, `/periods/${pid}/schedule`)).assignments as unknown[]).length) {
    const run = await page.request.post(`${API}/periods/${pid}/runs`, { headers: { "X-CSRF-Token": token, "Idempotency-Key": `conc-${Date.now()}` }, data: { time_limit_s: 10 } });
    expect(run.status(), await run.text()).toBe(202);
    await expect.poll(async () => ((await j(page, `/periods/${pid}/schedule`)).assignments as unknown[]).length, { timeout: 50_000 }).toBeGreaterThan(0);
  }
  await ctx.close();
});

test.afterAll(async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: "e2e/.auth/state.json" });
  const page = await ctx.newPage();
  await page.request.post(`${API}/periods/${pid}/delete`, { headers: { "X-CSRF-Token": await csrf(page) }, data: { password: process.env.E2E_PASSWORD } });
  await ctx.close();
});

async function openMay(page: Page) {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/planning");
  await page.evaluate(() => { try { localStorage.setItem("planning:month", "2028-05"); } catch { /* ignoré */ } });
  await page.reload(); await page.waitForLoadState("networkidle");
}

test("réaffectation sur une vue périmée : refusée et expliquée, rien n'est écrasé", async ({ page }) => {
  const H = { "X-CSRF-Token": await csrf(page) };
  await openMay(page);
  // l'onglet ne doit pas se recharger tout seul entre-temps : on simule un manager dont l'écran n'a pas encore reçu la modification
  await page.route("**/events", (r) => r.abort()); await page.route("**/revision", (r) => r.abort());
  const rows = (await j(page, `/periods/${pid}/schedule`)).assignments as A[];
  const card = page.getByRole("region", { name: /Planning général/ }).locator(".shift:not([data-locked])").first();
  const aid = (await card.getAttribute("data-assignment"))!;
  const x = rows.find((r) => r.assignment_id === aid)!;
  const busy = new Set(rows.filter((r) => r.day === x.day).map((r) => r.employee_id));
  // collègues libres ce jour-là ET autorisés sur la marque du shift (les autres sont grisés dans la liste, à juste titre)
  const emps = ((await j(page, "/employees")) as { id: string; name: string; brands: Record<string, string> }[])
    .filter((e) => !busy.has(e.id) && Object.keys(x.allocations).every((b) => b in (e.brands ?? {})));
  test.skip(emps.length < 2, "pas deux collègues libres et autorisés ce jour-là");
  await card.click();
  // un collègue réaffecte ce shift juste avant (par l'API, comme depuis un autre poste)
  const other = emps[0];
  expect((await page.request.put(`${API}/assignments/${aid}`, { headers: H, data: { employee_id: other.id, expected_employee_id: x.employee_id } })).status()).toBe(200);
  // ce manager, sur sa vue périmée, choisit quelqu'un d'autre
  const mine = emps[1];
  await page.getByLabel("Réaffecter à").selectOption(mine.id);
  await page.getByRole("button", { name: "Réaffecter", exact: true }).click();
  const dlg = page.getByRole("dialog", { name: "Confirmer le remplacement ?" });
  await dlg.getByRole("button", { name: "Confirmer le remplacement" }).click();
  await expect(dlg).toContainText("modifié par quelqu'un d'autre");
  await expect(dlg).toContainText("Rien n'a été modifié");
  const now = ((await j(page, `/periods/${pid}/schedule`)).assignments as A[]).find((r) => r.assignment_id === aid)!;
  expect(now.employee_id).toBe(other.id); // la modification du collègue est conservée
});

test("modification d'horaire sur une vue périmée : refusée, les horaires du collègue sont conservés", async ({ page }) => {
  const H = { "X-CSRF-Token": await csrf(page) };
  await openMay(page);
  await page.route("**/events", (r) => r.abort()); await page.route("**/revision", (r) => r.abort());
  const card = page.getByRole("region", { name: /Planning général/ }).locator(".shift:not([data-locked])").first();
  const aid = (await card.getAttribute("data-assignment"))!;
  const x = ((await j(page, `/periods/${pid}/schedule`)).assignments as A[]).find((r) => r.assignment_id === aid)!;
  await card.click();
  const brk = x.break_minutes === 60 ? 45 : 60;
  expect((await page.request.patch(`${API}/shifts/${x.shift_id}`, { headers: H, data: { start_time: x.start, end_time: x.end, break_minutes: brk, expected_start: x.start, expected_end: x.end, expected_break: x.break_minutes } })).status()).toBe(200);
  await page.getByLabel("Pause (min)").fill(String(x.break_minutes === 30 ? 15 : 30));
  await page.getByRole("button", { name: "Modifier l'horaire" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "modifiés par quelqu'un d'autre" }).first()).toBeVisible(); // erreur : annoncée comme alerte
  const now = ((await j(page, `/periods/${pid}/schedule`)).assignments as A[]).find((r) => r.assignment_id === aid)!;
  expect(now.break_minutes).toBe(brk); // l'horaire du collègue n'a pas été écrasé
});
