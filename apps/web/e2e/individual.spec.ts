import { expect, test, type Page } from "@playwright/test";
import { API, getJson as j } from "./api";

// Planning mensuel individuel (depuis la liste et depuis le planning général) et rappels « À régulariser ».
test.skip(!process.env.E2E_EMAIL, "E2E_EMAIL non défini");
test.describe.configure({ mode: "serial" });

type Row = { assignment_id: string; shift_id: string; employee_id: string; employee: string; day: string; start: string; end: string; locked: boolean; effective_minutes: number; allocations: Record<string, number> };
type Emp = { id: string; code: string; name: string; brands: Record<string, string> };
const csrf = async (page: Page) => (await j(page, "/auth/me")).csrf_token as string;
const hm = (m: number) => `${Math.floor(m / 60)} h${m % 60 ? ` ${String(m % 60).padStart(2, "0")}` : ""}`;
let novId = "";

test.beforeAll(async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: "e2e/.auth/state.json" });
  const page = await ctx.newPage();
  novId = ((await j(page, "/periods")) as { id: string; start_date: string }[]).find((p) => p.start_date === "2026-11-01")!.id;
  await ctx.close();
});

test("planning individuel depuis la liste : mois en cours, compteurs exacts, décembre → janvier, mois sans planning, « Aujourd'hui »", async ({ page }) => {
  const rows = (await j(page, `/periods/${novId}/schedule`)).assignments as Row[];
  const emp = ((await j(page, "/employees")) as Emp[]).find((e) => rows.some((a) => a.employee_id === e.id))!;
  const mine = rows.filter((a) => a.employee_id === emp.id);
  const periodsBefore = ((await j(page, "/periods")) as unknown[]).length;
  await page.goto("/employees"); await page.waitForLoadState("networkidle");
  await page.getByRole("row", { name: new RegExp(`^${emp.name} `) }).getByRole("button", { name: emp.name, exact: true }).click();
  const dlg = page.getByTestId("employee-month");
  const label = dlg.getByTestId("employee-month-label");
  await expect(label).toHaveText("Novembre 2026"); // mois en cours (17/11/2026)
  await expect(dlg.getByTestId("em-effective")).toHaveText(hm(mine.reduce((s, a) => s + a.effective_minutes, 0)));
  await expect(dlg.getByTestId("em-days")).toHaveText(String(new Set(mine.map((a) => a.day)).size));
  await expect(dlg.getByTestId("em-sundays")).toHaveText(String(new Set(mine.filter((a) => new Date(`${a.day}T12:00:00Z`).getUTCDay() === 0).map((a) => a.day)).size));
  await expect(dlg).toContainText("Plafond applicable : 176 h");
  await dlg.getByRole("button", { name: "Mois suivant" }).click();
  await expect(label).toHaveText("Décembre 2026");
  await dlg.getByRole("button", { name: "Mois suivant" }).click();
  await expect(label).toHaveText("Janvier 2027"); // changement d'année
  await dlg.getByRole("button", { name: "Mois précédent" }).click();
  await expect(label).toHaveText("Décembre 2026");
  for (let i = 0; i < 5; i++) await dlg.getByRole("button", { name: "Mois suivant" }).click();
  await expect(label).toHaveText("Mai 2027");
  await expect(dlg.getByText("Aucun planning pour Mai 2027")).toBeVisible(); // message clair, rien de créé
  await dlg.getByRole("button", { name: "Aujourd'hui" }).click();
  await expect(label).toHaveText("Novembre 2026");
  expect(((await j(page, "/periods")) as unknown[]).length).toBe(periodsBefore); // consulter ne crée aucune période
});

