import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  globalSetup: "./e2e/global-setup.ts",
  use: { baseURL: process.env.WEB_URL ?? "http://localhost:3000", storageState: "e2e/.auth/state.json" },
  workers: 1, // les tests modifient des données partagées : exécution séquentielle
  timeout: 60_000,
});
