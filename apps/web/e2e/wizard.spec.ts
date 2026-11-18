import { expect, test, type Page } from "@playwright/test";
import { getJson } from "./api";

// Parcours « + Générer un nouveau planning » de bout en bout, dans le navigateur.
// Prérequis : pile lancée, tenant de démonstration (E2E_EMAIL / E2E_PASSWORD, propriétaire), novembre 2026 généré.
test.skip(!process.env.E2E_EMAIL, "E2E_EMAIL non défini");
test.describe.configure({ mode: "serial" });
const API = process.env.API_URL ?? "http://localhost:8000";
const j = (page: Page, path: string) => getJson(page, path);
type P = { id: string; name: string; start_date: string; status: string };
const periodOf = async (page: Page, iso: string) => ((await j(page, "/periods")) as P[]).find((p) => p.start_date === iso);
/** Attend une confirmation RÉELLE d'enregistrement (compteur du serveur incrémenté, état « Enregistré »), limite raisonnable de 15 s ;
 *  une erreur affichée fait échouer immédiatement avec son message. */
async function saved(page: Page, action: () => Promise<unknown>) {
  const st = page.locator("[data-save-confirmed]").first();
  const before = Number((await st.getAttribute("data-save-confirmed")) ?? 0);
  await action();
  await expect.poll(async () => {
    const [state, n] = [await st.getAttribute("data-save-state"), Number(await st.getAttribute("data-save-confirmed"))];
    if (state === "error") throw new Error(`Échec d'enregistrement affiché : ${await st.textContent()}`);
    return state === "saved" && n > before;
  }, { timeout: 15_000, message: "confirmation d'enregistrement de l'effectif" }).toBe(true);
}
const roster = async (page: Page, pid: string) => (await j(page, `/periods/${pid}/roster`)).employees as { code: string; included: boolean; state: string }[];
const next = (page: Page) => page.getByRole("navigation", { name: "Navigation de l'assistant" }).getByRole("button", { name: /^Suivant/ });
const history = (page: Page) => page.getByRole("navigation", { name: "Navigation principale" }).locator(".history-nav");

async function openJanuary(page: Page) {
  await page.goto("/plannings/new"); await page.waitForLoadState("networkidle");
  await page.getByLabel("Année", { exact: true }).selectOption("2027");
  await page.getByLabel("Mois", { exact: true }).selectOption("1");
  const create = page.getByRole("button", { name: "Créer le planning de Janvier 2027 et continuer" });
  const edit = page.getByRole("button", { name: /Modifier ses paramètres|Reprendre le brouillon/ });
  await expect(create.or(edit).first()).toBeVisible();
  if (await create.isVisible()) await create.click(); else await edit.click(); // un brouillon reprend à l'étape enregistrée
  await page.getByRole("list", { name: "Étapes de création" }).getByRole("button", { name: /Collaborateurs$/ }).click();
  await expect(page.getByRole("heading", { name: "Collaborateurs du mois" })).toBeVisible();
}

test("1. période : un mois déjà planifié est signalé, jamais écrasé ; choisir un mois ne génère rien", async ({ page }) => {
  await page.goto("/planning"); await page.waitForLoadState("networkidle");
  await page.locator(".page-head").getByRole("link", { name: "Générer un nouveau planning" }).click();
  await expect(page).toHaveURL(/\/plannings\/new/);
  await page.getByLabel("Année", { exact: true }).selectOption("2026");
  await page.getByLabel("Mois", { exact: true }).selectOption("11");
  await expect(page.getByText(/Un planning existe déjà pour Novembre 2026/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Ouvrir le planning" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Modifier ses paramètres" })).toBeVisible();
  await expect(page.getByTestId("sunday-formula")).toContainText("5 dimanches × 7 shifts = 35");
  await page.getByLabel("Mois", { exact: true }).selectOption("12");
  await expect(page.getByText("Calendrier de Décembre 2026")).toBeVisible();
  await expect(page.getByTestId("sunday-formula")).toContainText("4 dimanches × 7 shifts = 28");
  // le bouton de génération est aussi sur la page de génération
  await page.goto("/generate"); await expect(page.locator(".page-head").getByRole("link", { name: "Générer un nouveau planning" })).toBeVisible();
});

