import { expect, test, type Page } from "@playwright/test";
import { API, getJson as j } from "./api";

// Règles et opérations de planning : horaires obligatoires, absences partielles, présence continue, temps de déplacement,
// échange réciproque et duplication (même confirmation que les autres modifications). Chaque test remet les données en l'état.
test.skip(!process.env.E2E_EMAIL, "E2E_EMAIL non défini");
test.describe.configure({ mode: "serial" });

type Row = { assignment_id: string; shift_id: string; employee_id: string; employee: string; day: string; start: string; end: string; site: string; locked: boolean };
const csrf = async (page: Page) => (await j(page, "/auth/me")).csrf_token as string;
const novId = async (page: Page) => ((await j(page, "/periods")) as { id: string; start_date: string }[]).find((p) => p.start_date === "2026-11-01")!.id;

test("fiche : horaires obligatoires et absence sur une partie de la journée", async ({ page }) => {
  const emps = (await j(page, "/employees")) as { id: string; name: string; deleted_at: string | null }[];
  const e = emps.find((x) => !x.deleted_at)!;
  await page.goto("/employees"); await page.waitForLoadState("networkidle");
  await page.getByRole("row", { name: new RegExp(`^${e.name} `) }).getByRole("button", { name: "Fiche" }).click();
  const sheet = page.getByRole("dialog", { name: `Fiche — ${e.name}` });
  const win = sheet.getByTestId("work-window");
  await win.getByLabel("Début au plus tôt").fill("07:00");
  await win.getByLabel("Fin au plus tard").fill("06:00");
  await expect(win.getByRole("alert")).toHaveText("La fin doit suivre le début.");
  await expect(win.getByRole("button", { name: "Enregistrer" })).toBeDisabled();
  await win.getByLabel("Fin au plus tard").fill("23:00");
  await win.getByRole("button", { name: "Enregistrer" }).click();
  await expect.poll(async () => ((await j(page, "/employee-preferences")) as { employee_id: string; kind: string; params: { start: string; end: string } }[])
    .find((p) => p.employee_id === e.id && p.kind === "work_window")?.params).toEqual({ start: "07:00", end: "23:00" });
  await win.getByRole("button", { name: "Aucune limite" }).click();
  await expect.poll(async () => ((await j(page, "/employee-preferences")) as { employee_id: string; kind: string }[]).some((p) => p.employee_id === e.id && p.kind === "work_window")).toBe(false);

  const pa = sheet.getByTestId("partial-absences");
  await pa.getByLabel("Jour").fill("2026-11-24");
  await pa.getByLabel("De").fill("09:00");
  await pa.getByLabel("À", { exact: true }).fill("11:30");
  await pa.getByLabel("Motif (facultatif)").fill("rendez-vous");
  await pa.getByRole("button", { name: "Ajouter" }).click();
  await expect(pa.getByText("24/11/2026 · 09:00–11:30")).toBeVisible();
  await pa.getByRole("button", { name: "Retirer l'absence du 24/11/2026" }).click();
  await expect(pa.getByText("24/11/2026 · 09:00–11:30")).toBeHidden();
});

test("sites : présence continue (alerte de pause sans relève) et temps de déplacement", async ({ page }) => {
  const sites = (await j(page, "/sites")) as { id: string; code: string; name: string; continuous_presence: boolean; archived_from: string | null }[];
  const [s1, s2] = sites.filter((s) => !s.archived_from);
  await page.goto("/catalog"); await page.waitForLoadState("networkidle");
  const rules = page.getByTestId("site-rules");
  // la case de CE réglage (la section « Pauses payées » liste aussi les sites, sous le même nom)
  const box = rules.getByRole("group", { name: "Présence continue" }).getByRole("checkbox", { name: s1.name, exact: true });
  await box.check();
  await expect.poll(async () => ((await j(page, "/sites")) as typeof sites).find((s) => s.id === s1.id)!.continuous_presence).toBe(true);
  try {
    await page.goto("/alerts"); await page.waitForLoadState("networkidle");
    await expect(page.getByTestId("break-coverage")).toBeVisible(); // signalement, jamais un blocage
    await page.goto("/catalog"); await page.waitForLoadState("networkidle");
    await rules.getByLabel("De").selectOption(s1.code);
    await rules.getByLabel("À", { exact: true }).selectOption(s2.code);
    await rules.getByLabel("Minutes").fill("35");
    await rules.getByRole("button", { name: "Ajouter" }).click();
    await expect(rules.getByText(`${s1.name} ↔ ${s2.name}`)).toBeVisible();
    await rules.getByRole("button", { name: `Retirer le temps entre ${s1.name} et ${s2.name}` }).click();
    await expect(rules.getByText(`${s1.name} ↔ ${s2.name}`)).toBeHidden();
  } finally {
    const token = await csrf(page);
    await page.request.put(`${API}/sites/${s1.id}`, { headers: { "X-CSRF-Token": token }, data: { code: s1.code, name: s1.name, continuous_presence: s1.continuous_presence } });
  }
});

