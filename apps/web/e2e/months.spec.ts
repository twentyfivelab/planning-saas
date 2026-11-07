import { expect, test, type Page } from "@playwright/test";
import { getJson } from "./api";

// Prérequis : pile lancée + tenant de démonstration (E2E_EMAIL / E2E_PASSWORD, rôle manager ou supérieur).
test.skip(!process.env.E2E_EMAIL, "E2E_EMAIL non défini");
test.describe.configure({ mode: "serial" });
const API = process.env.API_URL ?? "http://localhost:8000";

async function csrf(page: Page) { return (await (await page.request.get(`${API}/auth/me`)).json()).csrf_token as string; }
const j = (page: Page, path: string) => getJson(page, path);
async function periodOf(page: Page, month: string) { return ((await j(page, "/periods")) as { id: string; start_date: string }[]).find((p) => p.start_date.startsWith(month)); }
const sched = async (page: Page, id: string) => (await j(page, `/periods/${id}/schedule`)).assignments as { assignment_id: string; slot_key: string; employee: string; day: string }[];
const snap = (rows: { slot_key: string; employee: string }[]) => JSON.stringify(rows.map((r) => [r.slot_key, r.employee]).sort());
async function gotoPlanning(page: Page) { await page.goto("/planning"); await page.waitForLoadState("networkidle"); await expect(page.getByLabel("Mois", { exact: true })).toBeVisible(); }
async function selectMonth(page: Page, month: number, year: number) {
  await page.getByLabel("Année", { exact: true }).selectOption(String(year));
  await page.getByLabel("Mois", { exact: true }).selectOption(String(month));
}

test.beforeAll(async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: "e2e/.auth/state.json" });
  const page = await ctx.newPage();
  const nov = await periodOf(page, "2026-11");
  const token = await csrf(page);
  if (nov && !(await sched(page, nov.id)).length) await page.request.post(`${API}/periods/${nov.id}/runs`, { headers: { "X-CSRF-Token": token, "Idempotency-Key": `m-${Date.now()}` }, data: { time_limit_s: 30 } });
  await expect.poll(async () => (await j(page, "/runs"))[0]?.status, { timeout: 60_000 }).toBe("termine");
  await ctx.close();
});

// Scénario A
test("A. planning général : défilement horizontal sur tout le mois, noms fixes, dates alignées, cartes sans chevauchement", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1000 });
  await gotoPlanning(page);
  await selectMonth(page, 11, 2026);
  const sc = page.getByRole("region", { name: /Planning général/ });
  await expect(sc).toBeVisible();
  const sl = () => sc.evaluate((e) => e.scrollLeft);
  const nameX = async () => (await page.locator(".hgrid .cal-name").first().boundingBox())!.x;
  const x0 = await nameX();
  expect(await sl()).toBe(0);
  await page.getByRole("button", { name: "Jours suivants" }).click();
  await expect.poll(sl).toBeGreaterThan(100);
  await page.mouse.move(700, 500);
  const before = await sl();
  await page.mouse.wheel(400, 0); // trackpad / souris
  await expect.poll(sl).toBeGreaterThan(before);
  expect(await nameX()).toBeCloseTo(x0, 0); // la colonne des noms reste fixe
  // dates alignées avec les cellules (même colonne), pour chaque jour visible
  const dx = await page.evaluate(() => {
    const heads = [...document.querySelectorAll(".hgrid-head .cal-h")].slice(1, -1) as HTMLElement[];
    const row = document.querySelectorAll(".hgrid-row")[1];
    const cells = [...row.querySelectorAll(".cal-cell")].slice(0, -1) as HTMLElement[];
    return heads.map((h, i) => Math.abs(h.getBoundingClientRect().left - cells[i].getBoundingClientRect().left) + Math.abs(h.getBoundingClientRect().width - cells[i].getBoundingClientRect().width));
  });
  expect(dx).toHaveLength(30); expect(Math.max(...dx)).toBeLessThan(1);
  // cartes de shifts : aucun chevauchement
  const overlaps = await page.evaluate(() => {
    const r = [...document.querySelectorAll(".hgrid .shift")].map((e) => e.getBoundingClientRect()).filter((b) => b.width > 0);
    let n = 0; for (let i = 0; i < r.length; i++) for (let k = i + 1; k < r.length; k++) { const a = r[i], b = r[k]; if (a.left < b.right - 0.5 && b.left < a.right - 0.5 && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5) n++; }
    return { n, total: r.length };
  });
  expect(overlaps.total).toBeGreaterThan(0); expect(overlaps.n).toBe(0);
  // tout le mois est atteignable : flèche jusqu'au dernier jour
  const next = page.getByRole("button", { name: "Jours suivants" });
  for (let i = 0; i < 8 && (await next.isEnabled()); i++) { await next.click(); await page.waitForTimeout(250); }
  await expect(page.locator("strong[aria-live=polite]").filter({ hasText: /Lun 30 nov\.$/ })).toBeVisible();
  await expect(next).toBeDisabled();
  // changement de vue : la position est conservée ; changement de mois : réinitialisée
  const end = await sl();
  await page.getByRole("tab", { name: "Mois", exact: true }).click();
  await page.getByRole("tab", { name: "Planning général" }).click();
  await expect.poll(sl).toBeGreaterThan(end - 5);
});

