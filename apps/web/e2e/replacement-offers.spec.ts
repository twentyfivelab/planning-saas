import { expect, test, type Browser, type Page } from "@playwright/test";
import { API, getJson as j } from "./api";

// Propositions de remplacement : le manager propose depuis les remplaçants classés ; le collaborateur répond dans « Mon espace ».
// L'affectation actuelle reste en place jusqu'à l'acceptation validée. Mois dédié (février 2028), compte collaborateur créé pour le
// test puis désactivé, planning supprimé à la fin : aucun autre test n'en dépend.
test.skip(!process.env.E2E_EMAIL || !process.env.E2E_PASSWORD, "E2E_EMAIL / E2E_PASSWORD non définis");
test.describe.configure({ mode: "serial" });

const csrf = async (page: Page) => (await j(page, "/auth/me")).csrf_token as string;
type A = { assignment_id: string; shift_id: string; employee_id: string; day: string };
type Cand = { employee_uuid: string | null; name: string; status: string; has_account?: boolean };
const PW = `Remplacement-${Date.now().toString(36)}-Aa9!`;
let pid = ""; let userId = ""; let email = ""; let candId = ""; let candName = "";

test.beforeAll(async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: "e2e/.auth/state.json" });
  const page = await ctx.newPage();
  const token = await csrf(page);
  pid = (await (await page.request.post(`${API}/periods/ensure`, { headers: { "X-CSRF-Token": token }, data: { year: 2028, month: 2 } })).json()).id;
  if (!((await j(page, `/periods/${pid}/schedule`)).assignments as unknown[]).length) {
    const run = await page.request.post(`${API}/periods/${pid}/runs`, { headers: { "X-CSRF-Token": token, "Idempotency-Key": `rep-${Date.now()}` }, data: { time_limit_s: 10 } });
    expect(run.status(), await run.text()).toBe(202);
    await expect.poll(async () => ((await j(page, `/periods/${pid}/schedule`)).assignments as unknown[]).length, { timeout: 50_000 }).toBeGreaterThan(0);
  }
  await ctx.close();
});

test.afterAll(async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: "e2e/.auth/state.json" });
  const page = await ctx.newPage();
  const token = await csrf(page);
  if (userId) await page.request.patch(`${API}/users/${userId}`, { headers: { "X-CSRF-Token": token }, data: { is_active: false } });
  await page.request.post(`${API}/periods/${pid}/delete`, { headers: { "X-CSRF-Token": token }, data: { password: process.env.E2E_PASSWORD } });
  await ctx.close();
});

async function openFeb(page: Page) {
  await page.goto("/planning");
  await page.evaluate(() => { try { localStorage.setItem("planning:month", "2028-02"); } catch { /* ignoré */ } });
  await page.reload(); await page.waitForLoadState("networkidle");
}

async function openReplacements(page: Page) {
  const shift = page.getByRole("region", { name: /Planning général/ }).locator(".shift").first();
  await shift.click();
  const ranked = page.waitForResponse((r) => /\/shifts\/[0-9a-f-]+\/replacements$/.test(new URL(r.url()).pathname));
  await page.getByRole("button", { name: "Voir les remplaçants" }).click();
  const res = await ranked;
  const sid = new URL(res.url()).pathname.split("/")[2];
  return { sid, ranking: (await res.json()) as { candidates: Cand[]; holder_id: string | null } };
}

async function loginAs(browser: Browser, mail: string, pw: string) {
  const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const p = await ctx.newPage();
  await p.goto("/login");
  await p.getByLabel("E-mail").fill(mail); await p.getByLabel("Mot de passe").fill(pw);
  await p.getByRole("button", { name: "Se connecter" }).click();
  await p.waitForURL((u) => !u.pathname.startsWith("/login"));
  return { ctx, p };
}

