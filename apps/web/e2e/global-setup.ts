import { request, type FullConfig } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/** Une seule connexion pour toute la suite (le login est limité en débit) : cookies réutilisés via storageState. */
export default async function globalSetup(_: FullConfig) {
  const email = process.env.E2E_EMAIL, password = process.env.E2E_PASSWORD;
  const file = path.join(__dirname, ".auth", "state.json");
  fs.mkdirSync(path.dirname(file), { recursive: true });
  if (!email || !password) { fs.writeFileSync(file, JSON.stringify({ cookies: [], origins: [] })); return; }
  // ces tests modifient et régénèrent les plannings du compte utilisé : jamais sur les données que l'on consulte
  if (!email.endsWith("@e2e.example") && process.env.E2E_ALLOW_ANY_TENANT !== "1") throw new Error(`E2E_EMAIL doit être un compte du tenant de test dédié (@e2e.example), pas ${email}. Voir le README.`);
  const api = await request.newContext({ baseURL: process.env.API_URL ?? "http://localhost:8000" });
  const res = await api.post("/auth/login", { data: { email, password } });
  if (!res.ok()) throw new Error(`Connexion e2e impossible (${res.status()})`);
  await api.storageState({ path: file });
  await api.dispose();
}
