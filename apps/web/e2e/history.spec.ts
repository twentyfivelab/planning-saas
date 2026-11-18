import { expect, test, type Page } from "@playwright/test";
import { API, getJson as j } from "./api";

// Historique des modifications : langage simple, date de modification et date du shift distinctes, filtres, opération groupée avec
// détail, accès depuis le planning et la fiche collaborateur, persistance après actualisation. Données remises en l'état.
test.skip(!process.env.E2E_EMAIL, "E2E_EMAIL non défini");
test.describe.configure({ mode: "serial" });

type Row = { assignment_id: string; shift_id: string; employee_id: string; employee: string; day: string; start: string; end: string; locked: boolean;
  effective_minutes: number; allocations: Record<string, number>; site: string };
type Emp = { id: string; name: string; brands: Record<string, string>; deleted_at?: string | null };
const csrf = async (page: Page) => (await j(page, "/auth/me")).csrf_token as string;
const nov = async (page: Page) => ((await j(page, "/periods")) as { id: string; start_date: string }[]).find((p) => p.start_date === "2026-11-01")!.id;

async function pickTransfers(page: Page, pid: string, n: number) {
  const rows = (await j(page, `/periods/${pid}/schedule`)).assignments as Row[];
  const emps = ((await j(page, "/employees")) as Emp[]).filter((e) => !e.deleted_at);
  const used: Record<string, number> = {};
  for (const a of rows) used[a.employee_id] = (used[a.employee_id] ?? 0) + a.effective_minutes;
  for (const src of emps) {
    const mine = rows.filter((r) => r.employee_id === src.id && !r.locked);
    for (const to of emps) {
      if (to.id === src.id) continue;
      const busy = new Set(rows.filter((r) => r.employee_id === to.id).map((r) => r.day));
      const ok = mine.filter((r) => !busy.has(r.day) && Object.keys(r.allocations).every((b) => b in (to.brands ?? {}))).slice(0, n);
      if (ok.length === n && used[to.id] + ok.reduce((s, r) => s + r.effective_minutes, 0) <= 176 * 60) return { src, to, shifts: ok };
    }
  }
  throw new Error("aucun transfert possible");
}

test("historique : remplacement et opération groupée en langage simple, filtres, détail, persistance", async ({ page }) => {
  const pid = await nov(page);
  const token = await csrf(page);
  const me = (await j(page, "/auth/me")) as { name: string };
  const { src, to, shifts } = await pickTransfers(page, pid, 3);
  // 1) un remplacement simple, puis 2) une modification groupée de deux shifts
  const one = await page.request.post(`${API}/periods/${pid}/manual-assign`, { headers: { "X-CSRF-Token": token }, data: { employee_id: to.id, shift_id: shifts[0].shift_id, force: true, reason: "essai e2e" } });
  expect(one.status(), await one.text()).toBe(200);
  const bulk = await page.request.post(`${API}/periods/${pid}/bulk-transfer`, { headers: { "X-CSRF-Token": token },
    data: { operations: shifts.slice(1).map((r) => ({ assignment_id: r.assignment_id, to_employee_id: to.id })), force: true } });
  expect(bulk.status(), await bulk.text()).toBe(200);
  try {
    await page.goto("/history"); await page.waitForLoadState("networkidle");
    const feed = page.getByTestId("history-feed");
    const events = feed.getByTestId("history-event");
    const grouped = events.first();
    await expect(grouped).toContainText("Modification groupée : 2 shifts");
    await expect(grouped).toContainText(`Effectué par : ${me.name}`);
    await expect(grouped).toContainText("Date du shift : du ");
    await grouped.getByText("Voir le détail (2)").click();
    await expect(grouped.locator(".history-details li")).toHaveCount(2);
    const repl = events.nth(1);
    await expect(repl).toContainText(`Remplacement`);
    await expect(repl).toContainText(`${src.name} → ${to.name}`);
    const d = new Date(`${shifts[0].day}T12:00:00Z`);
    await expect(repl).toContainText(`Date du shift : `);
    await expect(repl).toContainText(`${d.getUTCDate()} novembre 2026`);
    await expect(repl).toContainText("Motif : essai e2e");
    await expect(repl.locator("time")).toHaveText(/ à \d\d:\d\d$/); // date de modification, heure du fuseau de l'entreprise
    // filtres : type d'action, collaborateur
    await feed.getByLabel("Type d'action").selectOption("replace");
    await expect(events.first()).toContainText(`${src.name} → ${to.name}`);
    for (const k of await events.evaluateAll((els) => els.map((e) => e.getAttribute("data-kind")))) expect(k).toBe("replace");
    await feed.getByRole("button", { name: "Effacer les filtres" }).click();
    await feed.getByLabel("Collaborateur").selectOption(to.id);
    await expect(events.first()).toContainText("Modification groupée");
    // persistance après actualisation
    await page.reload(); await page.waitForLoadState("networkidle");
    await expect(page.getByTestId("history-event").first()).toContainText("Modification groupée : 2 shifts");
    // mobile : lisible, sans débordement
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
  } finally {
    const back = await page.request.post(`${API}/periods/${pid}/bulk-transfer`, { headers: { "X-CSRF-Token": token },
      data: { operations: shifts.map((r) => ({ assignment_id: r.assignment_id, to_employee_id: src.id })), force: true, reason: "remise en l'état e2e" } });
    expect(back.status(), await back.text()).toBe(200);
    for (const r of shifts) if (!r.locked) await page.request.post(`${API}/assignments/${r.assignment_id}/unlock`, { headers: { "X-CSRF-Token": token } });
  }
});

