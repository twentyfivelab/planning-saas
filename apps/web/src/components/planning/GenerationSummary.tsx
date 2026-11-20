"use client";
import { Badge, Callout } from "@/components/ui/primitives";
import { useApi } from "@/components/hooks";
import { fmtHM } from "@/lib/schedule";

type State = "ok" | "warn" | "bad" | "info";
type Block = { state: State; title: string; text: string; action?: { label: string; href: string } | null };
type Summary = {
  run: { id: string; status: string; period: string | null; month: string | null; time_limit_s: number | null };
  blocks: {
    rules: Block & { checked: number; violations: string[] };
    coverage: Block & { mandatory: number; covered: number; uncovered: number; uncovered_minutes: number };
    budgets: Block & { brands: { brand: string; target_minutes: number; planned_minutes: number; strict: boolean; state: State }[];
      volume: { after: { mandatory: number; optional: number; minutes: number; optional_minutes: number }; delta_optional: number; delta_optional_minutes: number; note: string | null } | null };
    fairness: Block & { employees: { name: string; minutes: number; unbudgeted_minutes: number; target_minutes: number; deviation_minutes: number; capacity_minutes: number;
      ratio: number | null; flag: string | null; target_status: string | null; reinforce_only: boolean; partially_represented: string[] }[];
      spread: { min: number; max: number } | null; basis?: string; mode?: string; flow_represents?: string[]; flow_not_represented?: string[];
      total_minutes?: number; unbudgeted_minutes?: number };
    remaining: Block & { mandatory_uncovered: number; optional_unassigned: number; optional_minutes: number };
    optimisation: Block & { proved: boolean; levels: { level: string; label?: string; proved: boolean; seconds: number | null }[] };
  };
  priorities: string[];
};

const TONE: Record<State, "ok" | "warn" | "bad" | "info"> = { ok: "ok", warn: "warn", bad: "bad", info: "info" };
const LABEL: Record<State, string> = { ok: "Conforme", warn: "À regarder", bad: "Problème", info: "Information" };
const ORDER: (keyof Summary["blocks"])[] = ["rules", "coverage", "budgets", "fairness", "remaining", "optimisation"];

/** Résultat d'une génération en six blocs distincts : règles obligatoires, couverture, budgets et volume, équité des heures, shifts à
 *  compléter, état de l'optimisation. « Valide », « couverture complète » et « optimum prouvé » sont trois informations différentes. */
export function GenerationSummary({ runId }: { runId: string }) {
  const q = useApi<Summary>(`/runs/${runId}/summary`);
  if (q.error) return <Callout kind="bad" title="Résumé indisponible">{q.error}</Callout>;
  if (!q.data) return <div className="skeleton" style={{ height: "12rem" }} aria-hidden="true" />;
  const s = q.data;
  return (
    <section className="stack" aria-label="Résultat de la génération" data-testid="generation-summary">
      <div className="summary-grid">
        {ORDER.map((k) => {
          const b = s.blocks[k];
          return (
            <article key={k} className="glass card summary-block" data-testid={`summary-${k}`} data-state={b.state}>
              <header className="row" style={{ justifyContent: "space-between" }}><h3 className="h3" style={{ margin: 0 }}>{b.title}</h3><Badge tone={TONE[b.state]}>{LABEL[b.state]}</Badge></header>
              <p style={{ margin: 0 }}>{b.text}</p>
              {k === "rules" && s.blocks.rules.violations.length > 0 && <ul className="help" style={{ margin: 0, paddingLeft: "1.1rem" }}>{s.blocks.rules.violations.slice(0, 5).map((v) => <li key={v}>{v}</li>)}</ul>}
              {k === "budgets" && s.blocks.budgets.brands.length > 0 && (
                <ul className="help" style={{ margin: 0, paddingLeft: "1.1rem" }}>{s.blocks.budgets.brands.map((x) => <li key={x.brand}><strong>{x.brand}</strong> : {fmtHM(x.planned_minutes)} sur {fmtHM(x.target_minutes)} ({x.strict ? "plafond strict" : "objectif souple"})</li>)}</ul>)}
              {k === "fairness" && s.blocks.fairness.employees.length > 0 && (
                <details><summary className="help">Heures par collaborateur (toutes les heures attribuées, cible commune, écart)</summary>
                  <div className="table-wrap"><table className="table" data-testid="fairness-table"><thead><tr><th>Collaborateur</th><th className="num">Heures</th>
                    <th className="num">dont sans budget</th><th className="num">Cible</th><th className="num">Écart</th><th>Cible</th></tr></thead>
                    <tbody>{s.blocks.fairness.employees.map((e) => (
                      <tr key={e.name}><td>{e.name}{e.reinforce_only ? " (renfort)" : ""}{e.flag ? <div className="help">{e.flag}</div> : null}
                        {e.partially_represented.length > 0 && <div className="help">Calcul de la cible : {e.partially_represented.join(", ")} pris en compte en partie seulement</div>}</td>
                        <td className="num">{fmtHM(e.minutes)}</td><td className="num">{e.unbudgeted_minutes ? fmtHM(e.unbudgeted_minutes) : "—"}</td>
                        <td className="num">{fmtHM(e.target_minutes)}</td><td className="num">{e.deviation_minutes > 0 ? "+" : e.deviation_minutes < 0 ? "−" : ""}{fmtHM(Math.abs(e.deviation_minutes))}</td>
                        <td>{e.target_status ?? "—"}</td></tr>))}</tbody></table></div>
                  {(s.blocks.fairness.flow_not_represented?.length ?? 0) > 0 && (
                    <p className="help" style={{ margin: "var(--sp-1) 0 0" }}>Calcul de la cible : {s.blocks.fairness.flow_represents?.join(", ")} sont représentés ;
                      {" "}{s.blocks.fairness.flow_not_represented?.join(", ")} ne le sont pas (le planning les respecte toujours). « Atteinte » : le planning atteint la cible
                      (à moins d'un demi-shift près) ; « optimum prouvé » : aucune répartition conforme ne réduit davantage les écarts ; « estimée » : mode à un seul niveau.</p>)}
                </details>)}
              {k === "optimisation" && s.blocks.optimisation.levels.length > 0 && (
                <p className="help" style={{ margin: 0 }}>{s.blocks.optimisation.levels.map((l) => `${l.label ?? l.level} : ${l.proved ? "prouvé" : "non prouvé"}${l.seconds !== null ? ` (${String(l.seconds).replace(".", ",")} s)` : ""}`).join(" · ")}</p>)}
              {b.action && <a className="btn btn-sm" href={b.action.href}>{b.action.label}</a>}
            </article>);
        })}
      </div>
      <details className="help" data-testid="engine-priorities"><summary>Comment le moteur arbitre (ordre des priorités)</summary>
        <ol style={{ margin: "var(--sp-1) 0 0", paddingLeft: "1.2rem" }}>{s.priorities.map((p) => <li key={p}>{p}</li>)}</ol>
      </details>
    </section>
  );
}
