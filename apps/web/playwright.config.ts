import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  globalSetup: "./e2e/global-setup.ts",
  globalTeardown: "./e2e/global-teardown.ts",
  use: {
    baseURL: process.env.WEB_URL ?? "http://localhost:3000", storageState: "e2e/.auth/state.json",
    // diagnostic des échecs intermittents : trace conservée UNIQUEMENT en cas d'échec (réseau, durées, en-tête Server-Timing du serveur,
    // état de la page) ; supprimée si le test réussit. Sans captures d'écran, pour limiter le coût d'enregistrement.
    trace: { mode: "retain-on-failure", screenshots: false, snapshots: true, sources: false },
  },
  workers: 1, // les tests modifient des données partagées : exécution séquentielle
  timeout: 60_000,
});
