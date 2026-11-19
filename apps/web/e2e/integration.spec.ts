import { expect, test, type Page } from "@playwright/test";
import { API, getJson as j } from "./api";

// Intégration d'un ajout au planning existant d'un mois : nouvelle marque intégrée « manuellement » (suivi de couverture, novembre 2027)
// et nouveau collaborateur intégré par « Recalculer tout le planning » (décembre 2027). Un mois dédié par scénario : le premier laisse
// une affectation verrouillée, qui rendrait le recalcul du second infaisable (dépendance constatée le 19/11, corrigée ainsi). Marque
// archivée, collaborateurs et plannings supprimés à la fin : aucun autre test n'en dépend.
test.skip(!process.env.E2E_EMAIL || !process.env.E2E_PASSWORD, "E2E_EMAIL / E2E_PASSWORD non définis");
test.describe.configure({ mode: "serial" });

const csrf = async (page: Page) => (await j(page, "/auth/me")).csrf_token as string;
type A = { assignment_id: string; employee_id: string; shift_id: string; allocations: Record<string, number> };
const rows = async (page: Page, pid: string) => ((await j(page, `/periods/${pid}/schedule`)).assignments as A[]).map((a) => `${a.assignment_id}|${a.employee_id}|${a.shift_id}`).sort();
let pid = ""; let dec = "";

test.beforeAll(async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: "e2e/.auth/state.json" });
  const page = await ctx.newPage();
  const token = await csrf(page);
  for (const month of [11, 12]) {
    const id = (await (await page.request.post(`${API}/periods/ensure`, { headers: { "X-CSRF-Token": token }, data: { year: 2027, month } })).json()).id as string;
    if (month === 11) pid = id; else dec = id;
    if (!((await j(page, `/periods/${id}/schedule`)).assignments as unknown[]).length) {
      const run = await page.request.post(`${API}/periods/${id}/runs`, { headers: { "X-CSRF-Token": token, "Idempotency-Key": `integ-${month}-${Date.now()}` }, data: { time_limit_s: 10 } });
      expect(run.status(), await run.text()).toBe(202);
      await expect.poll(async () => ((await j(page, `/periods/${id}/schedule`)).assignments as unknown[]).length, { timeout: 50_000 }).toBeGreaterThan(0);
    }
  }
  await ctx.close();
});

test.afterAll(async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: "e2e/.auth/state.json" });
  const page = await ctx.newPage();
  const token = await csrf(page);
  for (const id of [pid, dec]) if (id) await page.request.post(`${API}/periods/${id}/delete`, { headers: { "X-CSRF-Token": token }, data: { password: process.env.E2E_PASSWORD } });
  await ctx.close();
});

async function openNov2027(page: Page) {
  await page.goto("/planning");
  await page.evaluate(() => { try { localStorage.setItem("planning:month", "2027-11"); } catch { /* ignoré */ } });
  await page.reload(); await page.waitForLoadState("networkidle");
}

