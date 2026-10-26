import { expect, test, type Page } from "@playwright/test";

// Prérequis : pile lancée + comptes de démo ; E2E_EMAIL / E2E_PASSWORD fournis par l'environnement.
const email = process.env.E2E_EMAIL, password = process.env.E2E_PASSWORD;
test.skip(!email || !password, "E2E_EMAIL / E2E_PASSWORD non définis");

// Session partagée (global-setup) : le login est limité en débit ; le formulaire est testé dans smoke.spec.ts.
async function login(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();
}

test("tableau de bord : indicateurs, budgets, hypothèses et avertissement légal visibles", async ({ page }) => {
  await login(page);
  await expect(page.getByText("Taux de couverture")).toBeVisible();
  await expect(page.getByText("Heures par marque")).toBeVisible();
  await expect(page.getByText(/128 h non planifiables/)).toBeVisible();
  await expect(page.getByText("Hypothèses et contraintes non validées")).toBeVisible();
  await expect(page.getByText(/non commercialisable en l'état/i).first()).toBeVisible();
  await page.getByRole("link", { name: "Générer le planning" }).click();
  await expect(page).toHaveURL(/\/generate/);
});

test("planning : semaine complète, légende, navigation, vues, filtres", async ({ page }) => {
  await login(page);
  await page.goto("/planning");
  await expect(page.getByRole("tab", { name: "Semaine" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByText("Lun 2 nov. – Dim 8 nov.")).toBeVisible(); // pas la semaine d'un seul jour
  await expect(page.getByRole("group", { name: "Légende" })).toContainText("Répartition co-branding");
  await page.getByRole("button", { name: "Semaine suivante" }).click();
  await expect(page.getByText("Lun 9 nov. – Dim 15 nov.")).toBeVisible();
  for (const v of ["Mois", "Jour", "Collaborateur", "Marque / site"]) {
    await page.getByRole("tab", { name: v, exact: true }).click();
    await expect(page.getByRole("tab", { name: v, exact: true })).toHaveAttribute("aria-selected", "true");
  }
  await page.getByRole("tab", { name: "Marque / site" }).click();
  await expect(page.getByText("À renseigner").first()).toBeVisible(); // Lindt / Toblerone
  await page.getByRole("tab", { name: "Semaine" }).click();
  await page.getByLabel("Site").selectOption("Cartier");
  await expect(page.getByText(/affectations? \(filtré\)/)).toBeVisible();
  await page.getByRole("button", { name: "Réinitialiser" }).click();
});

test("clavier : une carte de shift s'ouvre à Entrée, Échap ferme et rend le focus", async ({ page }) => {
  await login(page);
  await page.goto("/planning");
  const card = page.locator(".shift").first();
  await card.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("Travail effectif");
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
});

test("verrouillage depuis la fiche, puis déverrouillage", async ({ page }) => {
  await login(page);
  await page.goto("/planning");
  await page.locator(".shift").first().click();
  await page.getByRole("button", { name: "Verrouiller" }).click();
  await expect(page.getByText(/Affectation verrouillée/)).toBeVisible();
  await expect(page.locator('.shift[data-locked="true"]').first()).toBeVisible();
  await page.locator('.shift[data-locked="true"]').first().click();
  await page.getByRole("button", { name: "Déverrouiller" }).click();
  await expect(page.getByText("Affectation déverrouillée.")).toBeVisible();
});

test("thème : le choix est mémorisé et appliqué avant hydratation", async ({ page }) => {
  await login(page);
  const toggle = page.getByRole("button", { name: /Thème/ });
  await toggle.click(); // automatique -> clair
  await toggle.click(); // clair -> sombre
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await toggle.click(); // sombre -> automatique
});

test("mobile : menu, bandeau légal replié, pas de débordement horizontal", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  await expect(page.getByRole("button", { name: "Détails" })).toBeVisible(); // replié par défaut sur petit écran
  await page.getByRole("button", { name: "Menu" }).click();
  await page.getByRole("link", { name: "Budgets" }).click();
  await expect(page.getByRole("heading", { name: "Budgets", exact: true })).toBeVisible();
  for (const path of ["/", "/planning", "/budgets", "/generate", "/alerts", "/employees", "/rules", "/versions", "/import-export"]) {
    await page.goto(path);
    await page.waitForTimeout(800);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), path).toBe(true);
  }
});

test("mouvement réduit : aucune animation longue", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await login(page);
  const d = await page.locator(".rise").first().evaluate((el) => getComputedStyle(el).animationDuration);
  expect(parseFloat(d)).toBeLessThan(0.01);
});
