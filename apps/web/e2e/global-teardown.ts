import { execFileSync } from "node:child_process";

/** Nettoyage des fiches d'essai créées par e2e/team.spec.ts (« Camille ESSAI-… »), UNIQUEMENT dans le tenant de test dédié
 *  (@e2e.example) et seulement si elles n'ont aucune affectation. Sans accès à la base (E2E_DB_CONTAINER absent ou docker indisponible),
 *  rien n'est fait : les fiches restent supprimées (invisibles des listes et des plannings). */
export default async function globalTeardown() {
  const email = process.env.E2E_EMAIL ?? "";
  if (!email.endsWith("@e2e.example") || process.env.E2E_DB_CLEANUP === "0") return;
  const container = process.env.E2E_DB_CONTAINER ?? "planning-postgres-1";
  const user = process.env.POSTGRES_USER ?? "planning_owner", db = process.env.POSTGRES_DB ?? "planning";
  const sql = `DELETE FROM employees e USING users u WHERE u.email = '${email.replace(/'/g, "''")}' AND e.tenant_id = u.tenant_id
    AND e.first_name = 'Camille' AND e.last_name LIKE 'ESSAI-%' AND NOT EXISTS (SELECT 1 FROM assignments a WHERE a.employee_id = e.id)`;
  try { execFileSync("docker", ["exec", container, "psql", "-U", user, "-d", db, "-qc", sql], { stdio: "ignore", timeout: 20_000 }); }
  catch { /* nettoyage facultatif */ }
}
