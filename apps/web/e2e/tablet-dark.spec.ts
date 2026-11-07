import { expect, test, type Page } from "@playwright/test";

// Tablette (iPad Air portrait 820×1180 et paysage 1180×820), écran tactile, thème sombre.
test.skip(!process.env.E2E_EMAIL, "E2E_EMAIL non défini");
test.describe.configure({ mode: "serial" });
const API = process.env.API_URL ?? "http://localhost:8000";
const SHOTS = process.env.SHOTS_DIR;

/** Contraste WCAG entre la couleur du texte et le fond effectif (premier ancêtre opaque). */
async function contrast(page: Page, selector: string): Promise<number[]> {
  return page.$$eval(selector, (els) => els.slice(0, 12).map((el) => {
    const parse = (c: string) => { const m = c.match(/[\d.]+/g)!.map(Number); return { r: m[0], g: m[1], b: m[2], a: m[3] ?? 1 }; };
    const lum = ({ r, g, b }: { r: number; g: number; b: number }) => { const f = (v: number) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
    let n: Element | null = el, bg = { r: 0, g: 0, b: 0, a: 0 };
    while (n) { const c = parse(getComputedStyle(n).backgroundColor); if (c.a > 0.85) { bg = c; break; } n = n.parentElement; }
    if (!n) bg = parse(getComputedStyle(document.body).backgroundColor);
    const fg = parse(getComputedStyle(el).color);
    const [L1, L2] = [lum(fg), lum(bg)].sort((a, b) => b - a);
    return +((L1 + 0.05) / (L2 + 0.05)).toFixed(2);
  }));
}
async function swipe(page: Page, x: number, y: number, dx: number) {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Input.synthesizeScrollGesture", { x, y, xDistance: dx, yDistance: 0, gestureSourceType: "touch", speed: 1200 });
}
const noPageOverflow = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
const shot = async (page: Page, name: string) => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` }); };

for (const [orient, vp] of [["portrait", { width: 820, height: 1180 }], ["paysage", { width: 1180, height: 820 }]] as const) {
  test.describe(`tablette ${orient}, thème sombre`, () => {
    test.use({ viewport: vp, hasTouch: true, colorScheme: "dark", deviceScaleFactor: 2 });

    test(`planning général : glisser au doigt, noms fixes, contrastes (${orient})`, async ({ page }) => {
      await page.goto("/planning"); await page.waitForLoadState("networkidle");
      const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
      expect(bg).not.toBe("rgb(255, 255, 255)"); // le thème sombre est appliqué
      expect(await noPageOverflow(page)).toBe(true); // jamais de défilement horizontal de la page entière
      const sc = page.getByRole("region", { name: /Planning général/ });
      await sc.scrollIntoViewIfNeeded();
      const box = (await sc.boundingBox())!;
      const name0 = (await page.locator(".hgrid .cal-name").first().boundingBox())!.x;
      await shot(page, `tablette-${orient}-sombre-planning-avant`);
      await swipe(page, box.x + box.width * 0.75, box.y + Math.min(200, box.height / 2), -Math.round(box.width * 0.6)); // glisser vers la gauche = jours suivants
      await expect.poll(() => sc.evaluate((e) => e.scrollLeft)).toBeGreaterThan(150);
      expect((await page.locator(".hgrid .cal-name").first().boundingBox())!.x).toBeCloseTo(name0, 0); // colonne des noms fixe
      const misaligned = await page.evaluate(() => {
        const heads = [...document.querySelectorAll(".hgrid-head .cal-h")].slice(1, -1) as HTMLElement[];
        const cells = [...document.querySelectorAll(".hgrid-row")[1].querySelectorAll(".cal-cell")].slice(0, -1) as HTMLElement[];
        return heads.filter((h, i) => Math.abs(h.getBoundingClientRect().left - cells[i].getBoundingClientRect().left) > 1).length;
      });
      expect(misaligned).toBe(0);
      await shot(page, `tablette-${orient}-sombre-planning-apres`);
      await swipe(page, box.x + box.width * 0.25, box.y + Math.min(200, box.height / 2), Math.round(box.width * 0.6)); // vers la droite = jours précédents
      await expect.poll(() => sc.evaluate((e) => e.scrollLeft)).toBeLessThan(150);
      for (const sel of [".hgrid .cal-name", ".hgrid .cal-h", ".hgrid .shift-time", ".hgrid .cal-total", ".page h1, .page .h1"]) {
        const c = await contrast(page, sel);
        expect(c.length, sel).toBeGreaterThan(0);
        expect(Math.min(...c), `contraste ${sel}`).toBeGreaterThanOrEqual(4.5);
      }
      // les flèches restent atteignables au doigt
      const next = page.getByRole("button", { name: "Jours suivants" });
      expect((await next.boundingBox())!.height).toBeGreaterThanOrEqual(32);
      await next.tap();
      await expect.poll(() => sc.evaluate((e) => e.scrollLeft)).toBeGreaterThan(0);
    });

    test(`fenêtres d'affectation : tiennent dans l'écran, cibles tactiles, contrastes (${orient})`, async ({ page }) => {
      const pid = ((await (await page.request.get(`${API}/periods`)).json()) as { id: string; start_date: string }[]).find((p) => p.start_date === "2026-11-01")!.id;
      const rows = (await (await page.request.get(`${API}/periods/${pid}/schedule`)).json()).assignments as { employee: string; day: string; locked: boolean }[];
      const day = "2026-11-10";
      const busy = new Set(rows.filter((r) => r.day === day).map((r) => r.employee));
      const emps = ((await (await page.request.get(`${API}/employees`)).json()) as { name: string; code: string }[]).filter((e) => !busy.has(e.name) && e.code !== "sabrina");
      const who = emps[0].name;
      await page.goto("/planning"); await page.waitForLoadState("networkidle");
      await page.getByRole("tab", { name: "Collaborateur" }).tap();
      await page.getByLabel("Collaborateur", { exact: true }).last().selectOption({ label: who });
      await page.getByRole("button", { name: `Shifts du Mar 10 nov. pour ${who}` }).tap();
      const dlg = page.getByRole("dialog", { name: new RegExp(`Ajouter un jour de travail — ${who}`) });
      await expect(dlg).toBeVisible();
      await expect(dlg.locator(".dshift").first()).toBeVisible();
      const inView = async () => { const b = (await dlg.boundingBox())!; return b.x >= -1 && b.y >= -1 && b.x + b.width <= page.viewportSize()!.width + 1 && b.y + b.height <= page.viewportSize()!.height + 1; };
      expect(await inView()).toBe(true);
      const heights = await dlg.locator(".dshift").evaluateAll((els) => els.map((e) => e.getBoundingClientRect().height));
      expect(Math.min(...heights)).toBeGreaterThanOrEqual(44); // cibles tactiles confortables
      for (const sel of ['[role="dialog"] .dshift-main strong', '[role="dialog"] .dshift-main .muted', '[role="dialog"] h2', '[role="dialog"] .dshift-go']) {
        const c = await contrast(page, sel);
        expect(Math.min(...c), `contraste ${sel}`).toBeGreaterThanOrEqual(4.5);
      }
      await shot(page, `tablette-${orient}-sombre-fenetre-jour`);
      const occupied = dlg.locator('.dshift[data-status="assigned"]').first();
      await occupied.tap();
      const confirm = dlg.getByRole("button", { name: "Confirmer le transfert" });
      await expect(confirm).toBeVisible();
      expect(await inView()).toBe(true);
      await confirm.scrollIntoViewIfNeeded();
      expect((await confirm.boundingBox())!.y + 40).toBeLessThanOrEqual(page.viewportSize()!.height);
      await shot(page, `tablette-${orient}-sombre-confirmation`);
      // on ne modifie rien : retour à la liste puis fermeture
      await dlg.getByRole("button", { name: "Retour" }).tap();
      await dlg.getByRole("button", { name: "Fermer", exact: true }).last().tap();
      await expect(dlg).toBeHidden();
      expect(await noPageOverflow(page)).toBe(true);
    });
  });
}