test("2-5. janvier 2027 : effectif (Zaki décoché), exception de jours, indisponibilité, budget Valmont, création d'un site et d'une marque, vérification", async ({ page }) => {
  test.setTimeout(150_000);
  page.setDefaultTimeout(20_000);
  await page.setViewportSize({ width: 1440, height: 1100 });
  await openJanuary(page);
  const jan = (await periodOf(page, "2027-01-01"))!;
  // --- étape 2 : tous les actifs cochés par défaut, Zaki décoché pour ce mois seulement
  await saved(page, () => page.getByRole("button", { name: "Tout sélectionner" }).click());
  const list = page.getByRole("list", { name: "Effectif du mois" });
  const active = (r: { state: string; included: boolean }[]) => r.filter((x) => x.state !== "inactive" && x.state !== "contract_ended");
  expect(active(await roster(page, jan.id)).every((x) => x.included)).toBe(true); // confirmé par le serveur : vérifiable immédiatement
  const r0 = await roster(page, jan.id);
  const all = r0.length, selectable = r0.filter((x) => x.included).length;
  expect(r0.filter((x) => x.state !== "inactive" && x.state !== "contract_ended").every((x) => x.included)).toBe(true); // tous les actifs cochés
  await expect(page.getByText(new RegExp(`^${selectable} sélectionnés sur ${all}$`, "i"))).toBeVisible();
  await page.getByPlaceholder("Rechercher un collaborateur…").fill("zak");
  await saved(page, () => list.getByRole("checkbox").first().uncheck());
  await expect(list.locator("li").first()).toContainText("Exclu ce mois");
  await page.getByPlaceholder("Rechercher un collaborateur…").fill("");
  await expect(page.getByText(new RegExp(`^${selectable - 1} sélectionnés sur ${all}$`, "i"))).toBeVisible();
  expect((await roster(page, jan.id)).find((x) => x.code === "zaki")!.state).toBe("excluded");
  const nov = (await periodOf(page, "2026-11-01"))!;
  expect((await roster(page, nov.id)).find((x) => x.code === "zaki")!.included).toBe(true); // novembre : inchangé
  expect(((await j(page, "/employees")) as { code: string; active: boolean }[]).find((e) => e.code === "zaki")!.active).toBe(true); // fiche intacte
  // --- étape 3 : fiche de Mila, exception « 3 jours / semaine » et indisponibilité le 20 janvier, pour janvier seulement
  const milaId = ((await j(page, "/employees")) as { id: string; code: string }[]).find((e) => e.code === "mila")!.id;
  await page.request.put(`${API}/employees/${milaId}/unavailable-dates`, { headers: { "X-CSRF-Token": (await j(page, "/auth/me")).csrf_token }, data: { dates: [] } }); // état initial connu (un clic bascule le jour)
  await next(page).click();
  const row = page.getByRole("row").filter({ has: page.getByText("Mila", { exact: true }) });
  await row.getByRole("button", { name: "Configurer" }).click();
  const sheet = page.getByRole("dialog", { name: "Fiche — Mila" });
  await sheet.getByRole("radiogroup", { name: "Portée du nombre maximum de jours par semaine" }).getByRole("radio", { name: /Exception pour Janvier 2027/ }).check();
  await sheet.getByLabel("Jours par semaine (Janvier 2027)").selectOption("3");
  await expect(sheet.getByText("Enregistré automatiquement", { exact: true }).first()).toBeVisible();
  await sheet.getByRole("button", { name: /^\S+ 20 janv\. 2027/ }).click();
  await expect.poll(async () => (await j(page, `/employees/${((await j(page, "/employees")) as { id: string; code: string }[]).find((e) => e.code === "mila")!.id}/availability`)).dates).toContain("2027-01-20");
  await sheet.getByRole("button", { name: "Fermer" }).last().click();
  const mila = ((await j(page, "/employees")) as { id: string; code: string }[]).find((e) => e.code === "mila")!;
  const mp = async (mo: string) => ((await j(page, `/month-params?month=${mo}`)) as { employee_id: string; max_days_set: boolean; max_days_count: number | null }[]).find((x) => x.employee_id === mila.id)!;
  expect(await mp("2027-01")).toMatchObject({ max_days_set: true, max_days_count: 3 });
  expect((await mp("2026-12")).max_days_set).toBe(false); // décembre inchangé
  expect((await mp("2026-11")).max_days_set).toBe(false); // novembre inchangé
  await expect(row).toContainText("Exception du mois");
  // --- étape 4 : budget Valmont 80 h pour janvier ; création d'un site
  await next(page).click();
  const valmont = page.getByLabel("Budget Valmont (heures)");
  await valmont.fill("80"); await valmont.press("Enter");
  await expect.poll(async () => ((await j(page, `/periods/${jan.id}/brands`)) as { code: string; budget_minutes: number | null }[]).find((b) => b.code === "Valmont")!.budget_minutes).toBe(80 * 60);
  expect(((await j(page, `/periods/${nov.id}/brands`)) as { code: string; budget_minutes: number | null }[]).find((b) => b.code === "Valmont")!.budget_minutes).toBe(136 * 60);
  // nouveau site et nouvelle marque créés depuis l'assistant, puis supprimés (aucune donnée de test laissée dans le référentiel)
  const SITE = "Site de test e2e", BRAND = "Marque de test e2e";
  const token = (await j(page, "/auth/me")).csrf_token as string;
  const cleanup = async () => {
    const c = await j(page, "/catalog");
    for (const st of c.sites.filter((x: { name: string }) => x.name === SITE)) for (const an of st.animations) await page.request.delete(`${API}/catalog/animations/${an.id}?from_month=2027-01`, { headers: { "X-CSRF-Token": token } });
    for (const e of (await j(page, "/employees")) as Record<string, unknown>[]) {
      const br = e.brands as Record<string, string>;
      if (BRAND in br) { const { [BRAND]: _x, ...rest } = br; void _x; await page.request.put(`${API}/employees/${e.id}`, { headers: { "X-CSRF-Token": token }, data: { ...Object.fromEntries(["code", "name", "allocation_weight", "active", "max_days_count", "max_days_period", "time_pref", "time_pref_strict", "sunday_quota", "sunday_mode"].map((k) => [k, e[k]])), brands: rest } }); }
    }
    for (const b of ((await j(page, "/brands")) as { id: string; code: string }[]).filter((x) => x.code === BRAND)) await page.request.delete(`${API}/brands/${b.id}`, { headers: { "X-CSRF-Token": token } });
    for (const st of ((await j(page, "/sites")) as { id: string; name: string }[]).filter((x) => x.name === SITE)) await page.request.delete(`${API}/sites/${st.id}`, { headers: { "X-CSRF-Token": token } });
  };
  await cleanup();
  try {
    await page.getByRole("button", { name: "Ajouter ou modifier des sites et marques" }).click();
    const ed = page.getByRole("dialog", { name: "Sites et marques" });
    await ed.getByLabel("Nom du site").fill(SITE); await ed.getByRole("button", { name: "Ajouter le site" }).click();
    const card = ed.locator("section", { hasText: `Site · ${SITE.toUpperCase().replace(/ /g, "-")}` });
    await expect(card).toBeVisible();
    await ed.getByLabel("Nom de la marque (ou marque + boutique)").fill(BRAND); await ed.getByRole("button", { name: "Ajouter la marque" }).click();
    await expect(ed.getByRole("cell", { name: BRAND }).first()).toBeVisible();
    await card.getByRole("button", { name: "Ajouter une animation" }).click();
    const form = card.getByRole("form", { name: `Nouvelle animation — ${SITE}` });
    await form.getByLabel("Marque").selectOption(BRAND);
    await form.getByLabel("Début").fill("09:00"); await form.getByLabel("Fin").fill("18:00");
    await form.getByLabel("Personnes nécessaires").fill("2");
    await form.getByRole("button", { name: "Ajouter l'animation" }).click();
    await expect(card.getByRole("table", { name: `Animations de ${SITE}` })).toContainText(BRAND);
    const brandRow = ed.getByRole("row").filter({ has: page.getByText(BRAND, { exact: true }) }).last();
    await brandRow.getByRole("button", { name: "Autoriser des collaborateurs" }).click();
    const au = page.getByRole("dialog", { name: `Autoriser sur ${BRAND}` });
    await expect(au.getByRole("list", { name: "Collaborateurs à autoriser" })).toBeVisible();
    for (const n of ["Sahra", "Kristina"]) await au.getByLabel(n, { exact: true }).check();
    await au.getByRole("button", { name: /^Autoriser/ }).click();
    await expect(au).toBeHidden();
    await ed.getByLabel("Nom du site").focus();
    await page.keyboard.press("Escape"); // fermeture au clavier (Échap)
    await expect(ed).toBeHidden();
    const row = page.getByRole("table", { name: "Sites du mois" }).getByRole("row").filter({ hasText: SITE });
    await expect(row).toContainText(BRAND);
    const site = ((await j(page, `/periods/${jan.id}/sites`)) as { name: string; shifts: number }[]).find((x) => x.name === SITE)!;
    expect(site.shifts).toBe(2 * 21); // 2 personnes × 21 jours ouvrés de janvier 2027 : besoins reconnus par le moteur
    const brand = ((await j(page, `/periods/${jan.id}/brands`)) as { code: string; schedules: string[]; shifts: number }[]).find((x) => x.code === BRAND)!;
    expect(brand.schedules).toEqual(["09:00–18:00"]);
    expect(((await j(page, "/employees")) as { code: string; brands: Record<string, string> }[]).filter((e) => BRAND in e.brands).map((e) => e.code).sort()).toEqual(["kristina", "sahra"]);
  } finally {
    await cleanup(); // le site et la marque de test ne restent jamais dans les données
  }
  // --- étape 5 : vérification
  await next(page).click();
  await expect(page.locator("p", { hasText: "Exclus ce mois" })).toContainText("Zaki");
  await expect(page.locator(".recap")).toContainText(`${selectable - 1}`);
  await expect(page.getByText("Récapitulatif — Janvier 2027")).toBeVisible();
  // retour à une étape précédente sans perte
  await page.locator(".recap").getByRole("button", { name: "Modifier" }).first().click();
  await expect(page.getByRole("heading", { name: "Collaborateurs du mois" })).toBeVisible();
  await expect(page.getByText(new RegExp(`^${selectable - 1} sélectionnés`, "i"))).toBeVisible();
});

