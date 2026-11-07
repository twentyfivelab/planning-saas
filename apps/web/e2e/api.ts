import type { Page } from "@playwright/test";

export const API = process.env.API_URL ?? "http://localhost:8000";

/** Lecture JSON de l'API avec un délai maximal explicite : une requête sans réponse échoue vite en nommant le chemin
 *  (au lieu de bloquer le test jusqu'à son délai global) ; une seule nouvelle tentative en cas de connexion perdue. */
export async function getJson(page: Page, path: string, timeout = 20_000) {
  for (let attempt = 1; ; attempt++) {
    try {
      const r = await page.request.get(`${API}${path}`, { timeout });
      if (!r.ok()) throw new Error(`GET ${path} → ${r.status()} ${(await r.text()).slice(0, 200)}`);
      return await r.json();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (attempt >= 2 || msg.startsWith(`GET ${path} →`)) throw new Error(`GET ${path} : ${msg}`);
    }
  }
}