test("échange réciproque et duplication depuis le détail d'un shift : même confirmation, rien sans validation", async ({ page }) => {
  const pid = await novId(page);
  const rows = (await j(page, `/periods/${pid}/schedule`)).assignments as Row[];
  const day = "2026-11-02";
  const [a, b] = rows.filter((x) => x.day === day && !x.locked);
  expect(a && b && a.employee_id !== b.employee_id).toBeTruthy();
  await page.goto("/planning"); await page.waitForLoadState("networkidle");
  const openCard = async (r: Row) => page.locator(`.cal-cell[aria-label="${r.employee}, Lun 2 nov."] .shift`).first().click();

  // échange : choix, aperçu, enregistrement (avec confirmation si des alertes sont listées)
  await openCard(a);
  await page.getByRole("button", { name: "Échanger…" }).click();
  const sw = page.getByTestId("swap-modal");
  await sw.getByLabel("Avec").selectOption(b.employee_id);
  await sw.getByLabel("Son shift").selectOption(b.assignment_id);
  await expect(sw).toContainText(`${a.employee} prendra`);
  const swapResp = page.waitForResponse((r) => r.url().includes("/swap") && r.request().method() === "POST");
  await sw.getByRole("button", { name: "Échanger", exact: true }).click();
  await swapResp; // la réponse est arrivée : soit enregistré, soit alertes affichées
  const confirmSwap = sw.getByRole("button", { name: "Confirmer l'échange" });
  if (await confirmSwap.isVisible().catch(() => false)) {
    await expect(sw.getByTestId("op-issues")).toBeVisible();
    await confirmSwap.click();
  }
  await expect.poll(async () => ((await j(page, `/periods/${pid}/schedule`)).assignments as Row[]).find((x) => x.assignment_id === a.assignment_id)!.employee_id).toBe(b.employee_id);
  const token = await csrf(page);
  // remise en l'état : échange inverse
  const back = await page.request.post(`${API}/periods/${pid}/swap`, { headers: { "X-CSRF-Token": token }, data: { a: a.assignment_id, b: b.assignment_id, force: true, reason: "remise en l'état e2e" } });
  expect(back.status(), await back.text()).toBe(200);
  for (const id of [a.assignment_id, b.assignment_id]) await page.request.post(`${API}/assignments/${id}/unlock`, { headers: { "X-CSRF-Token": token } });

  // duplication : Annuler ne crée rien ; le plafond mensuel bloque sans dérogation possible ; une copie confirmée apparaît, puis est retirée
  await page.reload(); await page.waitForLoadState("networkidle");
  const now = (await j(page, `/periods/${pid}/schedule`)).assignments as Row[] & { effective_minutes?: number }[];
  const used: Record<string, number> = {};
  for (const x of now as unknown as { employee_id: string; effective_minutes: number }[]) used[x.employee_id] = (used[x.employee_id] ?? 0) + x.effective_minutes;
  const onDay = (now as unknown as (Row & { effective_minutes: number })[]).filter((x) => x.day === day);
  const roomy = onDay.find((x) => used[x.employee_id] + x.effective_minutes <= 176 * 60);
  const full = onDay.find((x) => used[x.employee_id] + x.effective_minutes > 176 * 60);
  const before = now.length;
  const freeDay = (eid: string) => {
    const mine = new Set(now.filter((x) => x.employee_id === eid).map((x) => x.day));
    return Array.from({ length: 30 }, (_, k) => `2026-11-${String(k + 1).padStart(2, "0")}`).find((d) => !mine.has(d))!;
  };
  const dup = page.getByTestId("duplicate-modal");
  const pickDay = (d: string) => dup.getByRole("group", { name: "Jours de copie" }).locator("label").nth(Number(d.slice(8)) - 1).locator("input").check();
  if (full) {
    await openCard(full);
    await page.getByRole("button", { name: "Dupliquer…" }).click();
    await pickDay(freeDay(full.employee_id));
    await dup.getByRole("button", { name: /^Dupliquer sur 1 jour$/ }).click();
    await expect(dup.getByText("Opération impossible")).toBeVisible();
    await expect(dup.getByTestId("op-issues")).toContainText("Plafond mensuel de 176 h");
    await expect(dup.getByRole("button", { name: /^Dupliquer sur 1 jour$/ })).toBeDisabled();
    await dup.getByRole("button", { name: "Annuler" }).click();
    expect(((await j(page, `/periods/${pid}/schedule`)).assignments as Row[]).length).toBe(before);
  }
  expect(roomy, "un collaborateur sous le plafond le 2 novembre").toBeTruthy();
  const c = roomy!;
  const free = freeDay(c.employee_id);
  await openCard(c);
  await page.getByRole("button", { name: "Dupliquer…" }).click();
  await pickDay(free);
  await dup.getByRole("button", { name: "Annuler" }).click();
  expect(((await j(page, `/periods/${pid}/schedule`)).assignments as Row[]).length).toBe(before);
  await openCard(c);
  await page.getByRole("button", { name: "Dupliquer…" }).click();
  await pickDay(free);
  const dupResp = page.waitForResponse((r) => r.url().includes("/duplicate") && r.request().method() === "POST");
  await dup.getByRole("button", { name: /^Dupliquer sur 1 jour$/ }).click();
  await dupResp;
  const confirmDup = dup.getByRole("button", { name: "Confirmer la duplication" });
  if (await confirmDup.isVisible().catch(() => false)) await confirmDup.click();
  let copy: Row | undefined;
  await expect.poll(async () => {
    copy = ((await j(page, `/periods/${pid}/schedule`)).assignments as Row[]).find((x) => x.employee_id === c.employee_id && x.day === free);
    return copy ? [copy.start, copy.end, copy.site] : null;
  }).toEqual([c.start, c.end, c.site]);
  const del = await page.request.delete(`${API}/assignments/${copy!.assignment_id}?force=true`, { headers: { "X-CSRF-Token": token } });
  expect(del.status()).toBe(204);
  expect(((await j(page, `/periods/${pid}/schedule`)).assignments as Row[]).length).toBe(before);
});