test("6. génération de janvier, historique latéral et retour à novembre intact", async ({ page }) => {
  test.setTimeout(240_000);
  const jan = (await periodOf(page, "2027-01-01"))!;
  const nov = (await periodOf(page, "2026-11-01"))!;
  const novBefore = JSON.stringify(((await j(page, `/periods/${nov.id}/schedule`)).assignments as { slot_key: string; employee: string }[]).map((a) => [a.slot_key, a.employee]).sort());
  await page.goto(`/plannings/new?period=${jan.id}`); await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: /Génération$/ }).click({ timeout: 15_000 });
  await page.getByLabel("Durée maximale du calcul (secondes)").fill("20");
  // janvier a déjà un planning (exécutions précédentes) : les paramètres de ce mois viennent d'être modifiés, on les applique explicitement
  // janvier déjà planifié (exécution précédente) : choix explicite des paramètres ; sinon (base neuve) aucun choix n'est proposé
  if (((await j(page, `/periods/${jan.id}/schedule`)).assignments as unknown[]).length) {
    const current = page.getByTestId("params-choice").getByRole("radio", { name: /Paramètres actuels/ });
    await expect(current).toBeVisible({ timeout: 15_000 });
    await current.check();
  }
  await page.getByRole("button", { name: "Générer automatiquement le planning" }).click();
  const confirm = page.getByRole("button", { name: "Confirmer et générer" });
  if (await confirm.isVisible({ timeout: 1000 }).catch(() => false)) await confirm.click();
  await expect(page.getByText(/Planning de Janvier 2027 généré/)).toBeVisible({ timeout: 90_000 });
  const rows = (await j(page, `/periods/${jan.id}/schedule`)).assignments as { employee: string; site: string; day: string }[];
  expect(rows.length).toBeGreaterThan(50);
  expect(rows.some((a) => a.employee === "Zaki")).toBe(false); // exclu du mois : aucun shift
  const mila = rows.filter((a) => a.employee === "Mila");
  expect(mila.some((a) => a.day === "2027-01-20")).toBe(false);
  // historique latéral : novembre, décembre et janvier, avec leur statut réel
  for (const n of ["Novembre 2026", "Décembre 2026", "Janvier 2027"]) await expect(history(page).getByRole("link", { name: new RegExp(n) })).toBeVisible();
  await expect(history(page).getByRole("link", { name: /Janvier 2027/ })).toContainText("Généré");
  await history(page).getByRole("link", { name: /Novembre 2026/ }).click({ timeout: 15_000 });
  await expect(page).toHaveURL(/\/planning$/);
  await expect(page.getByLabel("Mois", { exact: true })).toHaveValue("11");
  await expect(page.getByRole("region", { name: /Planning général/ }).locator(".shift").first()).toBeVisible();
  expect(JSON.stringify(((await j(page, `/periods/${nov.id}/schedule`)).assignments as { slot_key: string; employee: string }[]).map((a) => [a.slot_key, a.employee]).sort())).toBe(novBefore);
});

