import { expect, test, type Page } from "@playwright/test";

// Prérequis : pile lancée + tenant de démonstration (E2E_EMAIL / E2E_PASSWORD, rôle planificateur ou supérieur).
test.skip(!process.env.E2E_EMAIL, "E2E_EMAIL non défini");
test.describe.configure({ mode: "serial" });
const API = process.env.API_URL ?? "http://localhost:8000";

type Emp = { id: string; code: string; name: string; brands: Record<string, string>; allocation_weight: number; active: boolean } & Record<string, unknown>;
let periodId = "";
let originalBrands: Record<string, Record<string, string>> = {};

async function csrf(page: Page) { return (await (await page.request.get(`${API}/auth/me`)).json()).csrf_token as string; }
async function emps(page: Page): Promise<Record<string, Emp>> {
  return Object.fromEntries(((await (await page.request.get(`${API}/employees`)).json()) as Emp[]).map((e) => [e.code, e]));
}
async function putEmp(page: Page, e: Emp, over: Record<string, unknown>) {
  const token = await csrf(page);
  await page.request.put(`${API}/employees/${e.id}`, { headers: { "X-CSRF-Token": token }, data: { code: e.code, name: e.name, brands: e.brands, allocation_weight: e.allocation_weight, active: e.active,
    max_days_count: null, max_days_period: null, time_pref: null, time_pref_strict: false, sunday_quota: null, sunday_mode: "max", min_days_month: null, max_days_month: null, ...over } });
}
async function resetAll(page: Page) {
  // les shifts affectés à la main sont verrouillés : on les déverrouille pour ne pas fausser les autres tests
  for (const a of (await (await page.request.get(`${API}/periods/${periodId || (await (await page.request.get(`${API}/periods`)).json()).find((p: { start_date: string }) => p.start_date === "2026-11-01").id}/schedule`)).json()).assignments as { assignment_id: string; locked: boolean }[]) {
    if (a.locked) await page.request.post(`${API}/assignments/${a.assignment_id}/unlock`, { headers: { "X-CSRF-Token": await csrf(page) } });
  }
  for (const e of Object.values(await emps(page))) {
    await putEmp(page, e, { brands: originalBrands[e.code] ?? e.brands });
    const token = await csrf(page);
    await page.request.put(`${API}/employees/${e.id}/unavailable-dates`, { headers: { "X-CSRF-Token": token }, data: { dates: [] } });
    for (const month of ["2026-11", "2026-12"]) await page.request.put(`${API}/employees/${e.id}/month-params/${month}`, { headers: { "X-CSRF-Token": token }, data: { sunday_quota: null, sunday_mode: "max" } });
  }
}
async function openSheet(page: Page, name: string) {
  await page.goto("/employees");
  await page.getByRole("row", { name: new RegExp(`^${name} `) }).getByRole("button", { name: "Fiche" }).click();
  const dlg = page.getByRole("dialog", { name: `Fiche — ${name}` });
  await expect(dlg).toBeVisible();
  return dlg;
}
const saved = (page: Page) => page.getByRole("dialog").getByText("Enregistré automatiquement", { exact: true }).first();
const counter = (page: Page) => page.getByRole("group", { name: "Compteur des dimanches" });
const sched = async (page: Page) => (await (await page.request.get(`${API}/periods/${periodId}/schedule`)).json()).assignments as { assignment_id: string; employee: string; day: string; site: string; start: string; end: string; locked: boolean; allocations: Record<string, number> }[];
async function plan(page: Page) {
  const token = await csrf(page);
  // « paramètres actuels » : choix explicite d'appliquer les fiches modifiées par le test (sinon le planning garde ses paramètres)
  await page.request.post(`${API}/periods/${periodId}/runs`, { headers: { "X-CSRF-Token": token, "Idempotency-Key": `e2e-${Date.now()}-${Math.random()}` }, data: { time_limit_s: 30, params: "current" } });
  await expect.poll(async () => (await (await page.request.get(`${API}/runs`)).json())[0].status, { timeout: 60_000 }).toBe("termine");
}

