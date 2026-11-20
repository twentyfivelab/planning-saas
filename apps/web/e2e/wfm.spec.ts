import { expect, test, type Page } from "@playwright/test";
import { API, getJson } from "./api";

// Parcours du manager sur la plateforme WFM : client, mission, remplaçant, explication, simulation, versions, heures réelles, rentabilité.
// Prérequis : pile lancée, tenant de démonstration (E2E_EMAIL / E2E_PASSWORD, propriétaire), novembre 2026 généré. Les données créées sont retirées.
test.skip(!process.env.E2E_EMAIL, "E2E_EMAIL non défini");
test.describe.configure({ mode: "serial" });

const CLIENT = "Client de test e2e";
const TITLE = "Mission de test e2e";
type Asg = { assignment_id: string; shift_id: string; slot_key: string; employee: string; employee_id: string; day: string; site: string; locked: boolean; allocations: Record<string, number>; source: string };
const csrf = async (page: Page) => (await getJson(page, "/auth/me")).csrf_token as string;
const nov = async (page: Page) => ((await getJson(page, "/periods")) as { id: string; start_date: string }[]).find((p) => p.start_date === "2026-11-01")!.id;
const schedule = async (page: Page, pid: string) => (await getJson(page, `/periods/${pid}/schedule`)).assignments as Asg[];
const toNovember = async (page: Page) => { await page.evaluate(() => localStorage.setItem("planning:month", "2026-11")); };

async function cleanup(page: Page) {
  const token = await csrf(page), h = { "X-CSRF-Token": token };
  for (const m of (await getJson(page, "/missions")) as { id: string; title: string; status: string }[]) {
    if (m.title !== TITLE) continue;
    if (m.status === "confirmed") await page.request.post(`${API}/missions/${m.id}/cancel`, { headers: h, data: { release_shifts: true } });
    await page.request.delete(`${API}/missions/${m.id}`, { headers: h });
  }
  for (const c of (await getJson(page, "/clients")) as { id: string; name: string }[]) {
    if (c.name === CLIENT) await page.request.delete(`${API}/clients/${c.id}`, { headers: h });
  }
}

test("navigation : organisée autour des actions essentielles, sans Rentabilité, Équité ni Simulations", async ({ page }) => {
  await page.goto("/"); await page.waitForLoadState("networkidle");
  const nav = page.getByRole("navigation", { name: "Navigation principale" });
  for (const name of ["Planning", "Génération", "Alertes", "Historique", "Collaborateurs", "Clients et missions", "Heures réelles", "Paramètres"]) await expect(nav.getByRole("link", { name: new RegExp(`^${name}$`) }).first()).toBeVisible();
  for (const name of ["Simulations", "Rentabilité", "Équité"]) await expect(nav.getByRole("link", { name })).toHaveCount(0);
  for (const path of ["/simulations", "/finance", "/fairness"]) expect((await page.request.get(path)).status()).toBe(404); // écrans retirés
  await page.goto("/"); await page.waitForLoadState("networkidle");
  await expect(nav.getByRole("link", { name: "Mon planning" })).toHaveCount(0); // compte sans fiche collaborateur : pas d'espace personnel
  await expect(nav.locator(".history-nav").getByRole("link").first()).toBeInViewport(); // historique des plannings visible sans défiler
  await expect(page.locator(".sidebar.glass")).toBeVisible();
});

