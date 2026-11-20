import { expect, test } from "@playwright/test";
import path from "node:path";

// Accessibilité (axe-core, règles WCAG 2.1 A et AA) des écrans essentiels, en clair : aucune violation « grave » ou « critique ».
// Les violations mineures ou modérées sont listées dans le rapport du test (annotations) sans le faire échouer.
test.skip(!process.env.E2E_EMAIL, "E2E_EMAIL non défini");

const PAGES = ["/", "/planning", "/generate", "/plannings/new", "/catalog", "/employees", "/budgets", "/history", "/notifications", "/settings", "/me"];
const AXE = path.resolve("node_modules/axe-core/axe.min.js");

type Violation = { id: string; impact: string | null; help: string; nodes: { target: string[] }[] };

for (const url of PAGES) {
  test(`accessibilité : ${url}`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    const res = await page.goto(url);
    expect(res?.status() ?? 200).toBeLessThan(400);
    await page.locator("main, #contenu, .page").first().waitFor({ timeout: 30_000 });
    await page.waitForTimeout(300); // fin des animations d'apparition (contrastes mesurés sur l'état final)
    await page.addScriptTag({ path: AXE });
    const v = (await page.evaluate(async () => {
      // @ts-expect-error axe injecté
      const r = await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] }, resultTypes: ["violations"] });
      return r.violations.map((x: Violation) => ({ id: x.id, impact: x.impact, help: x.help, nodes: x.nodes.slice(0, 5).map((n) => ({ target: n.target })) }));
    })) as Violation[];
    for (const x of v) test.info().annotations.push({ type: `axe:${x.impact}`, description: `${x.id} — ${x.help} — ${x.nodes.map((n) => n.target.join(" ")).join(" | ")}` });
    const blocking = v.filter((x) => x.impact === "serious" || x.impact === "critical");
    expect(blocking.map((x) => `${x.impact} ${x.id}: ${x.help} → ${x.nodes.map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
  });
}

test("planning : une carte atteinte au clavier n'est jamais masquée par l'en-tête, les noms ou les totaux (WCAG 2.4.11)", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/planning");
  const cards = page.getByRole("region", { name: /Planning général/ }).locator(".shift");
  await cards.first().waitFor({ timeout: 30_000 });
  const n = await cards.count();
  test.skip(n < 3, "planning trop petit");
  for (const i of [n - 1, Math.floor(n / 2), 0]) { // dernière carte (jours de fin de mois, près des totaux), milieu, première
    const card = cards.nth(i);
    await card.focus();
    await page.waitForTimeout(150);
    const covered = await card.evaluate((el) => {
      const r = el.getBoundingClientRect();
      const hit = document.elementFromPoint(r.left + r.width / 2, r.top + Math.min(r.height / 2, 12));
      return hit && !el.contains(hit) ? (hit as HTMLElement).className || hit.tagName : null;
    });
    expect(covered, `carte ${i} masquée par ${covered}`).toBeNull();
  }
});
