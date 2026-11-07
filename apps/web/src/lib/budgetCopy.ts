import { api } from "./api";
import { shiftMonthKey } from "./months";

type B = { brand_code: string; month: string; target_minutes: number; requirements_defined: boolean; strict?: boolean };

/** Copie EXPLICITE (jamais silencieuse) des budgets du mois précédent vers `month` ; retourne le nombre de budgets créés. */
export async function copyPreviousBudgets(month: string): Promise<number> {
  const prev = `${shiftMonthKey(month, -1)}-01`, target = `${month}-01`;
  const all = await api<B[]>("/budgets");
  const have = new Set(all.filter((b) => b.month === target).map((b) => b.brand_code));
  const todo = all.filter((b) => b.month === prev && !have.has(b.brand_code));
  for (const b of todo) await api("/budgets", { method: "POST", json: { brand_code: b.brand_code, month: target, target_minutes: b.target_minutes, requirements_defined: b.requirements_defined, strict: b.strict ?? true } });
  return todo.length;
}