test("créer un client, puis une mission : brouillon non planifié, qualifications vérifiées, confirmation", async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1440, height: 1100 });
  await cleanup(page);
  await page.goto("/clients"); await page.waitForLoadState("networkidle");
  await page.getByRole("tab", { name: "Clients" }).click();
  await page.getByRole("button", { name: "Nouveau client" }).click();
  const dlg = page.getByRole("dialog", { name: "Nouveau client" });
  await dlg.getByLabel("Nom", { exact: true }).first().fill(CLIENT);
  await dlg.getByRole("button", { name: "Ajouter un responsable" }).click();
  await dlg.getByRole("group", { name: "Responsable 1" }).getByLabel("Nom").fill("Mme Test");
  await dlg.getByLabel("Tarif horaire (CHF)").fill("70");
  await dlg.getByRole("button", { name: "Enregistrer" }).click();
  await expect(dlg).toBeHidden();
  const row = page.getByRole("table", { name: "Clients" }).getByRole("row").filter({ hasText: CLIENT });
  await expect(row).toContainText("Mme Test");
  await expect(row).toContainText(/70[.,]00 CHF/);
  await page.getByRole("tab", { name: "Missions" }).click();
  await page.getByRole("button", { name: "Nouvelle mission" }).click();
  const form = page.getByRole("dialog", { name: "Nouvelle mission" });
  await form.getByLabel("Intitulé").fill(TITLE);
  await form.getByLabel("Client").selectOption({ label: CLIENT });
  await form.getByLabel("Marque").selectOption({ value: "Cartier" });
  await form.getByLabel("Cartier", { exact: true }).check();
  await form.getByLabel("Début de mission").fill("2026-11-23");
  await form.getByLabel("Fin de mission").fill("2026-11-24");
  await form.getByLabel("Priorité").selectOption({ label: "Critique" });
  await form.getByRole("button", { name: "Enregistrer" }).click();
  const open = page.getByRole("dialog", { name: TITLE });
  await expect(open).toContainText("Brouillon");
  await expect(open.getByRole("region", { name: "Collaborateurs admissibles" }).or(open.locator("section", { hasText: "Collaborateurs admissibles" })).first()).toContainText("Zaki");
  const pid = await nov(page);
  const before = (await schedule(page, pid)).filter((a) => a.slot_key.startsWith("MSN-")).length;
  expect(before).toBe(0); // brouillon : rien dans le planning
  await open.getByRole("button", { name: "Confirmer la mission" }).click();
  await expect(open).toContainText("Confirmée");
  await open.getByRole("button", { name: "Novembre 2026" }).click();
  await expect(open.getByRole("button", { name: "Appliquer cette proposition" }).or(open.getByText(/Aucune affectation ne changerait|Impossible dans ce périmètre/)).first()).toBeVisible({ timeout: 60_000 });
  expect((await schedule(page, pid)).filter((a) => a.slot_key.startsWith("MSN-")).length).toBe(0); // proposition : rien d'appliqué
  await open.getByRole("button", { name: "Fermer" }).last().click();
  await cleanup(page);
});

test("remplaçants classés et explication d'une affectation depuis le planning", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/"); await toNovember(page);
  await page.goto("/planning"); await page.waitForLoadState("networkidle");
  const shift = page.getByRole("region", { name: /Planning général/ }).locator(".shift").first();
  await expect(shift).toBeVisible();
  await shift.click();
  await page.getByRole("button", { name: "Pourquoi ce collaborateur ?" }).click();
  const why = page.getByRole("dialog", { name: /^Pourquoi .* sur ce shift \?/ });
  await expect(why.getByRole("heading", { name: "Règles strictes" })).toBeVisible();
  await expect(why.getByText("Marque autorisée dans la fiche")).toBeVisible();
  await expect(why.getByText(/pas une cause unique démontrée/)).toBeVisible();
  await why.getByRole("button", { name: "Fermer" }).last().click();
  await page.getByRole("button", { name: "Voir les remplaçants" }).click();
  const rep = page.getByRole("dialog", { name: "Remplaçants proposés" });
  await expect(rep.getByText(/Titulaire actuel/)).toBeVisible();
  const list = rep.getByRole("list", { name: /Remplaçants compatibles/ });
  if (await list.isVisible()) { await expect(list.locator("li").first()).toContainText("100 / 100"); await expect(list.locator("li").first()).toContainText("Heures attribuées"); }
  await rep.getByRole("button", { name: "Fermer" }).last().click();
});

test("déclarer une absence puis réoptimiser partiellement : seul le shift concerné change", async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/"); await toNovember(page);
  const pid = await nov(page), token = await csrf(page);
  const rows = await schedule(page, pid);
  const a = rows.find((x) => !x.locked && x.day >= "2026-11-10" && x.day <= "2026-11-25" && x.site === "GVA3")!;
  const emp = ((await getJson(page, "/employees")) as { id: string; name: string }[]).find((e) => e.id === a.employee_id)!;
  const keep = (await getJson(page, `/employees/${emp.id}/availability`)).dates as string[];
  await page.goto("/planning"); await page.waitForLoadState("networkidle");
  try {
    await page.getByRole("button", { name: "Déclarer une absence" }).click();
    const dlg = page.getByRole("dialog", { name: "Déclarer une absence" });
    await dlg.getByLabel("Collaborateur").selectOption({ label: emp.name });
    await dlg.getByLabel("Du", { exact: true }).fill(a.day);
    await dlg.getByRole("button", { name: "Enregistrer et voir les shifts concernés" }).click();
    await expect(dlg.getByRole("heading", { name: "1. Remplacement simple" })).toBeVisible();
    await expect(dlg.getByRole("heading", { name: "2. Réoptimisation partielle" })).toBeVisible();
    await expect(dlg.getByRole("heading", { name: "3. Réoptimisation complète" })).toBeVisible();
    await dlg.getByRole("button", { name: "Calculer une proposition" }).click();
    await expect(dlg.getByRole("button", { name: "Appliquer cette proposition" }).or(dlg.getByText(/Impossible dans ce périmètre/)).first()).toBeVisible({ timeout: 60_000 });
    const after = await schedule(page, pid);
    expect(after.find((x) => x.slot_key === a.slot_key)!.employee).toBe(a.employee); // une proposition ne modifie rien
    await dlg.getByRole("button", { name: "Fermer" }).last().click();
  } finally {
    await page.request.put(`${API}/employees/${emp.id}/unavailable-dates`, { headers: { "X-CSRF-Token": token }, data: { dates: keep } });
  }
});

