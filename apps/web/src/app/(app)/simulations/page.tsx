"use client";
import { useEffect, useMemo, useState } from "react";
import { useMe } from "@/components/Shell";
import { useApi, usePeriod } from "@/components/hooks";
import { MonthSwitcher } from "@/components/MonthSwitcher";
import { SimulationPreview, type SimMetrics, type SimRow } from "@/components/planning/SimulationPreview";
import { Badge, Button, Callout, Card, EmptyState, ErrorState, Field, Input, PageHead, SkeletonCard } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { monthLabel } from "@/lib/months";
import { SOFT_LABEL, errText, fmtCHF, fmtH, resultLabel } from "@/lib/wfm";

type Strategy = { key: string; label: string; description: string; keep_current: boolean };
const RUNNING = ["en_attente", "en_cours"];
const when = (d: string) => new Date(d).toLocaleString("fr-CH", { timeZone: "Europe/Zurich", dateStyle: "short", timeStyle: "short" });

function MetricCells({ m, cost }: { m: SimMetrics | null; cost: boolean }) {
  if (!m) return <td colSpan={cost ? 7 : 6} className="faint">Aucun résultat</td>;
  const soft = Object.entries(m.soft_detail ?? {}).map(([k, v]) => `${SOFT_LABEL[k] ?? k} : ${v}`).join("\n");
  return (
    <>
      <td className="num" data-label="Couverture"><strong>{m.coverage_rate ?? "–"} %</strong></td>
      <td className="num" data-label="Non couverts">{m.uncovered_shifts}</td>
      <td className="num nowrap" data-label="Heures planifiées">{fmtH(m.total_minutes)}</td>
      <td className="num nowrap" data-label="Écart aux objectifs">{fmtH(m.gap_to_targets_minutes)}</td>
      <td className="num" data-label="Préférences non satisfaites" title={soft}>{m.soft_unsatisfied}</td>
      <td className="num nowrap" data-label="Dimanches">{m.sundays_min}–{m.sundays_max}</td>
      {cost && <td className="num nowrap" data-label="Coût estimé">{fmtCHF(m.cost_cents) ?? <span className="faint">Non renseigné</span>}{m.cost_cents !== null && (m.cost_known_share ?? 0) < 100 && <span className="faint"> ({m.cost_known_share} % des heures)</span>}</td>}
    </>
  );
}