test("7-8. décembre : modifier une indisponibilité et transférer un shift ; tout persiste après actualisation", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  const dec = (await periodOf(page, "2026-12-01"))!;
  const jan = (await periodOf(page, "2027-01-01"))!;
  const token = (await j(page, "/auth/me")).csrf_token;
  const rows = (await j(page, `/periods/${dec.id}/schedule`)).assignments as { assignment_id: string; shift_id: string; employee: string; employee_id: string; day: string; locked: boolean; effective_minutes: number; allocations: Record<string, number> }[];
  const emps = (await j(page, "/employees")) as { id: string; name: string; code: string; brands: Record<string, string> }[];
  const inc = new Set((await roster(page, dec.id)).filter((x) => x.included).map((x) => x.code));
  // un shift non verrouillé et un collaborateur du mois, autorisé, libre la veille, le jour même et le lendemain
  const pair = rows.filter((x) => !x.locked && x.day >= "2026-12-07" && x.day <= "2026-12-23").flatMap((x) => emps.filter((e) => inc.has(e.code) && e.code !== "sabrina" && e.name !== x.employee
    && Object.keys(x.allocations).every((b) => b in e.brands) && !rows.some((y) => y.employee === e.name && Math.abs(Number(y.day.slice(8)) - Number(x.day.slice(8))) <= 1)
    && rows.filter((y) => y.employee === e.name).reduce((m, y) => m + y.effective_minutes, 0) + x.effective_minutes <= 176 * 60) // marge sous le plafond mensuel
    .map((e) => ({ a: x, to: e })))[0];
  expect(pair, "un cas de transfert disponible en décembre").toBeTruthy();
  const { a, to } = pair;
  await page.request.put(`${API}/employees/${a.employee_id}/unavailable-dates`, { headers: { "X-CSRF-Token": token }, data: { dates: [a.day] } });
  await page.goto("/planning"); await page.waitForLoadState("networkidle");
  await history(page).getByRole("link", { name: /Décembre 2026/ }).click();
  await expect(page.getByLabel("Mois", { exact: true })).toHaveValue("12");
  await expect(page.getByText(/incompatib/i).first()).toBeVisible(); // la modification est signalée, rien n'est régénéré
  await page.getByRole("tab", { name: "Collaborateur" }).click();
  await page.getByLabel("Collaborateur", { exact: true }).last().selectOption({ label: to.name });
  const DOW = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
  const lbl = `${DOW[(new Date(a.day + "T12:00:00Z").getUTCDay() + 6) % 7]} ${Number(a.day.slice(8))} déc.`;
  await page.getByRole("button", { name: `Shifts du ${lbl} pour ${to.name}` }).click();
  const dlg = page.getByRole("dialog", { name: new RegExp(`Ajouter un jour de travail — ${to.name}`) });
  await dlg.getByRole("button", { name: new RegExp(`^Transférer de ${a.employee} à ${to.name}`) }).first().click();
  await dlg.getByRole("button", { name: "Confirmer le transfert" }).click();
  const accept = dlg.getByRole("button", { name: "Accepter quand même" });
  const toast = page.getByText(new RegExp(`transféré à ${to.name}`));
  await expect(toast.or(accept).first()).toBeVisible(); // alerte éventuelle (dérogation) ou transfert direct
  if (await accept.isVisible()) await accept.click();
  await expect(toast).toBeVisible();
  // persistance : actualisation complète
  await page.reload(); await page.waitForLoadState("networkidle");
  await expect(page.getByLabel("Mois", { exact: true })).toHaveValue("12");
  const after = (await j(page, `/periods/${dec.id}/schedule`)).assignments as { shift_id: string; employee: string }[];
  expect(after.find((x) => x.shift_id === a.shift_id)!.employee).toBe(to.name);
  await page.goto(`/plannings/new?period=${jan.id}`); await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: /Collaborateurs$/ }).click();
  await page.getByPlaceholder("Rechercher un collaborateur…").fill("zak");
  await expect(page.getByRole("list", { name: "Effectif du mois" }).getByRole("checkbox").first()).not.toBeChecked(); // effectif conservé
  await page.getByRole("button", { name: /Marques et sites$/ }).click();
  await expect(page.getByLabel("Budget Valmont (heures)")).toHaveValue("80"); // budget conservé
  await expect(page.getByRole("table", { name: "Sites du mois" })).toContainText("Valmont"); // sites conservés
  await page.request.put(`${API}/employees/${a.employee_id}/unavailable-dates`, { headers: { "X-CSRF-Token": token }, data: { dates: [] } });
});