// Scénarios F, G, H, I
test("F-I. décembre 2026 et janvier 2027 : calendrier exact, 35 puis 28 shifts du dimanche, novembre conservé", async ({ page }) => {
  await gotoPlanning(page);
  const nov = (await periodOf(page, "2026-11"))!;
  const novBefore = snap(await sched(page, nov.id));
  expect(novBefore).not.toBe("[]");
  await page.getByRole("button", { name: "Mois suivant" }).click(); // novembre → décembre
  await expect(page.getByLabel("Mois", { exact: true })).toHaveValue("12");
  await expect(page.getByLabel("Année", { exact: true })).toHaveValue("2026");
  const dec = await periodOf(page, "2026-12");
  if (!dec) {
    await expect(page.getByText("Calendrier de Décembre 2026")).toBeVisible();
    await expect(page.getByTestId("sunday-formula")).toContainText("4 dimanches × 7 shifts = 28 shifts du dimanche");
    await expect(page.getByText("Aucun budget défini pour Décembre 2026")).toBeVisible(); // aucun budget inventé
  }
  await page.getByRole("button", { name: "Mois suivant" }).click(); // décembre → janvier : l'année change
  await expect(page.getByLabel("Année", { exact: true })).toHaveValue("2027");
  await expect(page.getByLabel("Mois", { exact: true })).toHaveValue("1");
  await page.getByRole("button", { name: "Mois précédent" }).click();
  await expect(page.getByLabel("Année", { exact: true })).toHaveValue("2026");
  // génération de décembre depuis la page de génération (même sélecteur de mois)
  await page.goto("/generate"); await page.waitForLoadState("networkidle");
  await expect(page.getByLabel("Mois", { exact: true })).toHaveValue("12");
  await expect(page.getByTestId("sunday-formula")).toContainText("4 dimanches × 7 shifts = 28");
  await page.getByRole("button", { name: "Continuer", exact: true }).click();
  await page.getByLabel("Durée maximale (secondes)").fill("20");
  await page.getByRole("button", { name: "Générer automatiquement le planning" }).click();
  if (await page.getByRole("button", { name: "Confirmer et lancer" }).isVisible().catch(() => false)) await page.getByRole("button", { name: "Confirmer et lancer" }).click();
  await expect(page.getByText(/Résultat :/)).toBeVisible({ timeout: 90_000 });
  const decNow = (await periodOf(page, "2026-12"))!;
  const decRows = await sched(page, decNow.id);
  expect(decRows.length).toBeGreaterThan(50);
  expect(decRows.every((r) => r.day >= "2026-12-01" && r.day <= "2026-12-31")).toBe(true);
  expect(snap(await sched(page, nov.id))).toBe(novBefore); // novembre non écrasé
  // le planning général de décembre affiche 31 jours
  await page.goto("/planning"); await page.waitForLoadState("networkidle");
  await expect(page.getByLabel("Mois", { exact: true })).toHaveValue("12");
  await expect(page.locator(".hgrid-head .cal-h")).toHaveCount(31 + 2);
  // janvier 2027 : 5 dimanches → 35 shifts (calendrier calculé, jamais codé pour novembre)
  await selectMonth(page, 1, 2027);
  if (!(await periodOf(page, "2027-01"))) { await expect(page.getByTestId("sunday-formula")).toContainText("5 dimanches × 7 shifts = 35"); }
  // retour à novembre 2026 : affectations intactes, 30 colonnes
  await selectMonth(page, 11, 2026);
  await expect(page.locator(".hgrid-head .cal-h")).toHaveCount(30 + 2);
  expect(snap(await sched(page, nov.id))).toBe(novBefore);
  await page.reload(); await page.waitForLoadState("networkidle");
  await expect(page.getByLabel("Mois", { exact: true })).toHaveValue("11"); // le mois choisi est mémorisé
});

