import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";
import { API, getJson as j } from "./api";

// Espace collaborateur : demandes (congé, absence partielle, échange) et décision du responsable. Comptes collaborateurs créés pour le test,
// désactivés à la fin ; données remises en l'état (aucun congé approuvé, absence retirée, échange inversé).
test.skip(!process.env.E2E_EMAIL, "E2E_EMAIL non défini");
test.describe.configure({ mode: "serial" });

type Row = { assignment_id: string; employee_id: string; day: string; locked: boolean };
const PW = `Essai-${Math.random().toString(36).slice(2)}-Aa1!`;
const users: { id: string; email: string; employee_id: string; name: string }[] = [];
const csrf = async (page: Page) => (await j(page, "/auth/me")).csrf_token as string;

async function as(browser: Browser, email: string): Promise<{ ctx: BrowserContext; page: Page }> {
  const ctx = await browser.newContext();
  const r = await ctx.request.post(`${API}/auth/login`, { data: { email, password: PW } });
  expect(r.status(), await r.text()).toBe(200);
  return { ctx, page: await ctx.newPage() };
}

test.beforeAll(async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: "e2e/.auth/state.json" });
  const page = await ctx.newPage();
  const token = await csrf(page);
  const pid = ((await j(page, "/periods")) as { id: string; start_date: string }[]).find((p) => p.start_date === "2026-11-01")!.id;
  const rows = (await j(page, `/periods/${pid}/schedule`)).assignments as Row[];
  const emps = ((await j(page, "/employees")) as { id: string; name: string; deleted_at: string | null }[]).filter((e) => !e.deleted_at && rows.some((r) => r.employee_id === e.id));
  const tag = Date.now().toString(36);
  // deux collaborateurs qui ont chacun un shift un jour où l'autre ne travaille pas (nécessaire au test d'échange)
  const days = (id: string) => new Set(rows.filter((r) => r.employee_id === id).map((r) => r.day));
  let pair = emps.slice(0, 2);
  outer: for (const x of emps) for (const y of emps) {
    if (x.id === y.id) continue;
    const dx = days(x.id), dy = days(y.id);
    const onlyX = [...dx].filter((d) => !dy.has(d)), onlyY = [...dy].filter((d) => !dx.has(d));
    if (onlyX.length && onlyY.some((d) => d !== onlyX[0])) { pair = [x, y]; break outer; }
  }
  for (const e of pair) {
    const email = `collab-${tag}-${users.length}@e2e.example`;
    const r = await page.request.post(`${API}/users`, { headers: { "X-CSRF-Token": token }, data: { email, name: e.name, role: "employee", password: PW, employee_id: e.id } });
    expect(r.status(), await r.text()).toBe(201);
    users.push({ id: (await r.json()).id, email, employee_id: e.id, name: e.name });
  }
  await ctx.close();
});

test.afterAll(async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: "e2e/.auth/state.json" });
  const page = await ctx.newPage();
  const token = await csrf(page);
  for (const u of users) await page.request.patch(`${API}/users/${u.id}`, { headers: { "X-CSRF-Token": token }, data: { is_active: false } });
  await ctx.close();
});

test("congé demandé depuis « Mon planning », refusé avec un message par le responsable", async ({ browser, page }) => {
  const c = await as(browser, users[0].email);
  await c.page.goto("/me"); await c.page.waitForLoadState("networkidle");
  const box = c.page.getByTestId("my-requests");
  await box.getByLabel("Du").fill("2027-03-10");
  await box.getByLabel("Au").fill("2027-03-12");
  await box.getByLabel("Message (facultatif)").fill("voyage");
  await box.getByRole("button", { name: "Envoyer" }).click();
  await expect(box.getByTestId("my-request").first()).toContainText("En attente du responsable");

  await page.goto("/requests"); await page.waitForLoadState("networkidle");
  const card = page.getByTestId("request").filter({ hasText: users[0].name }).filter({ hasText: "10/03/2027" });
  await expect(card).toContainText("Aucun shift concerné");
  await card.getByLabel("Message au collaborateur (facultatif)").fill("période d'inventaire");
  await card.getByRole("button", { name: "Refuser" }).click();
  await expect(card).toBeHidden(); // plus « à traiter »

  await c.page.reload(); await c.page.waitForLoadState("networkidle");
  await expect(box.getByTestId("my-request").first()).toContainText("Refusée");
  await expect(box.getByTestId("my-request").first()).toContainText("période d'inventaire");
  expect(((await j(page, "/leaves")) as { employee_id: string }[]).some((l) => l.employee_id === users[0].employee_id)).toBe(false); // rien d'appliqué
  await c.ctx.close();
});

test("absence sur une partie de la journée approuvée : appliquée comme absence partielle", async ({ browser, page }) => {
  const c = await as(browser, users[0].email);
  await c.page.goto("/me"); await c.page.waitForLoadState("networkidle");
  const box = c.page.getByTestId("my-requests");
  await box.getByLabel("Type de demande").selectOption("absence");
  await box.getByLabel("Jour", { exact: true }).fill("2027-03-15");
  await box.getByLabel("Une partie de la journée").check();
  await box.getByLabel("Heure de début").fill("09:00");
  await box.getByLabel("Heure de fin").fill("11:00");
  await box.getByRole("button", { name: "Envoyer" }).click();
  await expect(box.getByTestId("my-request").first()).toContainText("de 09:00 à 11:00");

  await page.goto("/requests"); await page.waitForLoadState("networkidle");
  const card = page.getByTestId("request").filter({ hasText: users[0].name }).filter({ hasText: "15/03/2027" });
  await card.getByRole("button", { name: "Approuver" }).click();
  await expect(card).toBeHidden();
  const pa = ((await j(page, "/partial-absences")) as { id: string; employee_id: string; on_date: string }[]).find((x) => x.employee_id === users[0].employee_id && x.on_date === "2027-03-15");
  expect(pa).toBeTruthy();
  await page.request.delete(`${API}/partial-absences/${pa!.id}`, { headers: { "X-CSRF-Token": await csrf(page) } }); // remise en l'état
  await c.ctx.close();
});

