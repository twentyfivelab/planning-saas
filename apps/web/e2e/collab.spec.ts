import { expect, test, type Browser, type Page } from "@playwright/test";
import { getJson } from "./api";

// Prérequis : pile lancée, tenant de démonstration (E2E_EMAIL / E2E_PASSWORD = propriétaire ; E2E_EMAIL2 = second manager, facultatif).
test.skip(!process.env.E2E_EMAIL, "E2E_EMAIL non défini");
test.describe.configure({ mode: "serial" });
const API = process.env.API_URL ?? "http://localhost:8000";
const EMAIL2 = process.env.E2E_EMAIL2 ?? process.env.E2E_EMAIL!.replace(/^[^@]+/, "manager");

type Row = { assignment_id: string; shift_id: string; slot_key: string; employee: string; employee_id: string; day: string; site: string; start: string; end: string; locked: boolean; effective_minutes: number; allocations: Record<string, number> };
type Emp = { id: string; code: string; name: string; brands: Record<string, string> };
const j = (page: Page, path: string) => getJson(page, path);
const csrf = async (page: Page) => (await j(page, "/auth/me")).csrf_token as string;
let pid = "";
const sched = async (page: Page) => (await j(page, `/periods/${pid}/schedule`)).assignments as Row[];
const DOW = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
const label = (iso: string) => `${DOW[(new Date(iso + "T12:00:00Z").getUTCDay() + 6) % 7]} ${Number(iso.slice(8))} nov.`;
const near = (rows: Row[], name: string, day: string) => rows.some((x) => x.employee === name && Math.abs(Number(x.day.slice(8)) - Number(day.slice(8))) <= 1);

async function manager2(browser: Browser) {
  const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const r = await ctx.request.post(`${API}/auth/login`, { data: { email: EMAIL2, password: process.env.E2E_PASSWORD } });
  expect(r.ok(), `connexion de ${EMAIL2}`).toBe(true);
  return ctx;
}

test.beforeAll(async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: "e2e/.auth/state.json" });
  const page = await ctx.newPage();
  pid = ((await j(page, "/periods")) as { id: string; start_date: string }[]).find((p) => p.start_date === "2026-11-01")!.id;
  if (!(await sched(page)).length) {
    await page.request.post(`${API}/periods/${pid}/runs`, { headers: { "X-CSRF-Token": await csrf(page), "Idempotency-Key": `c-${Date.now()}` }, data: { time_limit_s: 30 } });
    await expect.poll(async () => (await j(page, "/runs"))[0].status, { timeout: 60_000 }).toBe("termine");
  }
  await ctx.close();
});

test("temps réel : un second manager voit le transfert en moins de 2 s, sans recharger la page", async ({ page, browser }) => {
  const other = await manager2(browser);
  const b = await other.newPage();
  await b.setViewportSize({ width: 1600, height: 1000 });
  await b.goto("/planning"); await b.waitForLoadState("networkidle");
  await b.evaluate(() => { (window as unknown as { __m: number }).__m = 42; });
  const emps = (await j(page, "/employees")) as Emp[];
  const rows = await sched(page);
  // un shift non verrouillé de la première semaine (visible sans défiler) et un collaborateur libre, autorisé
  const pick = rows.flatMap((a) => (a.locked || a.day < "2026-11-02" || a.day > "2026-11-06" ? [] : emps.filter((e) => e.name !== a.employee && e.code !== "sabrina" && !near(rows, e.name, a.day)
    && Object.keys(a.allocations).every((k) => k in e.brands)).map((e) => ({ a, e }))))[0];
  expect(pick).toBeTruthy();
  const cell = b.locator(`.cal-cell[aria-label="${pick.e.name}, ${label(pick.a.day)}"]`);
  await expect(cell.locator(".shift")).toHaveCount(0);
  const t0 = Date.now();
  const r = await page.request.post(`${API}/periods/${pid}/manual-assign`, { headers: { "X-CSRF-Token": await csrf(page) }, data: { employee_id: pick.e.id, shift_id: pick.a.shift_id, force: true } });
  expect(r.status()).toBe(200);
  await expect(cell.locator(".shift")).toHaveCount(1, { timeout: 2000 });
  const elapsed = Date.now() - t0;
  console.log(`temps réel : affiché chez le second manager en ${elapsed} ms`);
  expect(elapsed).toBeLessThan(2000); // bien en dessous du cycle d'interrogation de 6 s
  expect(await b.evaluate(() => (window as unknown as { __m?: number }).__m)).toBe(42); // aucune actualisation de page
  await other.close();
  const mine = (await sched(page)).find((x) => x.shift_id === pick.a.shift_id)!;
  await page.request.post(`${API}/assignments/${mine.assignment_id}/unlock`, { headers: { "X-CSRF-Token": await csrf(page) } }); // nettoyage
});