// Scénario K + L (quota de dimanches indépendant par mois)
test("K-L. quota de dimanches propre à chaque mois, enregistré et conservé après actualisation", async ({ page }) => {
  const emps = (await j(page, "/employees")) as { id: string; code: string }[];
  const zaki = emps.find((e) => e.code === "zaki")!;
  const token = await csrf(page);
  for (const m of ["2026-11", "2026-12"]) await page.request.put(`${API}/employees/${zaki.id}/month-params/${m}`, { headers: { "X-CSRF-Token": token }, data: { sunday_quota: null, sunday_mode: "max" } });
  const open = async () => { await page.getByRole("row", { name: /^Zaki / }).getByRole("button", { name: "Fiche" }).click(); const d = page.getByRole("dialog", { name: "Fiche — Zaki" }); await expect(d).toBeVisible(); return d; };
  await page.goto("/employees"); await page.waitForLoadState("networkidle");
  await selectMonth(page, 11, 2026);
  let dlg = await open();
  await expect(dlg.getByText(/Réglage propre à ce mois/)).toBeVisible();
  await dlg.getByLabel("Nombre de dimanches").selectOption("2");
  await expect(dlg.getByText("Enregistré automatiquement", { exact: true }).first()).toBeVisible();
  await dlg.getByRole("button", { name: "Fermer" }).click();
  await selectMonth(page, 12, 2026);
  dlg = await open();
  await expect(dlg.getByLabel("Nombre de dimanches")).toHaveValue(""); // décembre n'hérite pas de novembre
  await dlg.getByLabel("Nombre de dimanches").selectOption("3");
  await expect(dlg.getByText("Enregistré automatiquement", { exact: true }).first()).toBeVisible();
  await dlg.getByRole("button", { name: "Fermer" }).click();
  // modifier décembre ne change pas novembre ; tout persiste après actualisation
  const mp = async (m: string) => ((await j(page, `/month-params?month=${m}`)) as { employee_id: string; sunday_quota: number | null }[]).find((x) => x.employee_id === zaki.id)!.sunday_quota;
  expect([await mp("2026-11"), await mp("2026-12")]).toEqual([2, 3]);
  await page.reload(); await page.waitForLoadState("networkidle");
  await expect(page.getByLabel("Mois", { exact: true })).toHaveValue("12");
  await selectMonth(page, 11, 2026);
  dlg = await open();
  await expect(dlg.getByLabel("Nombre de dimanches")).toHaveValue("2");
  await dlg.getByRole("button", { name: "Fermer" }).click();
  for (const m of ["2026-11", "2026-12"]) await page.request.put(`${API}/employees/${zaki.id}/month-params/${m}`, { headers: { "X-CSRF-Token": token }, data: { sunday_quota: null, sunday_mode: "max" } });
});

// Scénario E
test("E. pondérations : curseur + saisie, enregistrement automatique, persistance, transmission au solveur, réinitialisation", async ({ page }) => {
  await page.goto("/settings"); await page.waitForLoadState("networkidle");
  const row = page.getByTestId("weight-family");
  await expect(row).toContainText("Relations entre collaborateurs");
  await expect(row.getByRole("spinbutton")).toHaveValue("90");
  await row.getByRole("spinbutton").fill("40");
  await expect(page.getByText("Enregistré automatiquement")).toBeVisible();
  const weights = async () => (await j(page, "/settings/weights")) as { criteria: { key: string; value: number; engine: Record<string, number> }[]; customised: boolean };
  await expect.poll(async () => (await weights()).criteria.find((c) => c.key === "family")!.value).toBe(40);
  const eng = (await weights()).criteria.find((c) => c.key === "family")!.engine.family;
  expect(eng).toBeLessThan(15); // poids moteur par défaut : 15 ; 90 → 40 le réduit
  await page.reload(); await page.waitForLoadState("networkidle");
  await expect(page.getByTestId("weight-family").getByRole("spinbutton")).toHaveValue("40"); // persiste
  await page.getByTestId("weight-fairness").getByRole("slider").fill("100"); // curseur
  await expect.poll(async () => (await weights()).criteria.find((c) => c.key === "fairness")!.value).toBe(100);
  // le solveur reçoit les poids enregistrés
  const nov = (await periodOf(page, "2026-11"))!;
  const token = await csrf(page);
  await page.request.post(`${API}/periods/${nov.id}/reoptimize`, { headers: { "X-CSRF-Token": token, "Idempotency-Key": `w-${Date.now()}` }, data: { time_limit_s: 20 } });
  await expect.poll(async () => (await j(page, "/runs"))[0].status, { timeout: 60_000 }).toBe("termine");
  const run = (await j(page, "/runs"))[0];
  const rep = (await j(page, `/runs/${run.id}/diagnostic`)).report;
  expect(rep.weights_used.family).toBe(eng); expect(rep.weights_used.fairness).toBeGreaterThan(3); expect(rep.criteria_scores).toBeTruthy();
  await page.reload(); await page.waitForLoadState("networkidle");
  await expect(page.getByText("Influence sur la dernière génération")).toBeVisible();
  await page.getByRole("button", { name: "Réinitialiser les pondérations par défaut" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Réinitialiser", exact: true }).click();
  await expect.poll(async () => (await weights()).customised).toBe(false);
  await expect(page.getByTestId("weight-family").getByRole("spinbutton")).toHaveValue("90");
});