test.beforeAll(async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: "e2e/.auth/state.json" });
  const page = await ctx.newPage();
  periodId = (await (await page.request.get(`${API}/periods`)).json()).find((p: { start_date: string }) => p.start_date === "2026-11-01").id;
  originalBrands = Object.fromEntries(Object.values(await emps(page)).map((e) => [e.code, e.brands]));
  await resetAll(page);
  await plan(page);
  await ctx.close();
});
test.afterAll(async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: "e2e/.auth/state.json" });
  await resetAll(await ctx.newPage());
  await ctx.close();
});

test("identité : rose exact de l'image (Display P3 0.7333 0.1529 0.3412, repli sRGB #CC0256) et blanc, même si le système est en mode sombre", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/employees");
  await expect(page.getByRole("navigation", { name: "Navigation principale" }).locator('[aria-current="page"]'))
    .toHaveCSS("background-color", /^(color\(display-p3 0\.7333 0\.1529 0\.3412\)|rgb\(204, 2, 86\))$/);
  expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe("light");
  await expect(page.locator("body")).toHaveCSS("background-color", "rgb(253, 246, 249)");
});

test("fiche : minimum et maximum de jours par mois côte à côte (1–30), jours par semaine 1–7, préférences horaires", async ({ page }) => {
  const dlg = await openSheet(page, "Zaki");
  const min = dlg.getByLabel("Minimum de jours par mois"), max = dlg.getByLabel("Maximum de jours par mois");
  await expect(min).toHaveValue(""); await expect(max).toHaveValue("");
  // mesure après l'animation d'ouverture (les animations continues, comme un squelette de chargement, et celles interrompues sont ignorées)
  await dlg.evaluate((el) => Promise.all(el.getAnimations({ subtree: true }).filter((x) => x.effect?.getComputedTiming().iterations !== Infinity).map((x) => x.finished.catch(() => null))));
  const [a, b] = [await min.boundingBox(), await max.boundingBox()];
  expect(Math.abs(a!.y - b!.y)).toBeLessThan(4); expect(b!.x).toBeGreaterThan(a!.x + a!.width - 2);
  for (const sel of [min, max]) { const opts = await sel.locator("option").allTextContents(); expect(opts[0]).toBe("Pas de préférence"); expect(opts).toHaveLength(31); expect(opts.at(-1)).toBe("30"); }
  expect(await dlg.getByLabel("Jours par semaine", { exact: true }).locator("option").allTextContents()).toEqual(["Pas de préférence", "1", "2", "3", "4", "5", "6", "7"]);
  await expect(dlg.getByTestId("days-month")).toContainText("le plafond de 176 h de travail effectif par mois (tous sites et marques cumulés) reste toujours appliqué");
  expect(await dlg.getByLabel("Préférence horaire", { exact: true }).locator("option").allTextContents()).toEqual(["Pas de préférence", "Matin", "Middle shift", "Soir"]);
  expect(await dlg.getByLabel("Nombre de dimanches").locator("option").allTextContents()).toEqual(["Pas de préférence", "0 dimanche", "1 dimanche", "2 dimanches", "3 dimanches", "4 dimanches", "5 dimanches"]);
});

test("fiche : enregistrement AUTOMATIQUE, incohérence bloquée, persistance sans rechargement", async ({ page }) => {
  const dlg = await openSheet(page, "Zaki");
  await dlg.getByLabel("Maximum de jours par mois").selectOption("10");
  await expect(saved(page)).toBeVisible();
  await dlg.getByLabel("Minimum de jours par mois").selectOption("12");
  await expect(dlg.getByText("Le minimum (12 jours) dépasse le maximum (10 jours) : corrigez l'un des deux.").first()).toBeVisible();
  expect((await emps(page)).zaki.min_days_month).toBeNull(); // rien d'enregistré tant que c'est incohérent
  await page.evaluate(() => { (window as unknown as { __m: number }).__m = 1; });
  await dlg.getByLabel("Maximum de jours par mois").selectOption("20");
  await expect.poll(async () => (await emps(page)).zaki.min_days_month).toBe(12);
  expect((await emps(page)).zaki).toMatchObject({ min_days_month: 12, max_days_month: 20 });
  await dlg.getByLabel("Jours par semaine", { exact: true }).selectOption("4");
  await expect.poll(async () => (await emps(page)).zaki.max_days_count).toBe(4);
  expect((await emps(page)).zaki).toMatchObject({ max_days_count: 4, max_days_period: "week" });
  await dlg.getByRole("button", { name: "Fermer" }).click();
  const row = page.getByRole("row", { name: /^Zaki / });
  for (const txt of ["Min 12 j / mois", "Max 20 j / mois", "Max 4 j / semaine"]) await expect(row.getByText(txt)).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { __m?: number }).__m)).toBe(1); // aucune navigation
  await putEmp(page, (await emps(page)).zaki, { brands: (await emps(page)).zaki.brands, min_days_month: null, max_days_month: null });
});

