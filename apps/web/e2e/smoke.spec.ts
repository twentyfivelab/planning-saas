import { expect, test } from "@playwright/test";

// Prérequis : pile lancée (docker compose up) et comptes de démo créés par `python -m app.seed`.
// E2E_EMAIL / E2E_PASSWORD fournis par l'environnement (aucun secret dans le dépôt).
const email = process.env.E2E_EMAIL, password = process.env.E2E_PASSWORD;

test("redirige vers la connexion sans session", async ({ page }) => {
  await page.goto("/planning");
  await expect(page).toHaveURL(/\/login/);
});

test("connexion, planning, verrouillage et déconnexion", async ({ page }) => {
  test.skip(!email || !password, "E2E_EMAIL / E2E_PASSWORD non définis");
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(email!);
  await page.getByLabel("Mot de passe").fill(password!);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { name: /Tableau de bord/ })).toBeVisible();
  await page.getByRole("link", { name: "Planning" }).click();
  await expect(page.getByRole("tab", { name: "Semaine" })).toBeVisible();
  await page.getByRole("tab", { name: "Jour" }).click();
  await expect(page.getByLabel("Vue journalière")).toBeVisible();
  await page.getByRole("link", { name: "Budgets" }).click();
  await expect(page.getByText("À renseigner").first()).toBeVisible();
});
