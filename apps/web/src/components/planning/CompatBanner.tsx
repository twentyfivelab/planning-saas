"use client";
import { useState } from "react";
import { useApi } from "@/components/hooks";
import { Badge, Button, Callout } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { invalidate } from "@/lib/invalidate";
import { diffSchedules, type Assignment } from "@/lib/schedule";
import { errText } from "@/lib/wfm";
import { CapNoticeBox, IncompatModal, type CompatReport } from "./IncompatModal";
import { frozenLabel, type PeriodParams } from "./RunStatus";

type Change = { slot: string; from: string; to: string };

/** Incompatibilités du planning avec SES paramètres (conservés à sa création), détail consultable, paramètres conservés et application
 *  EXPLICITE des paramètres actuels. Réoptimisation encadrée : les affectations verrouillées ne sont jamais déplacées, rien n'est
 *  modifié sans confirmation, comparatif avant/après. */
export function CompatBanner({ periodId, periodName }: { periodId: string; periodName?: string }) {
  const comp = useApi<CompatReport>(`/periods/${periodId}/compatibility`);
  const params = useApi<PeriodParams>(`/periods/${periodId}/params`);
  const toast = useToast();
  const [ask, setAsk] = useState(false); const [busy, setBusy] = useState(false); const [changes, setChanges] = useState<Change[] | null>(null); const [fail, setFail] = useState("");
  const [detail, setDetail] = useState<"plan" | "current" | null>(null);
  const [cmp, setCmp] = useState(false); const [applyAsk, setApplyAsk] = useState(false);
  const c = comp.data; const pp = params.data;
  const hard = c?.items.filter((i) => i.kind === "obligatoire") ?? [];
  const soft = c?.items.filter((i) => i.kind !== "obligatoire") ?? [];
  const nDiff = pp?.differences.length ?? 0;

  async function reoptimize() {
    setBusy(true); setFail("");
    try {
      const before = (await api<{ assignments: Assignment[] }>(`/periods/${periodId}/schedule`)).assignments;
      const r = await api<{ run_id: string }>(`/periods/${periodId}/runs`, { method: "POST", json: { time_limit_s: 30, kind: "full", params: "frozen" }, headers: { "Idempotency-Key": crypto.randomUUID() } });
      let run: { status: string; result_status: string | null } = { status: "en_attente", result_status: null };
      for (let i = 0; i < 90 && !["termine", "annule", "erreur"].includes(run.status); i++) { await new Promise((x) => setTimeout(x, 1000)); run = await api(`/runs/${r.run_id}`); }
      if (run.status !== "termine") throw new Error("L'exécution n'a pas abouti : le planning n'a pas été modifié.");
      if (run.result_status === "infaisable") {
        const diag = await api<{ report: { diagnostics: { message: string }[] } }>(`/runs/${r.run_id}/diagnostic`);
        setFail(`Réoptimisation impossible : ${diag.report.diagnostics[0]?.message ?? "contraintes incompatibles"}. Rien n'a été modifié.`); setAsk(false); return;
      }
      const after = (await api<{ assignments: Assignment[] }>(`/periods/${periodId}/schedule`)).assignments;
      const d = diffSchedules(before, after);
      setChanges(d.changed); setAsk(false); invalidate(); comp.reload();
      toast.push(`Réoptimisation terminée : ${d.changed.length} affectation(s) modifiée(s), ${c?.locked ?? 0} verrouillée(s) conservée(s).`, "ok");
    } catch (e: unknown) { setFail(e instanceof Error ? e.message : "Erreur"); setAsk(false); }
    finally { setBusy(false); }
  }

  async function applyCurrent() {
    setBusy(true);
    try {
      const r = await api<CompatReport>(`/periods/${periodId}/params/apply-current`, { method: "POST", json: { confirm: true } });
      setApplyAsk(false); setCmp(false); comp.mutate(r); params.reload(); invalidate();
      toast.push(r.items.length ? `Paramètres actuels appliqués à ce planning : ${r.items.length} incompatibilité(s) à traiter.` : "Paramètres actuels appliqués à ce planning : aucune incompatibilité.", r.items.length ? "warn" : "ok");
    } catch (e) { toast.push(errText(e), "bad"); }
    finally { setBusy(false); }
  }

  return (
    <>
      {c && c.has_plan && !c.compatible && (
        <Callout kind="warn" title={`${periodName ? `${periodName} · ` : ""}${c.items.length} incompatibilité${c.items.length > 1 ? "s" : ""} avec les paramètres de ce planning`}>
          <div className="stack" style={{ gap: "var(--sp-2)" }} data-testid="compat-banner">
            <p className="row" style={{ margin: 0 }}>{hard.length > 0 && <Badge tone="bad" icon="alert">{hard.length} contrainte(s) obligatoire(s) non respectée(s)</Badge>} {soft.length > 0 && <Badge tone="warn">{soft.length} préférence(s) non respectée(s)</Badge>} <span className="muted">Rien n&apos;a été modifié automatiquement.</span></p>
            <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>{c.items.slice(0, 3).map((t, i) => <li key={i}><strong>{t.employee}</strong> · {t.rule} — {t.reason}</li>)}</ul>
            <div className="row"><Button icon="search" onClick={() => setDetail("plan")}>Voir le détail</Button><Button variant="primary" icon="sparkles" onClick={() => setAsk(true)}>Réoptimiser…</Button></div>
          </div>
        </Callout>
      )}
      {c?.has_plan && pp?.frozen && (
        <p className="help row" data-testid="frozen-params" style={{ margin: 0 }}>
          <Badge tone="neutral" icon="lock">Paramètres {frozenLabel(pp)}</Badge>
          {nDiff > 0 ? <>{nDiff} différence{nDiff > 1 ? "s" : ""} avec les paramètres actuels (fiches modifiées depuis) : elles ne s&apos;appliquent pas à ce planning. <button type="button" className="link-btn" onClick={() => setCmp(true)}>Comparer et appliquer…</button></> : "Identiques aux paramètres actuels."}
        </p>
      )}
      {c?.cap_notice && c.cap_notice.over.length > 0 && <CapNoticeBox notice={c.cap_notice} />}
      {c?.removed_notice && c.removed_notice.length > 0 && (
        <Callout kind="info" title="Collaborateurs supprimés après la création de ce planning">
          <p style={{ margin: 0 }} data-testid="removed-notice">{c.removed_notice.map((r) => `${r.employee} (supprimé·e le ${r.removed_on.split("-").reverse().join("/")} : ${r.assignments} affectation${r.assignments > 1 ? "s" : ""} à partir de cette date)`).join(" ; ")}.</p>
          <p style={{ margin: "var(--sp-1) 0 0" }}>Ces affectations restent dans ce planning (historique conservé) : ce n&apos;est pas une incompatibilité. Une nouvelle génération ne leur attribue plus aucun shift ; réattribuez-les à la main si nécessaire.</p>
        </Callout>
      )}
      {fail && <Callout kind="bad" title="Réoptimisation non appliquée">{fail}</Callout>}
      {changes && (
        <Callout kind="ok" title={`Dernière réoptimisation : ${changes.length} affectation(s) modifiée(s)`}>
          <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>{changes.slice(0, 6).map((x) => <li key={x.slot}>{x.slot} : {x.from} → <strong>{x.to}</strong></li>)}</ul>
          <div className="row" style={{ marginTop: "var(--sp-2)" }}><Button size="sm" onClick={() => setChanges(null)}>Masquer</Button></div>
        </Callout>
      )}
      {detail && <IncompatModal open onClose={() => setDetail(null)} periodId={periodId} periodName={periodName} params={detail} />}
      <Modal open={ask} onClose={() => !busy && setAsk(false)} title="Réoptimiser le planning ?" description="Les paramètres conservés par ce planning sont utilisés ; le plafond mensuel actuel est appliqué.">
        <div className="stack">
          <p><strong>{c?.locked ?? 0}</strong> affectation(s) verrouillée(s) ou ajoutée(s) à la main resteront exactement telles quelles.</p>
          <p><strong>{c?.unlocked ?? 0}</strong> affectation(s) non verrouillée(s) peuvent changer. Un comparatif avant/après sera affiché.</p>
          <p className="help">Si une affectation verrouillée est incompatible avec une règle, la réoptimisation est refusée avec l&apos;explication, sans rien modifier.</p>
          <div className="row modal-actions"><Button onClick={() => setAsk(false)} disabled={busy}>Annuler</Button><Button variant="primary" onClick={reoptimize} disabled={busy} aria-busy={busy}>{busy ? "Réoptimisation…" : "Confirmer la réoptimisation"}</Button></div>
        </div>
      </Modal>
      <Modal open={cmp} onClose={() => !busy && setCmp(false)} title="Paramètres de ce planning et paramètres actuels" description="Les modifications faites depuis (par exemple pour un autre mois) ne s'appliquent pas à ce planning, sauf si vous le décidez.">
        <div className="stack">
          {pp && pp.differences.length > 0 ? (
            <div className="table-wrap"><table className="table table-cards" data-testid="params-diff">
              <thead><tr><th>Collaborateur</th><th>Paramètre</th><th>Ce planning</th><th>Actuel</th></tr></thead>
              <tbody>{pp.differences.map((d, i) => <tr key={i}><td className="cell-main" data-label="Collaborateur">{d.employee ?? "Règles de l'entreprise"}</td><td data-label="Paramètre">{d.label}</td><td data-label="Ce planning">{d.planning}</td><td data-label="Actuel"><strong>{d.current}</strong></td></tr>)}</tbody>
            </table></div>
          ) : <p>Aucune différence.</p>}
          <div className="row modal-actions">
            <Button onClick={() => setCmp(false)} disabled={busy}>Fermer</Button>
            <Button icon="search" onClick={() => setDetail("current")}>Incompatibilités si appliqués</Button>
            <Button variant="primary" onClick={() => setApplyAsk(true)} disabled={busy || !nDiff}>Appliquer les paramètres actuels…</Button>
          </div>
        </div>
      </Modal>
      <Modal open={applyAsk} onClose={() => !busy && setApplyAsk(false)} title="Appliquer les paramètres actuels à ce planning ?" variant="confirm">
        <div className="stack">
          <p>Ce planning adoptera les paramètres actuels à la place de ceux qu&apos;il conserve. <strong>Aucune affectation ne sera modifiée</strong> : les incompatibilités qui en résultent seront listées, puis vous pourrez corriger à la main ou réoptimiser.</p>
          <p className="help">Les autres mois ne changent pas.</p>
          <div className="row modal-actions"><Button onClick={() => setApplyAsk(false)} disabled={busy}>Annuler</Button><Button variant="primary" onClick={applyCurrent} disabled={busy} aria-busy={busy}>Appliquer</Button></div>
        </div>
      </Modal>
    </>
  );
}