test("fiche : préférence horaire souple/stricte enregistrée automatiquement, « Pas de préférence » efface", async ({ page }) => {
  const dlg = await openSheet(page, "Kristina");
  await expect(dlg.getByRole("radio", { name: /Stricte/ })).toBeDisabled();
  await dlg.getByLabel("Préférence horaire", { exact: true }).selectOption("soir");
  await dlg.getByRole("radio", { name: /Stricte/ }).check();
  await expect(saved(page)).toBeVisible();
  expect((await emps(page)).kristina).toMatchObject({ time_pref: "soir", time_pref_strict: true });
  await dlg.getByLabel("Préférence horaire", { exact: true }).selectOption("");
  await expect.poll(async () => (await emps(page)).kristina.time_pref).toBeNull();
  expect((await emps(page)).kristina.time_pref_strict).toBe(false);
});

test("compteur des dimanches : 35 → 33 → 30 en direct, sans rechargement ni bouton d'enregistrement", async ({ page }) => {
  await page.goto("/employees");
  const restant = () => counter(page).getByText("Restant à attribuer").locator("..").locator(".kpi-value");
  await expect(restant()).toHaveText("35");
  await expect(counter(page)).toContainText("GVA3 15 · Pilar 10 · GVA9 10");
  await page.evaluate(() => { (window as unknown as { __m: number }).__m = 7; });
  let dlg = await openSheet(page, "Mila");
  await page.evaluate(() => { (window as unknown as { __m: number }).__m = 7; });
  await dlg.getByLabel("Nombre de dimanches").selectOption("2"); // mode par défaut : objectif exact, aucun autre clic
  await expect(dlg.getByTestId("sheet-counter")).toContainText("33");
  await expect(saved(page)).toBeVisible();
  await dlg.getByRole("button", { name: "Fermer" }).click();
  await expect(restant()).toHaveText("33");
  dlg = await openSheet(page, "Abdu");
  await page.evaluate(() => { (window as unknown as { __m: number }).__m = 7; });
  await dlg.getByLabel("Nombre de dimanches").selectOption("3");
  await expect(saved(page)).toBeVisible();
  await dlg.getByRole("button", { name: "Fermer" }).click();
  await expect(restant()).toHaveText("30");
  await expect(counter(page).getByText("Réservés aux collaborateurs").locator("..").locator(".kpi-value")).toHaveText("5");
  expect(await page.evaluate(() => (window as unknown as { __m?: number }).__m)).toBe(7);
  // modifier à nouveau : le restant suit immédiatement
  dlg = await openSheet(page, "Mila");
  await dlg.getByLabel("Nombre de dimanches").selectOption("1");
  await expect(saved(page)).toBeVisible();
  await dlg.getByRole("button", { name: "Fermer" }).click();
  await expect(restant()).toHaveText("31");
  // « maximum » compte aussi comme dimanche attribué
  dlg = await openSheet(page, "Mila");
  await dlg.getByRole("radio", { name: /Maximum/ }).check();
  await expect(saved(page)).toBeVisible();
  await dlg.getByRole("button", { name: "Fermer" }).click();
  await expect(restant()).toHaveText("31");
  const s = await (await page.request.get(`${API}/periods/${periodId}/sunday-summary`)).json();
  expect(s).toMatchObject({ total: 35, reserved: 4, reserved_exact: 3, reserved_max: 1, remaining_to_reserve: 31 });
});