test("nouvelle marque : saisie manuelle, suivi de couverture persistant, placement et attribution avec les contrôles habituels", async ({ page }) => {
  const token = await csrf(page); const H = { "X-CSRF-Token": token };
  const name = `Marque intégration ${Date.now().toString(36)}`;
  let code = ""; let empId = "";
  try {
    await page.goto("/catalog"); await page.waitForLoadState("networkidle");
    await page.getByLabel("Nom de la marque (ou marque + boutique)").fill(name);
    await page.getByRole("button", { name: "Ajouter la marque" }).click();
    const integ = page.getByTestId("integration-modal");
    await expect(integ).toBeVisible();
    code = ((await j(page, "/catalog")) as { brands: { code: string; name: string }[] }).brands.find((b) => b.name === name)!.code;
    await integ.getByLabel("Planning concerné").selectOption(pid); // le mois concerné est choisi et affiché AVANT le choix
    await expect(page.getByRole("dialog", { name: "Comment souhaitez-vous intégrer cet ajout au planning de novembre 2027 ?" })).toBeVisible();
    await expect(integ.getByTestId("integration-month")).toContainText("Novembre 2027");
    const before = await rows(page, pid);
    await integ.getByTestId("choice-manual").click();
    await expect(integ).toContainText("Choix enregistré");
    expect(await rows(page, pid)).toEqual(before); // aucune affectation créée du seul fait de l'ajout
    await integ.getByRole("button", { name: "Fermer" }).click();
    // suivi dans le planning : besoins non définis -> jamais de confirmation trompeuse
    await openNov2027(page);
    const tracker = page.getByTestId("integration-tracker");
    await expect(tracker).toContainText(`${name} : Besoins à renseigner`);
    // besoins définis (mercredis de novembre 2027 : 4 shifts) et un collaborateur autorisé, intégré au mois
    const site = ((await j(page, "/catalog")) as { sites: { code: string; archived: boolean }[] }).sites.find((s) => !s.archived)!.code;
    expect((await page.request.post(`${API}/catalog/animations`, { headers: H, data: { site_code: site, brand_code: code, start: "10:00", end: "17:00", weekdays: [2], headcount: 1, from_month: "2027-11" } })).status()).toBe(201);
    const emp = await (await page.request.post(`${API}/employees`, { headers: H, data: { code: `integ${Date.now().toString(36)}`, name: `Collab ${name}`, brands: { [code]: "priority" } } })).json();
    empId = emp.id;
    expect((await page.request.post(`${API}/periods/${pid}/integrations`, { headers: H, data: { kind: "employee", employee_id: empId, choice: "manual" } })).status()).toBe(201);
    await page.reload(); await page.waitForLoadState("networkidle");
    await expect(tracker).toContainText(`${name} : 0 shift attribué sur 4 — 4 restent à compléter.`);
    await expect(tracker).toContainText("4 à placer");
    await tracker.getByText("Voir les shifts à compléter (4)").click();
    await tracker.getByRole("button", { name: "Placer et attribuer" }).first().click();
    const pick = page.getByRole("dialog", { name: `Attribuer le shift ${name}` });
    await pick.getByLabel("Collaborateur").selectOption(empId);
    await pick.getByRole("button", { name: "Continuer" }).click();
    const day = page.getByRole("dialog", { name: `Ajouter un jour de travail — Collab ${name}` });
    // diagnostic conservé : durée réelle de l'attribution côté serveur (un échec antérieur : réponse au-delà de 5 s, juste après un redémarrage)
    const t0 = Date.now();
    const assigned = page.waitForResponse((r) => r.url().includes(`/periods/${pid}/manual-assign`) && r.request().method() === "POST");
    await day.getByRole("button", { name: new RegExp(code.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")) }).first().click(); // la fenêtre habituelle : contrôles et confirmations
    const res = await assigned;
    const tm = res.request().timing(); // ms relatives à startTime : attente avant envoi (file du navigateur) puis réponse
    console.log(`[diagnostic] manual-assign : HTTP ${res.status()} en ${Date.now() - t0} ms ; envoi après ${Math.round(tm.requestStart)} ms d'attente, réponse à ${Math.round(tm.responseStart)} ms (serveur : ${res.headers()["server-timing"] ?? "—"})`);
    const accept = day.getByRole("button", { name: "Accepter quand même" });
    if (await accept.isVisible().catch(() => false)) await accept.click();
    await expect(tracker).toContainText(`${name} : 1 shift attribué sur 4 — 3 restent à compléter.`);
    expect(((await j(page, `/periods/${pid}/schedule`)).assignments as A[]).filter((a) => code in a.allocations)).toHaveLength(1);
    // persistant après actualisation
    await page.reload(); await page.waitForLoadState("networkidle");
    await expect(tracker).toContainText(`${name} : 1 shift attribué sur 4 — 3 restent à compléter.`);
    await expect(tracker).toContainText(`Collab ${name} fait partie de l'effectif de ce mois`);
    await expect(tracker).toContainText("1 shift attribué");
    await expect(page.getByTestId("tracker-remaining")).toHaveText("Reste à attribuer : 3 shifts · 18 h"); // shifts ET heures restants
    // notifications : aucune tant que la couverture est incomplète ; une seule quand tout est couvert ; une seule quand elle redevient incomplète
    const cov = async () => ((await j(page, `/periods/${pid}/integrations`)) as { items: { kind: string; id: string; coverage?: { items: { slot_key: string; shift_id: string | null; state: string }[] } }[] }).items.find((i) => i.kind === "brand")!;
    const coverageNotes = async () => ((await j(page, "/notifications")) as { items: { kind: string; title: string; payload: { brand?: string } }[] }).items.filter((n) => n.kind.startsWith("coverage_") && n.payload.brand === code);
    expect(await coverageNotes()).toEqual([]);
    const tr = await cov();
    for (const x of tr.coverage!.items) { // les 3 derniers besoins, par l'API (mêmes contrôles côté serveur)
      const sid = x.shift_id ?? (await (await page.request.post(`${API}/periods/${pid}/integrations/${tr.id}/place`, { headers: H, data: { slot_key: x.slot_key } })).json()).shift_id;
      const r = await page.request.post(`${API}/periods/${pid}/manual-assign`, { headers: H, data: { employee_id: empId, shift_id: sid, force: true, reason: "test e2e" } });
      expect(r.status(), await r.text()).toBe(200);
    }
    await page.goto("/planning"); await page.waitForLoadState("networkidle");
    await expect(tracker).toContainText(`Tous les shifts de ${name} sont attribués et sans conflit.`);
    expect((await coverageNotes()).map((n) => n.kind)).toEqual(["coverage_complete"]);
    await page.goto("/notifications"); await page.waitForLoadState("networkidle");
    const notif = page.getByTestId("notification").filter({ hasText: `${name} : tous les besoins de novembre 2027 sont couverts` });
    await expect(notif).toHaveCount(1);
    await expect(notif).toContainText("Tous les shifts de " + name + " sont attribués et sans conflit (4 shift(s), 24 h).");
    // une suppression rend la couverture incomplète : nouvelle alerte, une seule fois même après une seconde suppression
    const nxs = ((await j(page, `/periods/${pid}/schedule`)).assignments as A[]).filter((a) => code in a.allocations);
    for (const a of nxs.slice(0, 2)) expect((await page.request.delete(`${API}/assignments/${a.assignment_id}?force=true`, { headers: H })).status()).toBe(204);
    expect((await coverageNotes()).map((n) => n.kind)).toEqual(["coverage_incomplete", "coverage_complete"]);
    // reconnexion (nouvelle session) : état et notifications conservés
    const fresh = await page.context().browser()!.newContext({ storageState: { cookies: [], origins: [] } });
    const p2 = await fresh.newPage();
    await p2.goto("/login");
    await p2.getByLabel("E-mail").fill(process.env.E2E_EMAIL!); await p2.getByLabel("Mot de passe").fill(process.env.E2E_PASSWORD!);
    await p2.getByRole("button", { name: "Se connecter" }).click();
    await p2.waitForURL((u) => !u.pathname.startsWith("/login"));
    await p2.goto("/notifications"); await p2.waitForLoadState("networkidle");
    await expect(p2.getByTestId("notification").filter({ hasText: `${name} : couverture de novembre 2027 de nouveau incomplète` })).toContainText("1 shift(s) (6 h) restent à attribuer : 1 sans collaborateur."); // envoyée à la 1re suppression, pas répétée à la 2e
    await expect(p2.getByTestId("notification").filter({ hasText: name })).toHaveCount(2);
    await p2.evaluate(() => { try { localStorage.setItem("planning:month", "2027-11"); } catch { /* ignoré */ } });
    await p2.goto("/planning"); await p2.waitForLoadState("networkidle");
    await expect(p2.getByTestId("integration-tracker")).toContainText(`${name} : 2 shifts attribués sur 4 — 2 restent à compléter.`);
    await expect(p2.getByTestId("tracker-remaining")).toHaveText("Reste à attribuer : 2 shifts · 12 h");
    await fresh.close();
    // historique : le choix, avec son auteur
    await page.goto("/history?kind=integration"); await page.waitForLoadState("networkidle");
    await expect(page.getByTestId("history-event").filter({ hasText: `Intégration de la marque ${name} au planning de novembre 2027` })).toContainText("Ajouter les shifts manuellement");
  } finally {
    if (code) await page.request.patch(`${API}/catalog/brands/${encodeURIComponent(code)}`, { headers: H, data: { archived_from: "2027-11" } });
    if (empId) await page.request.delete(`${API}/employees/${empId}`, { headers: H });
  }
});

test("nouveau collaborateur : « Recalculer tout le planning », planning initial conservé en version, rien de publié", async ({ page }) => {
  const token = await csrf(page); const H = { "X-CSRF-Token": token };
  const last = `INTEG-${Date.now().toString(36)}`; const full = `Alex ${last}`;
  let empId = "";
  try {
    const versionsBefore = ((await j(page, `/periods/${dec}/versions`)) as { id: string }[]).map((v) => v.id);
    await page.goto("/employees"); await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: "Ajouter un collaborateur" }).click();
    const form = page.getByTestId("employee-add-form");
    await form.getByLabel("Prénom *").fill("Alex");
    await form.getByLabel("Nom *", { exact: true }).fill(last);
    await form.getByRole("button", { name: "Ajouter le collaborateur" }).click();
    const integ = page.getByTestId("integration-modal");
    await expect(integ).toBeVisible();
    empId = ((await j(page, "/employees")) as { id: string; name: string }[]).find((x) => x.name === full)!.id;
    await integ.getByLabel("Planning concerné").selectOption(dec);
    await expect(page.getByRole("dialog", { name: "Comment souhaitez-vous intégrer cet ajout au planning de décembre 2027 ?" })).toBeVisible();
    await integ.getByTestId("choice-recalculate").click();
    await expect(integ).toContainText(`${full} sera ajouté·e à l'effectif de décembre 2027 uniquement`);
    await integ.getByTestId("integration-launch").click();
    const result = integ.getByTestId("integration-result");
    await expect(result).toBeAttached({ timeout: 45_000 }); // calcul limité à 30 s
    expect(await result.getAttribute("data-outcome"), await integ.textContent() ?? "").toBe("replaced"); // mois propre : le recalcul doit aboutir
    const run = ((await j(page, "/runs")) as { id: string; period_id: string; status: string; save?: { outcome: string } }[]).find((r) => r.period_id === dec)!;
    expect(run.status).toBe("termine");
    const vs = (await j(page, `/periods/${dec}/versions`)) as { id: string; label: string; state: string }[];
    const added = vs.filter((v) => !versionsBefore.includes(v.id)).map((v) => v.label);
    if (run.save?.outcome === "replaced") expect(added.sort()).toEqual([`Avant intégration de ${full}`, `Planning recalculé avec ${full}`].sort());
    else expect(added).toEqual([]); // échec : planning initial conservé, actif
    expect(vs.some((v) => v.state === "published")).toBe(false); // jamais publié automatiquement
    const ros = (await j(page, `/periods/${dec}/roster`)) as { employees: { employee_id: string; state: string }[] };
    expect(ros.employees.find((x) => x.employee_id === empId)!.state).toBe("included");
  } finally {
    if (empId) await page.request.delete(`${API}/employees/${empId}`, { headers: H });
  }
});