/** Comparer plusieurs stratégies avant de choisir : mêmes règles strictes, résultats mesurables, jamais d'écrasement du planning en cours. */
export default function Simulations() {
  const me = useMe(); const toast = useToast();
  const { period, month, setMonth, ensure } = usePeriod();
  const canRun = me.permissions.includes("planning.optimize");
  const strategies = useApi<Strategy[]>("/simulation-strategies");
  const sims = useApi<SimRow[]>(period ? `/periods/${period.id}/simulations` : null);
  const current = useApi<SimMetrics>(period ? `/periods/${period.id}/metrics` : null);
  const [chosen, setChosen] = useState<string[]>(["couverture", "equite", "preferences", "stabilite"]);
  const [limit, setLimit] = useState(15); const [busy, setBusy] = useState(false); const [err, setErr] = useState("");
  const [detail, setDetail] = useState<SimRow | null>(null);
  const running = !!sims.data?.some((s) => RUNNING.includes(s.status));
  const reload = sims.reload;
  useEffect(() => { if (!running) return; const t = setInterval(reload, 2000); return () => clearInterval(t); }, [running, reload]);
  async function launch() {
    setBusy(true); setErr("");
    try {
      const p = period ?? await ensure();
      await api(`/periods/${p.id}/simulations`, { method: "POST", json: { strategies: chosen, time_limit_s: limit } });
      toast.push(`${chosen.length} simulation(s) lancée(s). Le planning en cours ne change pas.`, "info"); sims.reload();
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  const showCost = me.permissions.includes("finance.read");
  const rows = useMemo(() => sims.data ?? [], [sims.data]);
  return (
    <>
      <PageHead eyebrow={monthLabel(month)} title="Simulations"><MonthSwitcher month={month} onChange={setMonth} /></PageHead>
      <Card title="Comparer des stratégies" eyebrow="Les contraintes strictes et la couverture restent prioritaires dans tous les cas">
        <div className="stack">
          <fieldset className="plain-fieldset"><legend className="label">Stratégies à comparer</legend>
            <ul className="strategy-list">{strategies.data?.map((s) => (
              <li key={s.key}><label className="strategy"><input type="checkbox" checked={chosen.includes(s.key)} disabled={!canRun} onChange={(e) => setChosen(e.target.checked ? [...chosen, s.key] : chosen.filter((x) => x !== s.key))} /><span><strong>{s.label}</strong><span className="help">{s.description}</span></span></label></li>))}</ul>
          </fieldset>
          <div className="row" style={{ alignItems: "flex-end" }}>
            <Field label="Durée maximale par simulation (secondes)">{(p) => <Input {...p} type="number" min={3} max={300} value={limit} disabled={!canRun} onChange={(e) => setLimit(Math.max(3, Math.min(300, Number(e.target.value) || 15)))} style={{ width: "8rem" }} />}</Field>
            <Button variant="primary" icon="sparkles" disabled={!canRun || !chosen.length || busy || running} aria-busy={busy} onClick={launch}>{running ? "Calcul en cours…" : "Lancer la comparaison"}</Button>
          </div>
          {err && <Callout kind="bad" title="Lancement impossible">{err}</Callout>}
        </div>
      </Card>
      <Card title="Résultats" actions={running ? <Badge tone="info" role="status">Calcul en cours</Badge> : undefined}>
        {sims.error ? <ErrorState message={sims.error} onRetry={sims.reload} /> : sims.loading && !sims.data && period ? <SkeletonCard lines={4} /> : (!period || (!rows.length && !current.data)) ? (
          <EmptyState icon="sparkles" title="Aucune simulation">Choisissez des stratégies et lancez la comparaison.</EmptyState>
        ) : (
          <div className="table-wrap"><table className="table table-cards" aria-label="Comparaison des simulations">
            <thead><tr><th>Stratégie</th><th>Couverture</th><th>Non couverts</th><th>Heures</th><th>Écart aux objectifs</th><th>Préférences non satisfaites</th><th>Dimanches (min–max)</th>{showCost && <th>Coût estimé</th>}<th>Modifications</th><th>Résolution</th><th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>
              {current.data && (current.data.mandatory_shifts > 0 || current.data.total_minutes > 0) && <tr data-current="true"><td className="cell-main"><strong>Planning actuel</strong></td><MetricCells m={current.data} cost={showCost} /><td className="num" data-label="Modifications">—</td><td data-label="Résolution"><Badge>En place</Badge></td><td /></tr>}
              {rows.map((s) => (
                <tr key={s.run_id}>
                  <td className="cell-main"><strong>{s.label ?? s.strategy}</strong><span className="faint nowrap"> · {when(s.created_at)}</span></td>
                  {RUNNING.includes(s.status) ? <td colSpan={showCost ? 8 : 7}><Badge tone="info">{s.status === "en_cours" ? "Calcul en cours" : "En attente"}</Badge></td> : (
                    <>
                      <MetricCells m={s.metrics} cost={showCost} />
                      <td className="num" data-label="Modifications">{s.metrics?.changes?.total ?? "—"}</td>
                    </>
                  )}
                  {!RUNNING.includes(s.status) && <td data-label="Résolution"><Badge tone={s.proved_optimal ? "ok" : s.status === "termine" ? "info" : "bad"}>{s.status === "termine" ? resultLabel(s.result_status, s.proved_optimal) : s.status === "annule" ? "Annulée" : "Échec"}</Badge>{s.applied_at && <Badge tone="ok" icon="check">Appliquée</Badge>}{s.stale && !s.applied_at && <Badge tone="warn">Obsolète</Badge>}</td>}
                  <td><div className="row" style={{ flexWrap: "nowrap" }}><Button size="sm" disabled={RUNNING.includes(s.status)} onClick={() => setDetail(s)} aria-label={`Voir le détail : ${s.label ?? s.strategy}`}>Voir</Button>
                    {canRun && !s.applied_at && !RUNNING.includes(s.status) && <Button size="sm" variant="ghost" iconOnly icon="x" label={`Retirer de la comparaison : ${s.label ?? s.strategy}`} onClick={async () => { try { await api(`/simulations/${s.run_id}`, { method: "DELETE" }); sims.reload(); } catch (e) { toast.push(errText(e), "bad"); } }} />}</div></td>
                </tr>))}
            </tbody>
          </table></div>
        )}
        <p className="help" style={{ marginTop: "var(--sp-3)" }}><Icon name="info" size={12} style={{ verticalAlign: "-2px" }} /> Indicateurs recalculés sur les affectations proposées. « Optimum prouvé » n&apos;apparaît que si le solveur l&apos;a démontré dans le temps imparti.</p>
      </Card>
      <Modal open={!!detail} onClose={() => setDetail(null)} title={detail?.label ?? "Simulation"} description="Ce qui changerait, shift par shift.">
        {detail && <SimulationPreview runId={detail.run_id} canApply={canRun} onApplied={() => { setDetail(null); sims.reload(); current.reload(); }} />}
      </Modal>
    </>
  );
}