test("9. renommer puis archiver un site : les anciens plannings gardent leurs affectations", async ({ page }) => {
  const jan = (await periodOf(page, "2027-01-01"))!;
  const sel = (rows: { assignment_id: string; site: string }[]) => rows.filter((a) => a.site === "Cartier").map((a) => a.assignment_id).sort();
  const before = sel((await j(page, `/periods/${jan.id}/schedule`)).assignments);
  expect(before.length).toBeGreaterThan(0);
  await page.goto("/catalog"); await page.waitForLoadState("networkidle");
  await page.getByLabel("Année", { exact: true }).selectOption("2027"); await page.getByLabel("Mois", { exact: true }).selectOption("1");
  const card = () => page.locator("section", { hasText: "Site · CARTIER" });
  try {
    await card().getByLabel("Nom affiché").fill("Cartier Place Centrale");
    await card().getByRole("button", { name: "Renommer" }).click();
    await expect(page.getByText("Site renommé en « Cartier Place Centrale ».")).toBeVisible();
    const s1 = (await j(page, `/periods/${jan.id}/schedule`)).assignments as { assignment_id: string; site: string; site_name: string }[];
    expect(sel(s1)).toEqual(before); // même code : rien de perdu
    expect(s1.filter((a) => a.site === "Cartier").every((a) => a.site_name === "Cartier Place Centrale")).toBe(true);
    // archiver à partir de février : janvier (et ses affectations) intact
    await page.getByLabel("Mois", { exact: true }).selectOption("2");
    await card().getByRole("button", { name: "Archiver à partir de Février 2027" }).click();
    await expect(card().getByText(/Archivé depuis Février 2027/)).toBeVisible();
    expect(sel((await j(page, `/periods/${jan.id}/schedule`)).assignments)).toEqual(before);
    expect(((await j(page, "/calendar?year=2027&month=2")).brands as { brand: string }[]).some((b) => b.brand === "Cartier")).toBe(false);
    expect(((await j(page, "/calendar?year=2027&month=1")).brands as { brand: string }[]).some((b) => b.brand === "Cartier")).toBe(true);
  } finally { // remise en état : nom et activité d'origine
    const token = (await j(page, "/auth/me")).csrf_token;
    await page.request.patch(`${API}/catalog/sites/Cartier`, { headers: { "X-CSRF-Token": token }, data: { name: "Cartier", archived_from: "" } });
  }
});