test("calendrier d'indisponibilités : Zaki bloqué les 5, 12 et 18 nov., enregistré automatiquement, jamais planifié ces jours", async ({ page }) => {
  const dlg = await openSheet(page, "Zaki");
  const day = (n: number) => dlg.getByRole("button", { name: new RegExp(`^\\w+ ${n} nov\\. 2026`) });
  for (const n of [5, 12, 18]) await day(n).click();
  for (const n of [5, 12, 18]) await expect(day(n)).toHaveAttribute("aria-pressed", "true");
  await expect(day(6)).toHaveAttribute("aria-pressed", "false");
  await expect(saved(page)).toBeVisible();
  await expect.poll(async () => (await (await page.request.get(`${API}/employees/${(await emps(page)).zaki.id}/availability`)).json()).dates).toEqual(["2026-11-05", "2026-11-12", "2026-11-18"]);
  await day(12).click(); await expect(day(12)).toHaveAttribute("aria-pressed", "false"); // modifiable
  await day(12).click(); await expect(day(12)).toHaveAttribute("aria-pressed", "true");
  await expect.poll(async () => (await (await page.request.get(`${API}/employees/${(await emps(page)).zaki.id}/availability`)).json()).dates).toHaveLength(3);
  await dlg.getByRole("button", { name: "Fermer" }).click();
  // persistant à la réouverture
  const again = await openSheet(page, "Zaki");
  await expect(again.getByRole("button", { name: /^\w+ 5 nov\. 2026/ })).toHaveAttribute("aria-pressed", "true");
  await again.getByRole("button", { name: "Fermer" }).click();
  await plan(page);
  expect((await sched(page)).filter((a) => a.employee === "Zaki" && ["2026-11-05", "2026-11-12", "2026-11-18"].includes(a.day))).toEqual([]);
});

test("paramètres modifiés après génération : incompatibilités signalées puis réoptimisation confirmée (verrous conservés)", async ({ page }) => {
  const mine = (await sched(page)).find((a) => a.employee === "Sabrina")!;
  const token = await csrf(page);
  const sab = (await emps(page)).sabrina;
  await page.request.put(`${API}/employees/${sab.id}/unavailable-dates`, { headers: { "X-CSRF-Token": token }, data: { dates: [mine.day] } });
  await page.goto("/planning");
  const banner = page.getByText(/incompatibilités? avec les paramètres de ce planning/);
  await expect(banner).toBeVisible();
  await expect(page.getByText("Rien n'a été modifié automatiquement.")).toBeVisible();
  // détail : collaborateur, date, horaires, site, règle et raison ; obligatoire distingué des préférences
  await page.getByRole("button", { name: "Voir le détail" }).click();
  const detail = page.getByTestId("incompat-detail");
  await expect(detail.getByRole("heading", { name: "Contraintes obligatoires non respectées" })).toBeVisible();
  const line = detail.getByRole("row").filter({ hasText: "Sabrina" }).filter({ hasText: "Disponibilité du collaborateur" });
  await expect(line).toContainText(`${mine.day.slice(8, 10)}/${mine.day.slice(5, 7)}/${mine.day.slice(0, 4)}`);
  await expect(line).toContainText(`${mine.start.slice(0, 5)}–${mine.end.slice(0, 5)}`);
  await expect(line).toContainText("Sabrina est indisponible ce jour-là");
  await page.getByRole("dialog").getByRole("button", { name: "Fermer" }).last().click();
  expect((await sched(page)).some((a) => a.employee === "Sabrina" && a.day === mine.day)).toBe(true); // pas de modification silencieuse
  await page.getByRole("button", { name: "Réoptimiser…" }).click();
  const dlg = page.getByRole("dialog", { name: "Réoptimiser le planning ?" });
  await expect(dlg).toContainText("resteront exactement telles quelles");
  await dlg.getByRole("button", { name: "Confirmer la réoptimisation" }).click();
  await expect(page.getByText(/Réoptimisation terminée/)).toBeVisible({ timeout: 60_000 });
  expect((await sched(page)).some((a) => a.employee === "Sabrina" && a.day === mine.day)).toBe(false);
  await expect(banner).toBeHidden();
});

