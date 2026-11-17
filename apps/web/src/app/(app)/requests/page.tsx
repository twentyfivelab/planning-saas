"use client";
import { useState } from "react";
import { useMe } from "@/components/Shell";
import { useApi } from "@/components/hooks";
import { Badge, Button, Callout, Card, EmptyState, ErrorState, Field, Input, PageHead, SkeletonCard } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError } from "@/lib/api";
import { invalidate } from "@/lib/invalidate";
import { errText } from "@/lib/wfm";

type Req = { id: string; kind: "leave" | "absence" | "swap"; status: string; status_label: string; employee: string; colleague: string | null; summary: string;
  note: string | null; created_at: string; decided_at: string | null; decision_note: string | null; impact?: string[]; stale?: boolean };
type Issue = { code: string; level: string; message: string };
type Refused = { code: string; issues: Issue[]; can_override: boolean; refusal?: string | null; message: string };
const KIND = { leave: "Congé", absence: "Absence", swap: "Échange" } as const;
const STATUS_TONE: Record<string, "warn" | "ok" | "bad" | "neutral" | "info"> = { pending: "warn", awaiting_colleague: "info", approved: "ok", refused: "bad", declined: "bad", cancelled: "neutral" };

/** Demandes des collaborateurs : décision du responsable. Un congé ou une absence approuvés ne retirent aucun shift (les shifts concernés
 *  sont listés) ; un échange approuvé passe par le même contrôle qu'un échange fait à l'écran. */
export default function Requests() {
  const me = useMe();
  const [scope, setScope] = useState<"open" | "all">("open");
  const q = useApi<Req[]>(`/requests?status=${scope}`);
  const canSwap = me.permissions.includes("planning.edit");
  return (
    <>
      <PageHead eyebrow="Congés, absences et échanges" title="Demandes des collaborateurs">
        <div className="row" role="group" aria-label="Filtre">
          <Button size="sm" variant={scope === "open" ? "primary" : undefined} onClick={() => setScope("open")} aria-pressed={scope === "open"}>À traiter</Button>
          <Button size="sm" variant={scope === "all" ? "primary" : undefined} onClick={() => setScope("all")} aria-pressed={scope === "all"}>Historique</Button>
        </div>
      </PageHead>
      {q.error ? <ErrorState message={q.error} onRetry={q.reload} /> : q.loading && !q.data ? <SkeletonCard lines={4} /> : !q.data?.length ? (
        <Card><EmptyState icon="check" title={scope === "open" ? "Aucune demande à traiter" : "Aucune demande"}>Les demandes envoyées depuis « Mon planning » apparaissent ici.</EmptyState></Card>
      ) : (
        <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }} data-testid="requests">
          {q.data.map((r) => <RequestCard key={r.id} r={r} canDecide={r.kind !== "swap" || canSwap} onChanged={() => { q.reload(); invalidate(); }} />)}
        </ul>
      )}
    </>
  );
}

function RequestCard({ r, canDecide, onChanged }: { r: Req; canDecide: boolean; onChanged: () => void }) {
  const toast = useToast();
  const [note, setNote] = useState(""); const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<Refused | null>(null); const [err, setErr] = useState("");
  async function decide(approve: boolean, force = false) {
    setBusy(true); setErr("");
    try {
      await api(`/requests/${r.id}/decide`, { method: "POST", json: { approve, note: note || null, force } });
      toast.push(approve ? "Demande approuvée." : "Demande refusée.", approve ? "ok" : "info"); setRefused(null); onChanged();
    } catch (e) {
      const d = e instanceof ApiError ? (e.detail as Refused | undefined) : undefined;
      if (d && typeof d === "object" && Array.isArray(d.issues)) setRefused(d); else setErr(errText(e));
    } finally { setBusy(false); }
  }
  return (
    <li className="glass card" data-testid="request" aria-label={`${KIND[r.kind]} — ${r.employee}`}>
      <div className="spread">
        <div className="row"><Badge tone="accent">{KIND[r.kind]}</Badge><strong>{r.employee}</strong>{r.colleague && <span className="muted">avec {r.colleague}</span>}</div>
        <Badge tone={STATUS_TONE[r.status] ?? "neutral"}>{r.status_label}</Badge>
      </div>
      <p style={{ margin: "var(--sp-2) 0 0" }}>{r.summary}</p>
      {r.note && <p className="muted" style={{ margin: "var(--sp-1) 0 0" }}>« {r.note} »</p>}
      {r.impact && (r.impact.length ? (
        <Callout kind="warn" title={`${r.impact.length} shift(s) concerné(s) dans le planning`}>
          <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>{r.impact.map((x) => <li key={x}>{x}</li>)}</ul>
          <p className="help" style={{ margin: "var(--sp-1) 0 0" }}>L&apos;approbation ne retire aucun shift : remplacez-les ensuite (« Voir les remplaçants »). Si le planning est validé ou publié, une révision est proposée.</p>
        </Callout>) : <p className="help" style={{ margin: "var(--sp-1) 0 0" }}>Aucun shift concerné dans les plannings existants.</p>)}
      {r.stale && <Callout kind="bad" title="Échange devenu impossible">Le planning a changé depuis la demande : ces shifts ne sont plus tenus par ces collaborateurs. Refusez-la ; une nouvelle demande pourra être faite.</Callout>}
      {r.decision_note && <p className="help" style={{ margin: "var(--sp-1) 0 0" }}>Décision : {r.decision_note}</p>}
      {refused && (
        <Callout kind={refused.code === "needs_confirmation" ? "warn" : "bad"} title={refused.code === "needs_confirmation" ? "Alertes avant d'appliquer l'échange" : "Échange impossible"}>
          {refused.issues.length > 0 && <ul style={{ margin: 0, paddingLeft: "1.1rem" }} data-testid="decision-issues">{refused.issues.map((i, n) => <li key={n}>{i.message}</li>)}</ul>}
          {!refused.issues.length && <p style={{ margin: 0 }}>{refused.message}</p>}
          {refused.code === "needs_confirmation" && !refused.can_override && <p style={{ margin: "var(--sp-1) 0 0" }}>{refused.refusal ?? refused.message}</p>}
          <p className="help" style={{ margin: "var(--sp-1) 0 0" }}>Rien n&apos;a été modifié.</p>
        </Callout>)}
      {err && <Callout kind="bad" title="Décision non enregistrée">{err}</Callout>}
      {r.status === "pending" && canDecide && (
        <div className="row" style={{ alignItems: "flex-end", marginTop: "var(--sp-2)" }}>
          <Field label="Message au collaborateur (facultatif)">{(p) => <Input {...p} value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} style={{ minWidth: "16rem" }} />}</Field>
          <Button onClick={() => decide(false)} disabled={busy}>Refuser</Button>
          {refused?.code === "needs_confirmation" && refused.can_override
            ? <Button variant="primary" onClick={() => decide(true, true)} disabled={busy} aria-busy={busy}>Confirmer et approuver</Button>
            : <Button variant="primary" onClick={() => decide(true)} disabled={busy || !!r.stale || refused?.code === "blocked"} aria-busy={busy}>Approuver</Button>}
        </div>)}
      {r.status === "pending" && !canDecide && <p className="help">Votre rôle ne permet pas d&apos;approuver un échange.</p>}
    </li>
  );
}