test("proposer, accepter (double clic) : titulaire conservé pendant l'attente, puis un seul transfert", async ({ page, browser }) => {
  const token = await csrf(page); const H = { "X-CSRF-Token": token };
  await page.setViewportSize({ width: 1440, height: 1100 });
  await openFeb(page);
  let { sid, ranking } = await openReplacements(page);
  // un candidat compatible SANS compte : le test crée son compte (mot de passe connu du test uniquement)
  const c = ranking.candidates.find((x) => x.status === "compatible" && x.employee_uuid && !x.has_account);
  test.skip(!c, "tous les candidats compatibles ont déjà un compte");
  candId = c!.employee_uuid!; candName = c!.name;
  const dlg = page.getByRole("dialog", { name: "Remplaçants proposés" });
  await expect(dlg.getByText("Sans compte : proposition impossible").first()).toBeVisible(); // sans compte : impossible, et dit clairement
  email = `remplacant-${Date.now().toString(36)}@e2e.example`;
  const u = await page.request.post(`${API}/users`, { headers: H, data: { email, name: candName, role: "employee", password: PW, employee_id: candId } });
  expect(u.status(), await u.text()).toBe(201);
  userId = (await u.json()).id;
  await dlg.getByRole("button", { name: "Fermer" }).last().click();
  ({ sid, ranking } = await openReplacements(page));
  const holderBefore = ((await j(page, `/periods/${pid}/schedule`)).assignments as A[]).find((a) => a.shift_id === sid)!;
  await dlg.getByRole("button", { name: `Proposer à ${candName}` }).click();
  const form = page.getByTestId("propose-form");
  await form.getByLabel("Délai de réponse").selectOption("240");
  await expect(form.getByTestId("propose-deadline")).toContainText("Réponse attendue avant le");
  await form.getByRole("button", { name: "Envoyer la proposition" }).click();
  await expect(dlg.getByTestId("proposal-status")).toContainText(`Proposé à ${candName} — réponse avant le`);
  await expect(dlg.getByTestId("proposal-status")).toContainText("reste affecté tant que le remplacement n'est pas accepté et validé");
  const during = ((await j(page, `/periods/${pid}/schedule`)).assignments as A[]).filter((a) => a.shift_id === sid);
  expect(during.map((a) => a.employee_id)).toEqual([holderBefore.employee_id]); // titulaire en place pendant l'attente
  await dlg.getByRole("button", { name: "Fermer" }).last().click();
  await page.reload(); await page.waitForLoadState("networkidle");
  await expect(page.getByTestId("period-proposals")).toContainText(`Proposé à ${candName}`);
  // le collaborateur se connecte : notification et proposition détaillée (persistantes)
  const { ctx, p } = await loginAs(browser, email, PW);
  await p.goto("/me"); await p.waitForLoadState("networkidle");
  const offer = p.getByTestId("my-offer").filter({ has: p.getByRole("button", { name: "Accepter" }) });
  await expect(offer).toHaveCount(1);
  await expect(offer).toContainText("Réponse attendue avant le");
  await expect(p.getByTestId("notification").filter({ hasText: "Proposition de remplacement" }).first()).toBeVisible();
  await offer.getByRole("button", { name: "Accepter" }).dblclick(); // double clic : une seule acceptation
  await expect(p.getByTestId("offer-result").first()).toContainText("C'est noté : vous reprenez le shift");
  await expect(p.getByTestId("my-offer").first()).toHaveAttribute("data-status", "accepted");
  await ctx.close();
  const after = ((await j(page, `/periods/${pid}/schedule`)).assignments as A[]).filter((a) => a.shift_id === sid);
  expect(after.map((a) => [a.assignment_id, a.employee_id])).toEqual([[holderBefore.assignment_id, candId]]);
  // manager : notification, historique avec auteurs
  const notes = (await j(page, "/notifications")).items as { kind: string; body: string }[];
  expect(notes.filter((n) => n.kind === "replacement_update" && n.body.includes(`${candName} a accepté`))).toHaveLength(1);
  await page.goto("/history?kind=proposal"); await page.waitForLoadState("networkidle");
  await expect(page.getByTestId("history-event").first()).toContainText(`Proposition acceptée par ${candName}`);
});

test("refus puis annulation : le shift n'est jamais laissé vacant", async ({ page, browser }) => {
  const token = await csrf(page); const H = { "X-CSRF-Token": token };
  test.skip(!email, "compte du candidat non créé par ce test (déjà relié) : scénario couvert par l'API");
  const rows = (await j(page, `/periods/${pid}/schedule`)).assignments as A[];
  // deux autres shifts pour lesquels le candidat est compatible, un autre jour que ses shifts
  const mine = new Set(rows.filter((a) => a.employee_id === candId).map((a) => a.day));
  const picks: A[] = [];
  for (const a of rows) {
    if (picks.length === 2 || mine.has(a.day) || picks.some((x) => x.day === a.day)) continue;
    const rk = (await j(page, `/shifts/${a.shift_id}/replacements`)) as { candidates: Cand[] };
    if (rk.candidates.some((c) => c.employee_uuid === candId && c.status === "compatible")) picks.push(a);
  }
  test.skip(picks.length < 2, "pas assez de shifts proposables au candidat");
  for (const a of picks) expect((await page.request.post(`${API}/shifts/${a.shift_id}/replacement-requests`, { headers: H, data: { start_employee_id: candId, response_minutes: 60 } })).status()).toBe(201);
  const { ctx, p } = await loginAs(browser, email, PW);
  await p.goto("/me"); await p.waitForLoadState("networkidle");
  const pending = p.getByTestId("my-offer").filter({ has: p.getByRole("button", { name: "Refuser" }) });
  await expect(pending).toHaveCount(2);
  await pending.first().getByRole("button", { name: "Refuser" }).click();
  await p.getByRole("dialog", { name: "Refuser cette proposition ?" }).getByLabel("Motif (facultatif)").fill("déjà pris ce jour-là");
  await p.getByRole("dialog", { name: "Refuser cette proposition ?" }).getByRole("button", { name: "Refuser" }).click();
  await expect(p.getByTestId("offer-result").first()).toContainText("vous ne reprenez pas ce shift");
  // le manager annule l'autre depuis le planning
  await openFeb(page);
  const panel = page.getByTestId("period-proposals");
  await expect(panel).toBeVisible();
  // le refus a pu solliciter le candidat suivant : toutes les propositions encore ouvertes sont annulées
  while (await panel.getByRole("button", { name: "Annuler la proposition" }).count()) {
    const before = await panel.getByRole("button", { name: "Annuler la proposition" }).count();
    await panel.getByRole("button", { name: "Annuler la proposition" }).first().click();
    await page.getByRole("dialog", { name: "Annuler la proposition de remplacement ?" }).getByRole("button", { name: "Annuler la proposition" }).click();
    await expect(panel.getByRole("button", { name: "Annuler la proposition" })).toHaveCount(before - 1);
    if (before === 1) break;
  }
  await expect.poll(async () => ((await j(page, `/periods/${pid}/replacement-requests`)) as { items: { status: string }[] }).items.filter((r) => r.status === "open").length).toBe(0);
  for (const a of picks) {
    const now = ((await j(page, `/periods/${pid}/schedule`)).assignments as A[]).filter((x) => x.shift_id === a.shift_id);
    expect(now.map((x) => x.employee_id)).toEqual([a.employee_id]); // titulaire conservé après refus et annulation
  }
  await p.reload(); await p.waitForLoadState("networkidle");
  await expect(p.getByTestId("my-offer").filter({ hasText: "Annulée" })).toHaveCount(1);
  await ctx.close();
});