test("marques et boutiques autorisées : sélection, priorité, horaires proposés, jamais d'autre marque", async ({ page }) => {
  const dlg = await openSheet(page, "Zaki");
  const ploom = dlg.getByRole("checkbox", { name: "Ploom : toutes les boutiques" });
  if (!(await ploom.isChecked())) await ploom.check(); // groupe partiellement coché (une boutique a pu être ajoutée) : tout cocher puis tout décocher
  await ploom.uncheck();
  for (const b of ["GVA3", "GVA9", "Pilar"]) await expect(dlg.locator(".brand-shop", { hasText: b }).getByRole("checkbox")).not.toBeChecked();
  await dlg.locator(".brand-shop", { hasText: "GVA9" }).getByRole("checkbox").check(); // une boutique précise
  await dlg.getByRole("checkbox", { name: "Nuxe", exact: true }).uncheck(); await dlg.getByRole("checkbox", { name: "Cellcosmet", exact: true }).uncheck();
  await dlg.getByLabel("Priorité Cartier").selectOption("secondary");
  await expect(saved(page)).toBeVisible();
  const zaki = (await emps(page)).zaki;
  expect(zaki.brands).toEqual({ Cartier: "secondary", Valmont: "reinforce", "Ploom GVA9": "priority" });
  const sched2 = dlg.getByLabel("Horaires proposés selon les marques autorisées");
  await expect(sched2).toContainText("Cartier : 08h–17h");
  await expect(sched2).toContainText("Ploom GVA9 : 07h–16h, 12h30–21h30");
  await expect(sched2).not.toContainText("Ploom GVA3");
  await dlg.getByRole("button", { name: "Fermer" }).click();
  await plan(page);
  const brands = new Set((await sched(page)).filter((a) => a.employee === "Zaki").flatMap((a) => Object.keys(a.allocations)));
  expect([...brands].every((b) => ["Cartier", "Valmont", "Ploom GVA9"].includes(b))).toBe(true);
});

test("ajout d'un shift : seules les marques autorisées puis les horaires de la marque ; le shift est verrouillé", async ({ page }) => {
  const z = (await emps(page)).zaki;
  await putEmp(page, z, { brands: { Cartier: "priority", "Ploom GVA9": "reinforce" } });
  const used = new Set((await sched(page)).filter((a) => a.employee === "Zaki").map((a) => a.day));
  const NAMES = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
  const days = [2, 3, 4, 5, 6, 7, 8].map((n) => ({ iso: `2026-11-${String(n).padStart(2, "0")}`, label: `${NAMES[n - 2]} ${n} nov.` }));
  const blocked = new Set(((await (await page.request.get(`${API}/employees/${z.id}/availability`)).json()) as { dates: string[] }).dates); // jamais un jour d'indisponibilité
  const day = days.find((d) => !used.has(d.iso) && !blocked.has(d.iso))!;
  const free = day.iso;
  await page.goto("/planning");
  await page.getByRole("tab", { name: "Planning général" }).click();
  const LABEL: Record<string, string> = Object.fromEntries(days.map((d) => [d.iso, d.label]));
  const cell = page.locator(`.cal-cell[aria-label="Zaki, ${LABEL[free]}"]`);
  await cell.hover();
  await cell.getByRole("button", { name: /Ajouter un shift pour Zaki/ }).click();
  await page.getByRole("dialog", { name: /Ajouter un jour de travail — Zaki/ }).getByRole("button", { name: "Créer un nouveau shift" }).click();
  const dlg = page.getByRole("dialog", { name: /Ajouter un shift — Zaki/ });
  expect(await dlg.getByLabel("Marque ou boutique").locator("option").allTextContents()).toEqual(["Cartier — Prioritaire", "Ploom GVA9 — Renfort"]);
  await dlg.getByLabel("Marque ou boutique").selectOption("Cartier");
  await expect(dlg.getByLabel("Horaire", { exact: true }).locator("option")).toHaveCount(1);
  await expect(dlg.getByLabel("Horaire", { exact: true })).toContainText("08h00–17h00");
  await dlg.getByLabel("Marque ou boutique").selectOption("Ploom GVA9");
  await expect(dlg.getByLabel("Horaire", { exact: true }).locator("option")).toHaveText([
    "07h00–16h00 · GVA9 · 1 h de pause = 8 h effectives", "12h30–21h30 · GVA9 · 1 h de pause = 8 h effectives"]);
  await dlg.getByLabel("Marque ou boutique").selectOption("Cartier");
  await dlg.getByRole("button", { name: "Ajouter le shift" }).click();
  await expect(page.getByText(/Shift ajouté pour Zaki/)).toBeVisible();
  const added = (await sched(page)).find((a) => a.employee === "Zaki" && a.day === free && a.site === "Cartier")!;
  expect(added).toMatchObject({ start: "08:00:00", end: "17:00:00", locked: true });
  // nettoyage
  const token = await csrf(page);
  await page.request.post(`${API}/assignments/${added.assignment_id}/unlock`, { headers: { "X-CSRF-Token": token } });
  await page.request.delete(`${API}/assignments/${added.assignment_id}`, { headers: { "X-CSRF-Token": token } });
});