test("vue semaine : du lundi au dimanche, shifts exacts jour par jour, navigation entre les semaines, mobile sans débordement", async ({ page }) => {
  const pid = ((await j(page, "/periods")) as { id: string; start_date: string }[]).find((p) => p.start_date === "2026-11-01")!.id;
  const rows = (await j(page, `/periods/${pid}/schedule`)).assignments as Row[];
  await page.goto("/planning"); await page.waitForLoadState("networkidle");
  await page.getByRole("tab", { name: "Semaine" }).click();
  const wv = page.getByTestId("week-view");
  await expect(wv).toBeVisible();
  const check = async () => {
    const cells = await wv.locator(".week-col").evaluateAll((els) => els.map((e) => [e.getAttribute("data-day"), Number(e.getAttribute("data-count")), e.hasAttribute("data-outside")] as const));
    expect(cells).toHaveLength(7);
    expect(new Date(`${cells[0][0]}T12:00:00Z`).getUTCDay()).toBe(1); // commence un lundi
    for (const [day, n, outside] of cells) if (!outside) expect(n, day!).toBe(rows.filter((r) => r.day === day).length);
    return cells[0][0];
  };
  const first = await check();
  await wv.getByRole("button", { name: "Semaine suivante" }).click();
  const second = await check();
  expect(second).not.toBe(first);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
});
