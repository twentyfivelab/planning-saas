import { expect, test, type Page } from "@playwright/test";
import { API, getJson as j } from "./api";

// Récupération contrôlée d'un planning supprimé, depuis l'événement de suppression de l'historique : aperçu, mot de passe, nouveau
// planning identique à l'archive, ancien planning et trace inchangés. Mois dédié (mai 2027) : aucun autre test n'en dépend.
test.skip(!process.env.E2E_EMAIL || !process.env.E2E_PASSWORD, "E2E_EMAIL / E2E_PASSWORD non définis");

const csrf = async (page: Page) => (await j(page, "/auth/me")).csrf_token as string;
type A = { day: string; start: string; end: string; site: string; employee_id: string; locked: boolean };
const rows = async (page: Page, pid: string) => ((await j(page, `/periods/${pid}/schedule`)).assignments as A[]).map((a) => [a.day, a.start, a.end, a.site, a.employee_id, a.locked].join("|")).sort();

test("récupérer un planning supprimé depuis l'historique", async ({ page }) => {
  const token = await csrf(page);
  const H = { "X-CSRF-Token": token };
  const pw = process.env.E2E_PASSWORD!;
  const pid = (await (await page.request.post(`${API}/periods/ensure`, { headers: H, data: { year: 2027, month: 5 } })).json()).id as string;
  let recovered = "";
  try {
    if (!((await j(page, `/periods/${pid}/schedule`)).assignments as unknown[]).length) {
      const run = await page.request.post(`${API}/periods/${pid}/runs`, { headers: { ...H, "Idempotency-Key": `rec-${Date.now()}` }, data: { time_limit_s: 10 } });
      expect(run.status(), await run.text()).toBe(202);
      await expect.poll(async () => ((await j(page, `/periods/${pid}/schedule`)).assignments as unknown[]).length, { timeout: 90_000 }).toBeGreaterThan(0);
    }
    const before = await rows(page, pid);
    const nov = ((await j(page, "/periods")) as { id: string; start_date: string }[]).find((p) => p.start_date === "2026-11-01")!.id;
    const novBefore = await rows(page, nov);
    expect((await page.request.post(`${API}/periods/${pid}/delete`, { headers: H, data: { password: pw } })).status()).toBe(200);
    await page.goto("/history?kind=deletion"); await page.waitForLoadState("networkidle");
    const ev = page.getByTestId("history-event").filter({ hasText: "Planning de mai 2027" }).first();
    await ev.getByTestId("recover-open").click();
    const dlg = page.getByRole("dialog", { name: "Récupérer le planning de mai 2027 ?" });
    await expect(dlg.getByTestId("recover-summary")).toContainText(String(before.length));
    await dlg.getByRole("button", { name: "Annuler" }).click(); // annuler : rien n'est créé
    expect(((await j(page, "/periods")) as { start_date: string }[]).some((p) => p.start_date === "2027-05-01")).toBe(false);
    await ev.getByTestId("recover-open").click();
    await dlg.getByLabel("Mot de passe de votre compte").fill("pas-le-bon");
    await dlg.getByRole("button", { name: "Confirmer la récupération" }).click();
    await expect(dlg.getByTestId("recover-error")).toHaveText("Mot de passe incorrect. Rien n'a été modifié.");
    await dlg.getByLabel("Mot de passe de votre compte").fill(pw);
    await dlg.getByRole("button", { name: "Confirmer la récupération" }).click();
    await expect(page.getByText(/Le planning de mai 2027 a été récupéré/).first()).toBeVisible();
    await expect(page.getByTestId("history-event").first()).toContainText("Récupération d'un planning supprimé");
    recovered = ((await j(page, "/periods")) as { id: string; start_date: string }[]).find((p) => p.start_date === "2027-05-01")!.id;
    expect(recovered).not.toBe(pid);
    expect(await rows(page, recovered)).toEqual(before);
    expect(await rows(page, nov)).toEqual(novBefore); // autre mois intact
    expect((await page.request.get(`${API}/periods/${pid}/schedule`)).status()).toBe(404); // l'ancien reste supprimé
  } finally {
    const live = ((await j(page, "/periods")) as { id: string; start_date: string }[]).find((p) => p.start_date === "2027-05-01");
    if (live) await page.request.post(`${API}/periods/${live.id}/delete`, { headers: H, data: { password: pw } });
  }
});