test("planning individuel depuis le planning général : mois consulté, détail d'une affectation, filtres conservés au retour", async ({ page }) => {
  await page.goto("/planning"); await page.waitForLoadState("networkidle");
  await page.getByRole("tab", { name: "Planning général" }).click();
  const site = page.getByLabel("Site", { exact: true });
  const firstSite = (await site.locator("option").allTextContents())[1];
  await site.selectOption(firstSite);
  const nameBtn = page.locator(".hgrid .cal-name .name-link").first();
  const name = (await nameBtn.textContent())!.trim();
  await nameBtn.click();
  const dlg = page.getByTestId("employee-month");
  await expect(dlg.getByTestId("employee-month-label")).toHaveText("Novembre 2026"); // mois consulté dans le planning général
  const shift = dlg.locator(".emonth-shift").first();
  if (await shift.count()) {
    await shift.click();
    const detail = dlg.getByTestId("employee-month-detail");
    await expect(detail).toContainText("Horaires");
    const pickTo = detail.getByLabel("Réaffecter à");
    if (await pickTo.isEnabled() && (await pickTo.locator("option").count()) > 1) { // même confirmation que le planning général ; Annuler ne modifie rien
      await pickTo.selectOption({ index: 1 });
      await detail.getByRole("button", { name: "Réaffecter…" }).click();
      const confirm = page.getByRole("dialog", { name: "Confirmer le remplacement ?" });
      await expect(confirm.getByRole("button", { name: "Annuler" })).toBeVisible();
      await confirm.getByRole("button", { name: "Annuler" }).click();
      await expect(dlg.getByTestId("employee-month-label")).toHaveText("Novembre 2026");
    }
  }
  await dlg.getByRole("button", { name: "Fermer" }).last().click();
  await expect(page.getByTestId("employee-month")).toBeHidden();
  await expect(site).toHaveValue(firstSite); // filtre conservé
  await expect(page.getByLabel("Mois", { exact: true })).toHaveValue("11");
  expect(name.length).toBeGreaterThan(0);
});

test("rappel « À régulariser » : double affectation confirmée, rappel persistant, traitement du shift initial, disparition", async ({ page }) => {
  const token = await csrf(page);
  const rows = (await j(page, `/periods/${novId}/schedule`)).assignments as Row[];
  const emps = (await j(page, "/employees")) as Emp[];
  const used: Record<string, number> = {};
  for (const a of rows) used[a.employee_id] = (used[a.employee_id] ?? 0) + a.effective_minutes;
  // un shift A et un collaborateur déjà affecté AILLEURS le même jour, autorisé sur la marque de A et avec de la marge sous le plafond
  let pick: { a: Row; holder: Row } | null = null;
  for (const a of rows.filter((x) => !x.locked && x.day >= "2026-11-10")) {
    const holder = rows.find((x) => x.day === a.day && x.employee_id !== a.employee_id && !x.locked && used[x.employee_id] + a.effective_minutes <= 176 * 60
      && Object.keys(a.allocations).every((b) => b in (emps.find((e) => e.id === x.employee_id)?.brands ?? {})));
    if (holder) { pick = { a, holder }; break; }
  }
  expect(pick, "un cas de double affectation disponible").toBeTruthy();
  const { a, holder } = pick!;
  const r = await page.request.post(`${API}/periods/${novId}/manual-assign`, { headers: { "X-CSRF-Token": token }, data: { employee_id: holder.employee_id, shift_id: a.shift_id, force: true, reason: "essai e2e" } });
  expect(r.status(), await r.text()).toBe(200);
  await page.goto("/planning"); await page.waitForLoadState("networkidle");
  const panel = page.getByTestId("regularizations");
  const note = panel.getByTestId("regularization").filter({ hasText: holder.employee });
  await expect(note).toBeVisible();
  await expect(note).toContainText("Nouvelle affectation :");
  await expect(note).toContainText(`Affectation initiale à traiter`);
  await expect(note).toContainText(`${holder.start.slice(0, 2)} h`);
  await page.reload(); await page.waitForLoadState("networkidle"); // persiste après actualisation
  await expect(note).toBeVisible();
  await note.getByRole("button", { name: "Voir le shift initial" }).click();
  await expect(page.getByRole("dialog").filter({ hasText: holder.employee }).first()).toBeVisible();
  await page.keyboard.press("Escape");
  await note.getByRole("button", { name: "Retirer l'affectation" }).click();
  const confirm = page.getByRole("dialog", { name: "Retirer ce shift ?" });
  await confirm.getByRole("button", { name: "Retirer le shift" }).click();
  await expect(note).toBeHidden(); // disparaît après enregistrement réussi
  const after = await j(page, `/periods/${novId}/schedule`);
  expect((after.uncovered as { shift_id: string }[]).some((u) => u.shift_id === holder.shift_id)).toBe(true); // besoin conservé dans la couverture
});