test("versions : statut et publication refusée tant que les contrats manquent, heures réelles", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/"); await toNovember(page);
  await page.goto("/versions"); await page.waitForLoadState("networkidle");
  await page.getByLabel("Libellé de la version").fill("Version de test e2e");
  await page.getByRole("button", { name: "Nouvelle version" }).click();
  const row = page.getByRole("table", { name: "Versions" }).getByRole("row").filter({ hasText: "Version de test e2e" }).first();
  await expect(row).toBeVisible();
  await expect(row).toContainText("Copie de travail");
  await expect(row).toContainText("non publiable");
  await row.getByRole("button", { name: /^Supprimer la version/ }).click(); // une copie de travail manuelle se retire ; rien ne reste dans les données
  await expect(page.getByRole("table", { name: "Versions" }).getByRole("row").filter({ hasText: "Version de test e2e" })).toHaveCount(0);
  // heures réelles : distinctes du planning
  const pid = await nov(page);
  const a = (await schedule(page, pid)).find((x) => x.day === "2026-11-02")!;
  const before = JSON.stringify(await schedule(page, pid));
  await page.goto("/time"); await page.waitForLoadState("networkidle");
  await page.getByLabel("Jour", { exact: true }).fill("2026-11-02");
  const line = page.getByRole("table", { name: "Heures du jour" }).getByRole("row").filter({ hasText: a.employee }).first();
  await line.getByRole("button", { name: `Saisir les heures de ${a.employee}` }).click();
  const dlg = page.getByRole("dialog", { name: `Heures réelles — ${a.employee}` });
  const start = a.slot_key ? await dlg.getByLabel("Arrivée réelle").inputValue() : "";
  const [h, m] = start.split(":").map(Number);
  const late = `${String(h).padStart(2, "0")}:${String(m + 20).padStart(2, "0")}`;
  await dlg.getByLabel("Arrivée réelle").fill(late);
  await dlg.getByRole("button", { name: "Enregistrer" }).click();
  await expect(line).toContainText("Retard 20 min");
  await line.getByRole("button", { name: `Valider ${a.employee}` }).click();
  await expect(line).toContainText("Validée");
  expect(JSON.stringify(await schedule(page, pid))).toBe(before); // le planning prévu ne bouge pas
  const token = await csrf(page);
  expect((await page.request.delete(`${API}/shifts/${a.shift_id}/time-entry`, { headers: { "X-CSRF-Token": token } })).status()).toBe(409); // validé : protégé
  await line.getByRole("button", { name: `Retirer la validation de ${a.employee}` }).click();
  await expect(line).toContainText("À valider");
  expect((await page.request.delete(`${API}/shifts/${a.shift_id}/time-entry`, { headers: { "X-CSRF-Token": token } })).status()).toBe(204);
});

test("le tableau de bord présente le pilotage du mois", async ({ page }) => {
  await page.goto("/"); await toNovember(page);
  await page.reload(); await page.waitForLoadState("networkidle");
  const p = page.getByTestId("pilotage");
  await expect(p).toContainText("Absences à remplacer et shifts non couverts");
  await expect(p).not.toContainText("Écart aux objectifs"); // carte d'équité retirée de l'interface
  await expect(p).not.toContainText("Coût et marge");
  await expect(page.getByRole("table", { name: "Répartition par collaborateur" })).toBeVisible();
});

test.describe("collaborateur", () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  test("arrive sur son espace, sans accès au planning en préparation", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("E-mail").fill((process.env.E2E_EMAIL ?? "").replace(/^[^@]+/, "collaborateur"));
    await page.getByLabel("Mot de passe").fill(process.env.E2E_PASSWORD ?? "");
    await page.getByRole("button", { name: "Se connecter" }).click();
    await expect(page).toHaveURL(/\/me$/, { timeout: 20_000 });
    await expect(page.getByRole("heading", { name: "Mon planning" })).toBeVisible();
    const nav = page.getByRole("navigation", { name: "Navigation principale" });
    await expect(nav.getByRole("link", { name: "Planning", exact: true })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Collaborateurs" })).toHaveCount(0);
    const pid = ((await getJson(page, "/periods")) as { id: string }[])[0].id;
    expect((await page.request.get(`${API}/periods/${pid}/schedule`)).status()).toBe(403);
    expect((await page.request.get(`${API}/employees`)).status()).toBe(403);
  });
});