test("une marque non autorisée ne peut pas être attribuée : sélecteur désactivé", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/planning");
  await page.getByRole("tab", { name: "Jour" }).click();
  const row = page.getByLabel(/Collaborateur pour GVA3 06:00–15:00/);
  await expect(row.locator("option", { hasText: "Aziza — marque non autorisée" })).toBeDisabled();
});

test("planning : compteur visible", async ({ page }) => {
  await page.goto("/planning");
  await expect(counter(page).first()).toContainText("à couvrir");
});

// ---------- gestion manuelle depuis le calendrier du collaborateur ----------
type Row = Awaited<ReturnType<typeof sched>>[number];
/** Un shift non verrouillé occupé par A, et un collaborateur B autorisé sur ses marques, sans shift la veille, le jour même ni le lendemain. */
async function findCase(page: Page): Promise<{ a: Row; to: Emp }> {
  const rows = await sched(page), all = Object.values(await emps(page));
  const sunday = (iso: string) => new Date(iso + "T12:00:00Z").getUTCDay() === 0;
  for (const a of rows) {
    if (a.locked || sunday(a.day) || a.day < "2026-11-03" || a.day > "2026-11-27") continue;
    const near = new Set(rows.filter((x) => Math.abs(Number(x.day.slice(8)) - Number(a.day.slice(8))) <= 1).map((x) => x.employee));
    for (const to of all.filter((e) => e.active && !near.has(e.name) && e.code !== "sabrina" && Object.keys(a.allocations).every((b) => b in e.brands))) {
      // cas valide selon le serveur lui-même (même contrôle que l'écran) : aucune alerte pour ce transfert. Le planning généré varie
      // d'une génération à l'autre ; deviner le cas sur les seuls jours voisins a déjà choisi un collaborateur à son maximum de jours
      // par semaine (constaté le 19/11).
      const d = (await (await page.request.get(`${API}/periods/${periodId}/day-shifts?day=${a.day}&employee_id=${to.id}`)).json()) as { shifts: { assignment_id: string | null; issues: unknown[] }[] };
      if (d.shifts.find((x) => x.assignment_id === a.assignment_id)?.issues.length === 0) return { a, to };
    }
  }
  throw new Error("aucun cas de test");
}
async function openDay(page: Page, name: string, iso: string) {
  await page.goto("/planning");
  await page.waitForLoadState("networkidle");
  await page.getByRole("tab", { name: "Collaborateur" }).click();
  await page.getByLabel("Collaborateur", { exact: true }).last().selectOption({ label: name });
  await page.getByRole("button", { name: new RegExp(`Ajouter un jour de travail pour ${name}, \\S+ ${Number(iso.slice(8))} nov`) }).click();
  const dlg = page.getByRole("dialog", { name: new RegExp(`Ajouter un jour de travail — ${name}`) });
  await expect(dlg).toBeVisible();
  return dlg;
}