test("historique depuis le planning (mois affiché) et depuis la fiche collaborateur", async ({ page }) => {
  const pid = await nov(page);
  const ev = (await j(page, `/history?period_id=${pid}&limit=1`)) as { items: { title: string; employees: { id: string; name: string }[] }[] };
  expect(ev.items.length).toBe(1);
  await page.goto("/planning"); await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "Historique" }).click();
  const dlg = page.getByRole("dialog", { name: "Historique des modifications" });
  await expect(dlg.getByTestId("history-event").first()).toContainText(ev.items[0].title);
  await expect(dlg.getByRole("link", { name: "Ouvrir l'historique complet" })).toHaveAttribute("href", new RegExp(`period=${pid}`));
  await page.keyboard.press("Escape");
  const who = ev.items[0].employees[0];
  test.skip(!who, "événement sans collaborateur");
  await page.goto("/employees"); await page.waitForLoadState("networkidle");
  await page.getByRole("row", { name: new RegExp(`^${who.name} `) }).getByRole("button", { name: "Fiche" }).click();
  const sheet = page.getByRole("dialog", { name: `Fiche — ${who.name}` });
  const h = sheet.getByTestId("employee-history");
  await h.scrollIntoViewIfNeeded();
  await expect(h.getByTestId("history-event").first()).toBeVisible();
  await expect(h.getByRole("link", { name: `Tout l'historique de ${who.name}` })).toHaveAttribute("href", `/history?employee=${who.id}`);
});

test("paramètres : réglages courants visibles, options techniques dans « Paramètres avancés », valeurs inchangées", async ({ page }) => {
  const before = await j(page, "/settings/weights");
  await page.goto("/settings"); await page.waitForLoadState("networkidle");
  await expect(page.getByRole("heading", { name: "Paramètres", level: 1 })).toBeVisible();
  await expect(page.getByTestId("weight-family")).toBeVisible(); // priorités courantes
  const adv = page.getByTestId("advanced-settings");
  await expect(adv.getByTestId("raw-weights")).toBeHidden(); // replié par défaut
  await adv.getByText("Paramètres avancés").click();
  await expect(adv.getByTestId("raw-weights")).toBeVisible();
  await expect(adv.getByText("Optimisation hiérarchisée")).toBeVisible();
  expect(await j(page, "/settings/weights")).toEqual(before); // ouvrir les écrans ne change aucune règle ni priorité
});
