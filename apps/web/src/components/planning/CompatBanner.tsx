"use client";
import { useState } from "react";
import { useApi } from "@/components/hooks";
import { Badge, Button, Callout } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { invalidate } from "@/lib/invalidate";
import { diffSchedules, type Assignment } from "@/lib/schedule";

type Compat = { hard: string[]; soft: { text: string; employee: string }[]; checked: number; flagged_assignment_ids: string[]; locked: number; unlocked: number; has_plan: boolean; compatible: boolean };
type Change = { slot: string; from: string; to: string };

/** Signale les incompatibilités entre le planning existant et les paramètres actuels, et propose une réoptimisation encadrée
 *  (les affectations verrouillées ne sont jamais déplacées ; rien n'est modifié sans confirmation ; comparatif avant/après). */
export function CompatBanner({ periodId }: { periodId: string }) {
  const comp = useApi<Compat>(`/periods/${periodId}/compatibility`);
  const toast = useToast();
  const [ask, setAsk] = useState(false); const [busy, setBusy] = useState(false); const [changes, setChanges] = useState<Change[] | null>(null); const [fail, setFail] = useState("");
  const c = comp.data;

  async function reoptimize() {
    setBusy(true); setFail("");
    try {
      const before = (await api<{ assignments: Assignment[] }>(`/periods/${periodId}/schedule`)).assignments;
      const r = await api<{ run_id: string }>(`/periods/${periodId}/runs`, { method: "POST", json: { time_limit_s: 30, kind: "full" }, headers: { "Idempotency-Key": crypto.randomUUID() } });
      let run: { status: string; result_status: string | null } = { status: "en_attente", result_status: null };
      for (let i = 0; i < 90 && !["termine", "annule", "erreur"].includes(run.status); i++) { await new Promise((x) => setTimeout(x, 1000)); run = await api(`/runs/${r.run_id}`); }
      if (run.status !== "termine") throw new Error("L'exécution n'a pas abouti.");
      if (run.result_status === "infaisable") {
        const diag = await api<{ report: { diagnostics: { message: string }[] } }>(`/runs/${r.run_id}/diagnostic`);
        setFail(`Réoptimisation impossible : ${diag.report.diagnostics[0]?.message ?? "contraintes incompatibles"}. Rien n'a été modifié.`); setAsk(false); return;
      }
      const after = (await api<{ assignments: Assignment[] }>(`/periods/${periodId}/schedule`)).assignments;
      const d = diffSchedules(before, after);
      setChanges(d.changed); setAsk(false); invalidate();
      toast.push(`Réoptimisation terminée : ${d.changed.length} affectation(s) modifiée(s), ${c?.locked ?? 0} verrouillée(s) conservée(s).`, "ok");
    } catch (e: unknown) { setFail(e instanceof Error ? e.message : "Erreur"); setAsk(false); }
    finally { setBusy(false); }
  }

  return (
    <>
      {c && c.has_plan && !c.compatible && (
        <Callout kind="warn" title={`${c.hard.length + c.soft.length} incompatibilité(s) avec les paramètres actuels`}>
          <div className="stack" style={{ gap: "var(--sp-2)" }}>
            <p>{c.hard.length > 0 && <Badge tone="bad" icon="alert">{c.hard.length} règle(s) obligatoire(s) non respectée(s)</Badge>} {c.soft.length > 0 && <Badge tone="warn">{c.soft.length} préférence(s) non respectée(s)</Badge>} <span className="muted">Le planning n&apos;a pas été modifié : rien ne change sans votre confirmation.</span></p>
            <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>{[...c.hard, ...c.soft.map((s) => s.text)].slice(0, 4).map((t) => <li key={t}>{t}</li>)}</ul>
            <div className="row"><Button variant="primary" icon="sparkles" onClick={() => setAsk(true)}>Réoptimiser…</Button></div>
          </div>
        </Callout>
      )}
      {fail && <Callout kind="bad" title="Réoptimisation non appliquée">{fail}</Callout>}
      {changes && (
        <Callout kind="ok" title={`Dernière réoptimisation : ${changes.length} affectation(s) modifiée(s)`}>
          <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>{changes.slice(0, 6).map((x) => <li key={x.slot}>{x.slot} : {x.from} → <strong>{x.to}</strong></li>)}</ul>
          <div className="row" style={{ marginTop: "var(--sp-2)" }}><Button size="sm" onClick={() => setChanges(null)}>Masquer</Button></div>
        </Callout>
      )}
      <Modal open={ask} onClose={() => !busy && setAsk(false)} title="Réoptimiser le planning ?" description="Les paramètres actuels des collaborateurs seront appliqués.">
        <div className="stack">
          <p><strong>{c?.locked ?? 0}</strong> affectation(s) verrouillée(s) ou ajoutée(s) à la main resteront exactement telles quelles.</p>
          <p><strong>{c?.unlocked ?? 0}</strong> affectation(s) non verrouillée(s) peuvent changer. Un comparatif avant/après sera affiché.</p>
          <p className="help">Si une affectation verrouillée est incompatible avec une règle, la réoptimisation est refusée avec l&apos;explication, sans rien modifier.</p>
          <div className="row modal-actions"><Button onClick={() => setAsk(false)} disabled={busy}>Annuler</Button><Button variant="primary" onClick={reoptimize} disabled={busy} aria-busy={busy}>{busy ? "Réoptimisation…" : "Confirmer la réoptimisation"}</Button></div>
        </div>
      </Modal>
    </>
  );
}