test("effectif : un échec d'enregistrement s'affiche avec « Réessayer », rien n'est perdu, la reprise est confirmée par le serveur", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await openJanuary(page);
  const jan = (await periodOf(page, "2027-01-01"))!;
  const list = page.getByRole("list", { name: "Effectif du mois" });
  const box = list.getByRole("checkbox").first();
  const initial = await box.isChecked();
  const status = page.locator("[data-save-confirmed]").first();
  let fail = true;
  await page.route("**/roster", (r) => (r.request().method() === "PUT" && fail ? r.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Service momentanément indisponible" }) }) : r.continue()));
  await box.setChecked(!initial);
  await expect(status).toHaveAttribute("data-save-state", "error", { timeout: 15_000 });
  await expect(status).toContainText("Échec de l'enregistrement");
  await expect(box).toBeChecked({ checked: !initial }); // la modification reste à l'écran, prête à être renvoyée
  const code = (await roster(page, jan.id)); expect(code.length).toBeGreaterThan(0);
  fail = false;
  await saved(page, () => status.getByRole("button", { name: "Réessayer" }).click());
  const name = (await list.locator("li").first().locator("strong").textContent())!.trim();
  const row = (await j(page, `/periods/${jan.id}/roster`)).employees.find((x: { name: string }) => x.name === name);
  expect(row.included).toBe(!initial); // confirmé par le serveur
  await saved(page, () => box.setChecked(initial)); // remise en l'état
  await page.unroute("**/roster");
});
