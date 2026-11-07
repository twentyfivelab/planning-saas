"use client";
import { useEffect, useState } from "react";
import { Badge, Button, Callout } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { invalidate } from "@/lib/invalidate";
import { errCode, errText, fmtH, resultLabel } from "@/lib/wfm";

export type SimMetrics = {
  coverage_rate: number | null; uncovered_shifts: number; mandatory_shifts: number; total_minutes: number; gap_to_targets_minutes: number; soft_unsatisfied: number; soft_detail: Record<string, number>;
  sundays_min: number; sundays_max: number; sundays_total: number; cost_cents: number | null; cost_known_share: number | null; changes?: { added: number; removed: number; changed: number; total: number; unchanged: number };
};
export type SimRow = { run_id: string; kind: string; strategy: string | null; label: string | null; status: string; result_status: string | null; proved_optimal: boolean; duration_s: number | null; created_at: string; applied_at: string | null; stale: boolean; hard_violations: number; error?: string | null; metrics: SimMetrics | null };
type Detail = SimRow & { changes: { slot_id: string; day: string; site: string | null; start: string | null; end: string | null; from: string | null; to: string | null }[]; diagnostics?: { code: string; severity: string; message: string }[] };

const DONE = ["termine", "annule", "erreur"];

/** Résultat d'une simulation : ce qui changerait, shift par shift. Rien n'est modifié tant que le manager n'applique pas. */
export function SimulationPreview({ runId, canApply, onApplied }: { runId: string; canApply: boolean; onApplied: () => void }) {
  const toast = useToast();
  const [d, setD] = useState<Detail | null>(null);
  const [busy, setBusy] = useState(false); const [err, setErr] = useState(""); const [needConfirm, setNeedConfirm] = useState("");
  useEffect(() => {
    let stop = false, t: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try { const r = await api<Detail>(`/simulations/${runId}`); if (stop) return; setD(r); if (!DONE.includes(r.status)) t = setTimeout(tick, 1000); }
      catch (e) { if (!stop) setErr(errText(e)); }
    };
    setD(null); setErr(""); setNeedConfirm(""); void tick();
    return () => { stop = true; clearTimeout(t); };
  }, [runId]);
  async function apply(confirm: boolean) {
    setBusy(true); setErr("");
    try {
      const r = await api<{ version: number; safety_version: number; conflicts: string[] }>(`/simulations/${runId}/apply`, { method: "POST", json: { confirm_replace: confirm } });
      toast.push(`Simulation appliquée : version ${r.version} créée (copie de sécurité : version ${r.safety_version}).`, r.conflicts.length ? "warn" : "ok");
      invalidate(); onApplied();
    } catch (e) {
      if (errCode(e) === "official_version") setNeedConfirm(errText(e)); else setErr(errText(e));
    } finally { setBusy(false); }
  }
  if (err && !d) return <Callout kind="bad" title="Simulation indisponible">{err}</Callout>;
  if (!d || !DONE.includes(d.status)) return <p className="muted" role="status" aria-live="polite">Calcul de la proposition en cours… Le planning n&apos;est pas modifié.</p>;
  if (d.status !== "termine" || !d.metrics) return <Callout kind="bad" title="Pas de résultat applicable">{d.error ?? "Le calcul n'a pas abouti."} Le planning n&apos;a pas été modifié.</Callout>;
  const m = d.metrics;
  const blocking = (d.diagnostics ?? []).filter((x) => x.severity === "blocking");
  return (
    <div className="stack" aria-live="polite">
      <div className="row">
        <Badge tone={d.proved_optimal ? "ok" : "info"}>{resultLabel(d.result_status, d.proved_optimal)}</Badge>
        <Badge>Couverture : {m.coverage_rate ?? "–"} %</Badge>
        <Badge tone={m.uncovered_shifts ? "warn" : "ok"}>{m.uncovered_shifts} non couvert{m.uncovered_shifts > 1 ? "s" : ""}</Badge>
        {m.changes && <Badge tone="accent">{m.changes.total} modification{m.changes.total > 1 ? "s" : ""}</Badge>}
      </div>
      {d.result_status === "infaisable" && <Callout kind="bad" title="Impossible dans ce périmètre">{blocking[0]?.message ?? "Élargissez le périmètre ou passez à une réoptimisation complète."}</Callout>}
      {d.changes.length > 0 && (
        <div className="table-wrap"><table className="table table-cards">
          <caption className="sr-only">Modifications proposées</caption>
          <thead><tr><th>Date</th><th>Site</th><th>Horaire</th><th>Avant</th><th>Après</th></tr></thead>
          <tbody>{d.changes.slice(0, 60).map((c) => <tr key={c.slot_id}><td className="num cell-main">{c.day}</td><td data-label="Site">{c.site ?? "—"}</td><td className="num" data-label="Horaire">{c.start ? `${c.start}–${c.end}` : "—"}</td><td data-label="Avant">{c.from ?? <span className="faint">non couvert</span>}</td><td data-label="Après"><strong>{c.to ?? <span className="faint">non couvert</span>}</strong></td></tr>)}</tbody>
        </table></div>)}
      {d.changes.length === 0 && <p className="muted">Aucune affectation ne changerait.</p>}
      {d.changes.length > 60 && <p className="help">+ {d.changes.length - 60} autres modifications.</p>}
      <p className="help">Heures planifiées : {fmtH(m.total_minutes)} · Écart aux objectifs : {fmtH(m.gap_to_targets_minutes)} · Préférences non satisfaites : {m.soft_unsatisfied}.</p>
      {d.stale && <Callout kind="warn" title="Planning modifié depuis ce calcul">Relancez la simulation : l&apos;appliquer écraserait ces modifications.</Callout>}
      {d.applied_at && <Callout kind="ok">Cette simulation a été appliquée.</Callout>}
      {needConfirm && <Callout kind="warn" title="Version validée ou publiée">{needConfirm}<div className="row" style={{ marginTop: "var(--sp-2)" }}><Button variant="primary" disabled={busy} onClick={() => apply(true)}>Confirmer et appliquer</Button><Button onClick={() => setNeedConfirm("")}>Annuler</Button></div></Callout>}
      {err && <Callout kind="bad" title="Application refusée">{err}</Callout>}
      {canApply && !d.applied_at && !d.stale && !needConfirm && d.result_status !== "infaisable" && d.changes.length > 0 && <div className="row"><Button variant="primary" icon="check" disabled={busy} aria-busy={busy} onClick={() => apply(false)}>{busy ? "Application…" : "Appliquer cette proposition"}</Button><span className="help">Le planning actuel est d&apos;abord copié dans les versions.</span></div>}
    </div>
  );
}