test("indisponibilités hebdomadaires demandées (cases pré-remplies), décision du responsable", async ({ browser, page }) => {
  const u = users[1];
  const current = ((await j(page, `/employees/${u.employee_id}/availability`)) as { weekdays: number[] }).weekdays;
  const c = await as(browser, u.email);
  await c.page.goto("/me"); await c.page.waitForLoadState("networkidle");
  const box = c.page.getByTestId("my-requests");
  await box.getByLabel("Type de demande").selectOption("availability");
  const group = box.getByRole("group", { name: "Jours où je ne peux pas travailler chaque semaine" });
  const days = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
  for (let i = 0; i < 7; i++) await expect(group.getByRole("checkbox", { name: days[i] })).toBeChecked({ checked: current.includes(i) }); // valeurs actuelles
  await expect(box.getByRole("button", { name: "Envoyer" })).toBeDisabled(); // rien de changé : rien à demander
  const target = current.includes(6) ? 5 : 6;
  await group.getByRole("checkbox", { name: days[target] }).check();
  await box.getByRole("button", { name: "Envoyer" }).click();
  await expect(box.getByTestId("my-request").first()).toContainText("Indisponibilités hebdomadaires");
  await page.goto("/requests"); await page.waitForLoadState("networkidle");
  const card = page.getByTestId("request").filter({ hasText: "Disponibilités" }).filter({ hasText: u.name });
  await expect(card).toContainText("prochains plannings");
  await card.getByRole("button", { name: "Refuser" }).click();
  await expect(card).toBeHidden();
  expect(((await j(page, `/employees/${u.employee_id}/availability`)) as { weekdays: number[] }).weekdays).toEqual(current); // refus : fiche inchangée
  await c.ctx.close();
});

test("échange proposé, accepté par le collègue, approuvé par le responsable", async ({ browser, page }) => {
  const pid = ((await j(page, "/periods")) as { id: string; start_date: string }[]).find((p) => p.start_date === "2026-11-01")!.id;
  const rows = (await j(page, `/periods/${pid}/schedule`)).assignments as Row[];
  const [u1, u2] = users;
  const a = rows.find((r) => r.employee_id === u1.employee_id && !rows.some((x) => x.employee_id === u2.employee_id && x.day === r.day))!;
  const b = rows.find((r) => r.employee_id === u2.employee_id && r.day !== a.day && !rows.some((x) => x.employee_id === u1.employee_id && x.day === r.day))!;
  const c1 = await as(browser, u1.email);
  await c1.page.goto("/me"); await c1.page.waitForLoadState("networkidle");
  const box = c1.page.getByTestId("my-requests");
  await box.getByLabel("Type de demande").selectOption("swap");
  await box.getByLabel("Mon shift du").fill(a.day);
  await box.getByLabel("Avec").selectOption(u2.employee_id);
  await box.getByLabel("Son shift du").fill(b.day);
  await box.getByRole("button", { name: "Envoyer" }).click();
  await expect(box.getByTestId("my-request").first()).toContainText("En attente du collègue");

  const c2 = await as(browser, u2.email);
  await c2.page.goto("/me"); await c2.page.waitForLoadState("networkidle");
  const rec = c2.page.getByTestId("received-request").filter({ hasText: u1.name });
  await rec.getByRole("button", { name: "Accepter" }).click();
  await expect(rec).toBeHidden();

  await page.goto("/requests"); await page.waitForLoadState("networkidle");
  const card = page.getByTestId("request").filter({ hasText: "Échange" }).filter({ hasText: u1.name });
  const resp = page.waitForResponse((r) => r.url().includes("/decide") && r.request().method() === "POST");
  await card.getByRole("button", { name: "Approuver" }).click();
  await resp;
  const confirm = card.getByRole("button", { name: "Confirmer et approuver" });
  if (await confirm.isVisible().catch(() => false)) await confirm.click(); // mêmes alertes qu'un échange fait à l'écran
  await expect(card).toBeHidden();
  const now = new Map(((await j(page, `/periods/${pid}/schedule`)).assignments as Row[]).map((r) => [r.assignment_id, r.employee_id]));
  expect([now.get(a.assignment_id), now.get(b.assignment_id)]).toEqual([u2.employee_id, u1.employee_id]);
  // remise en l'état
  const token = await csrf(page);
  const back = await page.request.post(`${API}/periods/${pid}/swap`, { headers: { "X-CSRF-Token": token }, data: { a: a.assignment_id, b: b.assignment_id, force: true, reason: "remise en l'état e2e" } });
  expect(back.status(), await back.text()).toBe(200);
  for (const r of [a, b]) if (!r.locked) await page.request.post(`${API}/assignments/${r.assignment_id}/unlock`, { headers: { "X-CSRF-Token": token } });
  await c1.ctx.close(); await c2.ctx.close();
});