test("Kristina → Sahra : transfert depuis le calendrier de Sahra, deux plannings et tous les compteurs actualisés immédiatement", async ({ page, browser }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  const token = await csrf(page);
  const emps = (await j(page, "/employees")) as Emp[];
  const K = emps.find((e) => e.code === "kristina")!, S = emps.find((e) => e.code === "sahra")!;
  await page.request.put(`${API}/employees/${S.id}/unavailable-dates`, { headers: { "X-CSRF-Token": token }, data: { dates: [] } });
  let rows = await sched(page);
  // plafond mensuel de 176 h : Kristina puis Sahra recevront ce shift ; on libère un de leurs shifts si elles sont au plafond (jamais dépassé)
  for (const name of ["Kristina", "Sahra"]) {
    const used = rows.filter((x) => x.employee === name).reduce((s, x) => s + x.effective_minutes, 0);
    if (used + 9 * 60 > 176 * 60) {
      const drop = (rows.find((x) => x.employee === name && !x.locked && x.day > "2026-11-27") ?? rows.find((x) => x.employee === name && !x.locked && x.day < "2026-11-03"))!;
      expect((await page.request.delete(`${API}/assignments/${drop.assignment_id}`, { headers: { "X-CSRF-Token": token } })).status()).toBe(204);
      rows = await sched(page);
    }
  }
  // 1) un shift Ploom attribué INITIALEMENT à Kristina, un jour (hors dimanche) où Sahra et Kristina sont libres
  const cand = rows.find((a) => !a.locked && a.day >= "2026-11-03" && a.day <= "2026-11-27" && new Date(a.day + "T12:00:00Z").getUTCDay() !== 0
    && Object.keys(a.allocations).every((k) => k.startsWith("Ploom") && k !== "Ploom Pilar") && a.employee !== "Kristina" && a.employee !== "Sahra"
    && !rows.some((x) => (x.employee === "Sahra" || x.employee === "Kristina") && x.day === a.day))!;
  expect(cand).toBeTruthy();
  expect((await page.request.post(`${API}/periods/${pid}/manual-assign`, { headers: { "X-CSRF-Token": token }, data: { employee_id: K.id, shift_id: cand.shift_id, force: true, reason: "préparation du test" } })).status()).toBe(200);
  rows = await sched(page);
  const shift = rows.find((x) => x.shift_id === cand.shift_id)!;
  expect(shift.employee).toBe("Kristina");
  const mins = (name: string, rs: Row[]) => rs.filter((x) => x.employee === name).reduce((s, x) => s + x.effective_minutes, 0);
  const days = (name: string, rs: Row[]) => new Set(rs.filter((x) => x.employee === name).map((x) => x.day)).size;
  const before = { k: [days("Kristina", rows), mins("Kristina", rows)], s: [days("Sahra", rows), mins("Sahra", rows)], total: rows.length, brand: (await j(page, `/periods/${pid}/sunday-summary`)).planned };
  const budgetsBefore = JSON.stringify(rows.reduce<Record<string, number>>((o, x) => { for (const [b, v] of Object.entries(x.allocations)) o[b] = (o[b] ?? 0) + v; return o; }, {}));
  // 2) planning individuel de Sahra : clic sur la date
  await page.goto("/planning"); await page.waitForLoadState("networkidle");
  await page.evaluate(() => { (window as unknown as { __m: number }).__m = 7; });
  await page.getByRole("tab", { name: "Collaborateur" }).click();
  const sel = page.getByLabel("Collaborateur", { exact: true }).last();
  await sel.selectOption({ label: "Sahra" });
  const badgeDays = page.locator(".badge").filter({ hasText: /jours travaillés$/ });
  const badgeHours = page.locator(".badge").filter({ hasText: /effectives$/ });
  const fmt = (m: number) => `${Math.floor(m / 60)} h${m % 60 ? ` ${String(m % 60).padStart(2, "0")}` : ""}`;
  await expect(badgeDays).toHaveText(`${before.s[0]} jours travaillés`);
  await page.getByRole("button", { name: `Shifts du ${label(shift.day)} pour Sahra` }).click();
  const dlg = page.getByRole("dialog", { name: /Ajouter un jour de travail — Sahra/ });
  const row = dlg.getByRole("button", { name: new RegExp(`^Transférer de Kristina à Sahra : .*${shift.site}`) });
  await expect(row).toContainText("Kristina");
  await row.click();
  await expect(dlg.getByText(/Transférer ce shift de Kristina à Sahra/)).toBeVisible();
  await dlg.getByRole("button", { name: "Confirmer le transfert" }).click();
  const accept = dlg.getByRole("button", { name: "Accepter quand même" });
  // le shift est verrouillé par l'attribution initiale (et le repos peut être court) : l'alerte s'affiche, le propriétaire accepte
  await expect(accept).toBeVisible();
  await expect(dlg.getByRole("alertdialog")).toContainText("Verrouillage");
  await accept.click();
  await expect(page.getByText("Shift de Kristina transféré à Sahra.")).toBeVisible();
  // 3) Sahra : shift visible + compteurs, sans recharger
  const cell = page.locator(".month-cell").nth(6 + Number(shift.day.slice(8)) - 1);
  await expect(cell).toContainText(shift.start.slice(0, 5));
  await expect(badgeDays).toHaveText(`${before.s[0] + 1} jours travaillés`);
  await expect(badgeHours).toHaveText(`${fmt(before.s[1] + shift.effective_minutes)} effectives`);
  // Kristina : shift retiré + compteurs
  await sel.selectOption({ label: "Kristina" });
  await expect(cell).not.toContainText(shift.start.slice(0, 5));
  await expect(badgeDays).toHaveText(`${before.k[0] - 1} jours travaillés`);
  await expect(badgeHours).toHaveText(`${fmt(before.k[1] - shift.effective_minutes)} effectives`);
  // planning général : même jour, Sahra a la carte, Kristina une case libre ; totaux de ligne recalculés
  await page.getByRole("tab", { name: "Planning général" }).click();
  const cellOf = (n: string) => page.locator(`.cal-cell[aria-label="${n}, ${label(shift.day)}"]`);
  await cellOf("Sahra").scrollIntoViewIfNeeded();
  await expect(cellOf("Sahra").locator(".shift")).toHaveCount(1);
  await expect(cellOf("Kristina").locator(".shift")).toHaveCount(0);
  const total = (n: string) => page.getByRole("row").filter({ has: page.getByRole("rowheader", { name: n, exact: true }) }).locator(".cal-total");
  await expect(total("Sahra")).toHaveText(fmt(before.s[1] + shift.effective_minutes));
  await expect(total("Kristina")).toHaveText(fmt(before.k[1] - shift.effective_minutes));
  expect(await page.evaluate(() => (window as unknown as { __m?: number }).__m)).toBe(7); // aucune actualisation de page
  // 4) base : un seul titulaire, mêmes horaires / marque / boutique, aucun doublon, budgets et couverture inchangés
  const after = await sched(page);
  const holders = after.filter((x) => x.shift_id === shift.shift_id);
  expect(holders).toHaveLength(1);
  expect(holders[0]).toMatchObject({ employee: "Sahra", day: shift.day, start: shift.start, end: shift.end, site: shift.site, allocations: shift.allocations });
  expect(after.length).toBe(before.total);
  expect(JSON.stringify(after.reduce<Record<string, number>>((o, x) => { for (const [b, v] of Object.entries(x.allocations)) o[b] = (o[b] ?? 0) + v; return o; }, {}))).toBe(budgetsBefore);
  expect((await j(page, `/periods/${pid}/sunday-summary`)).planned).toBe(before.brand);
  expect([days("Sahra", after), mins("Sahra", after)]).toEqual([before.s[0] + 1, before.s[1] + shift.effective_minutes]);
  expect([days("Kristina", after), mins("Kristina", after)]).toEqual([before.k[0] - 1, before.k[1] - shift.effective_minutes]);
  // 5) historique puis persistance après actualisation
  await page.getByRole("button", { name: "Historique" }).click();
  await expect(page.getByRole("dialog", { name: "Historique des modifications" }).getByRole("list", { name: "Historique des modifications" }).locator("li").first()).toContainText("Kristina → Sahra");
  await page.keyboard.press("Escape");
  await page.reload(); await page.waitForLoadState("networkidle");
  await expect(cellOf("Sahra").locator(".shift")).toHaveCount(1);
  await expect(cellOf("Kristina").locator(".shift")).toHaveCount(0);
  // 6) un second manager ouvert sur le planning voit les deux plannings à jour
  const other = await manager2(browser);
  const b = await other.newPage(); await b.setViewportSize({ width: 1440, height: 1100 });
  await b.goto("/planning"); await b.waitForLoadState("networkidle");
  await expect(b.locator(`.cal-cell[aria-label="Sahra, ${label(shift.day)}"] .shift`)).toHaveCount(1);
  await other.close();
  // nettoyage : déverrouille l'affectation manuelle
  await page.request.post(`${API}/assignments/${holders[0].assignment_id}/unlock`, { headers: { "X-CSRF-Token": await csrf(page) } });
});