test("calendrier d'un collaborateur : transfert d'un shift occupé, planning général et historique mis à jour sans rechargement", async ({ page }) => {
  const { a, to } = await findCase(page);
  const dlg = await openDay(page, to.name, a.day);
  const row = dlg.getByRole("button", { name: new RegExp(`^Transférer de ${a.employee} à ${to.name}`) }).first();
  await expect(row).toContainText(a.employee);
  await row.click();
  await expect(dlg.getByText(new RegExp(`Transférer ce shift de ${a.employee} à ${to.name}`))).toBeVisible();
  await dlg.getByRole("button", { name: "Confirmer le transfert" }).click();
  await expect(page.getByText(new RegExp(`transféré à ${to.name}`))).toBeVisible();
  const moved = (await sched(page)).filter((x) => x.day === a.day && x.start === a.start && x.site === a.site);
  expect(moved.map((x) => x.employee)).toContain(to.name);
  expect(moved.filter((x) => x.employee === a.employee && x.allocations && JSON.stringify(x.allocations) === JSON.stringify(a.allocations))).toHaveLength(0);
  // le calendrier du collaborateur affiche immédiatement le shift (aucun rechargement de page)
  await expect(page.locator(".month-cell").nth(6 + Number(a.day.slice(8)) - 1)).toContainText(a.site); // 1er nov. 2026 = dimanche
  await page.getByRole("button", { name: "Historique" }).click();
  const hist = page.getByRole("dialog", { name: "Historique des modifications" });
  await expect(hist.getByRole("list", { name: "Historique des modifications" }).locator("li").first()).toContainText(`${a.employee} → ${to.name}`);
});

test("contrainte détectée : alerte claire, « Annuler » laisse le planning inchangé, « Accepter quand même » enregistre la dérogation", async ({ page }) => {
  const { a, to } = await findCase(page);
  const token = await csrf(page);
  await page.request.put(`${API}/employees/${to.id}/unavailable-dates`, { headers: { "X-CSRF-Token": token }, data: { dates: [a.day] } });
  const before = JSON.stringify((await sched(page)).map((x) => [x.assignment_id, x.employee]).sort());
  const dlg = await openDay(page, to.name, a.day);
  await dlg.getByRole("button", { name: new RegExp(`^Transférer de ${a.employee} à ${to.name}`) }).first().click();
  await dlg.getByRole("button", { name: "Confirmer le transfert" }).click();
  const alert = dlg.getByRole("alertdialog", { name: "Contraintes détectées" });
  await expect(alert).toContainText("indisponible");
  await expect(alert).toContainText("Valeur autorisée"); await expect(alert).toContainText("Valeur atteinte"); await expect(alert).toContainText("Conséquence");
  await expect(alert.getByRole("button", { name: "Accepter quand même" })).toBeVisible();
  await alert.getByRole("button", { name: "Annuler" }).click();
  expect(JSON.stringify((await sched(page)).map((x) => [x.assignment_id, x.employee]).sort())).toBe(before);
  await dlg.getByRole("button", { name: new RegExp(`^Transférer de ${a.employee} à ${to.name}`) }).first().click();
  await dlg.getByRole("button", { name: "Confirmer le transfert" }).click();
  await alert.getByLabel(/Motif de la dérogation/).fill("Remplacement de dernière minute");
  await alert.getByRole("button", { name: "Accepter quand même" }).click();
  await expect(page.getByText(new RegExp(`transféré à ${to.name}`))).toBeVisible();
  expect((await sched(page)).some((x) => x.employee === to.name && x.day === a.day)).toBe(true);
  await page.getByRole("button", { name: "Historique" }).click();
  const first = page.getByRole("dialog", { name: "Historique des modifications" }).getByRole("list", { name: "Historique des modifications" }).locator("li").first();
  await expect(first).toContainText("Dérogation");
  await expect(first).toContainText("Remplacement de dernière minute");
});

test("retrait : « Retirer du planning » rend le shift disponible dans la fenêtre du jour", async ({ page }) => {
  const rows = (await sched(page)).filter((x) => !x.locked && x.day >= "2026-11-10");
  const a = rows[0];
  await page.goto("/planning");
  await page.waitForLoadState("networkidle");
  await page.waitForLoadState("networkidle");
  await page.getByRole("tab", { name: "Collaborateur" }).click();
  await page.getByLabel("Collaborateur", { exact: true }).last().selectOption({ label: a.employee });
  await page.locator(".month-cell").nth(6 + Number(a.day.slice(8)) - 1).locator(".shift").first().click();
  await page.getByRole("button", { name: "Retirer du planning" }).click();
  await page.getByRole("button", { name: "Retirer le shift" }).click();
  await expect(page.getByText(/de nouveau disponible/)).toBeVisible();
  expect((await sched(page)).some((x) => x.assignment_id === a.assignment_id)).toBe(false);
});
