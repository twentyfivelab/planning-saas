"use client";
import { useState } from "react";
import { Badge, Button, Callout, Field, Input, Select } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { useApi } from "@/components/hooks";
import { api, ApiError } from "@/lib/api";
import { invalidate } from "@/lib/invalidate";
import { errText } from "@/lib/wfm";

export type Offer = { id: string; request_id: string; employee: { id: string; name: string } | null; rank: number; status: string; status_label: string; deadline: string;
  deadline_label: string; responded_at: string | null; reason: string | null; shift: string; created_at: string | null;
  details?: { day: string; start: string; end: string; site: string; brands: string[]; period: string | null; exists: boolean } };
export type ReplacementRequest = { id: string; shift_id: string | null; period_id: string; status: string; status_label: string; shift: string; holder: string | null;
  response_minutes: number; candidates: number; closed_reason: string | null; created_at: string | null; offers: Offer[]; pending: Offer | null };

const TONE: Record<string, "ok" | "bad" | "warn" | "info" | "neutral"> = { pending: "info", accepted: "ok", refused: "neutral", expired: "warn", cancelled: "neutral", invalidated: "warn",
  open: "info", filled: "ok", exhausted: "warn" };
export const DELAYS = [[60, "1 heure"], [240, "4 heures"], [720, "12 heures"], [1440, "24 heures"], [2880, "48 heures"]] as const;
const detailMsg = (e: unknown) => (e instanceof ApiError ? ((e.detail as { message?: string } | undefined)?.message ?? errText(e)) : errText(e));

/** Échéance affichée avant l'envoi : maintenant + délai, jamais après le début du shift (le serveur applique la même règle). */
export function deadlinePreview(day: string, start: string, minutes: number): { at: Date; capped: boolean } {
  const begin = new Date(`${day}T${start.slice(0, 5)}:00`);
  const at = new Date(Date.now() + minutes * 60_000);
  return at > begin ? { at: begin, capped: true } : { at, capped: false };
}
export const fmtWhen = (d: Date) => new Intl.DateTimeFormat("fr-CH", { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" }).format(d);

/** Suivi d'une proposition pour un shift (manager) : candidat sollicité, échéance, réponses, annulation. */
export function ProposalStatus({ req, canEdit, onChanged }: { req: ReplacementRequest; canEdit: boolean; onChanged: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false); const [confirm, setConfirm] = useState(false);
  async function cancel() {
    setBusy(true);
    try { await api(`/replacement-requests/${req.id}/cancel`, { method: "POST" }); toast.push("Proposition annulée. Le titulaire actuel reste affecté.", "ok"); invalidate(); onChanged(); }
    catch (e) { toast.push(detailMsg(e), "bad"); } finally { setBusy(false); setConfirm(false); }
  }
  const open = req.status === "open";
  return (
    <div className="stack" data-testid="proposal-status" data-status={req.status}>
      <Callout kind={open ? "info" : req.status === "filled" ? "ok" : "warn"} title={open && req.pending ? `Proposé à ${req.pending.employee?.name ?? "—"} — réponse avant le ${req.pending.deadline_label}` : req.status_label}>
        <span>{open ? <>Le titulaire actuel{req.holder ? <> (<strong>{req.holder}</strong>)</> : null} reste affecté tant que le remplacement n&apos;est pas accepté et validé. En cas de refus ou sans réponse, le candidat suivant du classement est sollicité.</>
          : req.closed_reason}</span>
        {req.offers.length > 0 && (
          <ol className="help" style={{ margin: "var(--sp-1) 0 0", paddingLeft: "1.1rem" }}>
            {req.offers.map((o) => <li key={o.id}>{o.employee?.name ?? "—"} : <Badge tone={TONE[o.status] ?? "neutral"}>{o.status_label}</Badge>{o.status === "pending" ? ` — avant le ${o.deadline_label}` : ""}{o.reason ? ` — ${o.reason}` : ""}</li>)}
          </ol>)}
        {open && canEdit && <div className="row" style={{ marginTop: "var(--sp-2)" }}><Button size="sm" onClick={() => setConfirm(true)} disabled={busy}>Annuler la proposition</Button></div>}
      </Callout>
      <Modal open={confirm} onClose={() => !busy && setConfirm(false)} variant="confirm" title="Annuler la proposition de remplacement ?" description={req.shift}>
        <div className="stack"><p>{req.pending ? `${req.pending.employee?.name} ne pourra plus l'accepter et en sera informé·e. ` : ""}Le titulaire actuel reste affecté ; rien d&apos;autre ne change.</p>
          <div className="row modal-actions"><Button onClick={() => setConfirm(false)} disabled={busy}>Garder la proposition</Button><Button variant="primary" onClick={() => void cancel()} disabled={busy} aria-busy={busy}>Annuler la proposition</Button></div></div>
      </Modal>
    </div>
  );
}

/** Propositions du mois (planning) : en cours en premier, puis les dernières closes. Mises à jour à chaque modification. */
export function PeriodProposals({ periodId, canEdit }: { periodId: string; canEdit: boolean }) {
  const q = useApi<{ items: ReplacementRequest[] }>(`/periods/${periodId}/replacement-requests`);
  const items = q.data?.items ?? [];
  const open = items.filter((r) => r.status === "open");
  if (!open.length) return null;
  return (
    <Callout kind="info" title={`${open.length} proposition${open.length > 1 ? "s" : ""} de remplacement en attente de réponse`}>
      <ul className="cover-list" data-testid="period-proposals">
        {open.map((r) => <li key={r.id} className="cover-row"><ProposalStatus req={r} canEdit={canEdit} onChanged={q.reload} /></li>)}
      </ul>
    </Callout>
  );
}

/** « Mon espace » : propositions reçues, réponse Accepter / Refuser (une seule soumission ; l'affectation n'est faite qu'après vérification). */
export function MyOffers() {
  const toast = useToast();
  const q = useApi<{ items: Offer[] }>("/me/replacement-offers");
  const [busy, setBusy] = useState<string | null>(null);
  const [refusing, setRefusing] = useState<Offer | null>(null); const [reason, setReason] = useState("");
  const [result, setResult] = useState<Record<string, { ok: boolean; text: string }>>({});
  const items = q.data?.items ?? [];
  if (!items.length) return null;
  async function answer(o: Offer, kind: "accept" | "refuse") {
    if (busy) return;
    setBusy(o.id);
    try {
      const r = await api<{ message: string }>(`/replacement-offers/${o.id}/${kind}`, { method: "POST", json: kind === "refuse" ? { reason: reason.trim() || null } : undefined });
      setResult((x) => ({ ...x, [o.id]: { ok: true, text: r.message } })); toast.push(r.message, "ok");
    } catch (e) {
      const text = detailMsg(e);
      setResult((x) => ({ ...x, [o.id]: { ok: false, text } })); toast.push(text, "bad");
    } finally { setBusy(null); setRefusing(null); setReason(""); q.reload(); invalidate(); }
  }
  const long = (d?: Offer["details"]) => d ? new Intl.DateTimeFormat("fr-CH", { weekday: "long", day: "numeric", month: "long", year: "numeric" }).format(new Date(`${d.day}T12:00:00`)) : "";
  return (
    <div className="glass card stack" id="propositions" data-testid="my-offers">
      <h2 className="h2" style={{ margin: 0 }}>Propositions de remplacement</h2>
      <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0, gap: "var(--sp-2)" }}>
        {items.map((o) => (
          <li key={o.id} className="surface" style={{ padding: "var(--sp-3)" }} data-testid="my-offer" data-status={o.status}>
            <div className="spread"><div>
              <strong>{o.details ? `${long(o.details)}, ${o.details.start}–${o.details.end}` : o.shift}</strong> <Badge tone={TONE[o.status] ?? "neutral"}>{o.status_label}</Badge>
              {o.details && <p className="muted" style={{ margin: 0 }}>{o.details.site}{o.details.brands.length ? ` · ${o.details.brands.join(" / ")}` : ""}{o.details.period ? ` · ${o.details.period}` : ""}</p>}
              {o.status === "pending" && <p className="help" style={{ margin: 0 }}>Réponse attendue avant le <strong>{o.deadline_label}</strong>. Le shift n&apos;est attribué qu&apos;après vérification de toutes les règles.</p>}
              {o.status !== "pending" && o.reason && <p className="help" style={{ margin: 0 }}>{o.reason}</p>}
              {result[o.id] && <p className={result[o.id].ok ? "help" : "error-text"} style={{ margin: 0 }} data-testid="offer-result">{result[o.id].text}</p>}
            </div>
            {o.status === "pending" && <div className="row">
              <Button variant="primary" onClick={() => void answer(o, "accept")} disabled={!!busy} aria-busy={busy === o.id}>{busy === o.id ? "Vérification…" : "Accepter"}</Button>
              <Button onClick={() => { setRefusing(o); setReason(""); }} disabled={!!busy}>Refuser</Button>
            </div>}</div>
          </li>))}
      </ul>
      <Modal open={!!refusing} onClose={() => !busy && setRefusing(null)} variant="confirm" title="Refuser cette proposition ?" description={refusing?.shift}>
        <div className="stack">
          <Field label="Motif (facultatif)" help="Transmis à votre responsable avec votre réponse.">{(p) => <Input {...p} maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
          <div className="row modal-actions"><Button onClick={() => setRefusing(null)} disabled={!!busy}>Retour</Button><Button variant="primary" onClick={() => refusing && void answer(refusing, "refuse")} disabled={!!busy}>Refuser</Button></div>
        </div>
      </Modal>
    </div>
  );
}

export function ProposeControl({ shift, candidate, disabled, onSent }: { shift: { shift_id: string; day: string; start: string }; candidate: { employee_uuid: string | null; name: string; has_account?: boolean };
  disabled: boolean; onSent: () => void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false); const [minutes, setMinutes] = useState(240); const [busy, setBusy] = useState(false); const [err, setErr] = useState("");
  if (!candidate.has_account) return <Badge tone="neutral">Sans compte : proposition impossible</Badge>;
  const pv = deadlinePreview(shift.day, shift.start, minutes);
  async function send() {
    if (busy || !candidate.employee_uuid) return;
    setBusy(true); setErr("");
    try {
      await api(`/shifts/${shift.shift_id}/replacement-requests`, { method: "POST", json: { start_employee_id: candidate.employee_uuid, response_minutes: minutes } });
      toast.push(`Proposition envoyée à ${candidate.name}. Le titulaire actuel reste affecté en attendant sa réponse.`, "ok"); setOpen(false); invalidate(); onSent();
    } catch (e) { setErr(detailMsg(e)); } finally { setBusy(false); }
  }
  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)} disabled={disabled} aria-label={`Proposer à ${candidate.name}`}>Proposer</Button>
      <Modal open={open} onClose={() => !busy && setOpen(false)} title={`Proposer ce shift à ${candidate.name} ?`} description="Le titulaire actuel reste affecté tant que le remplacement n'est pas accepté et validé.">
        <div className="stack" data-testid="propose-form">
          <Field label="Délai de réponse" help="En cas de refus ou sans réponse, le candidat suivant du classement est sollicité, avec le même délai.">{(p) => (
            <Select {...p} value={minutes} onChange={(e) => setMinutes(Number(e.target.value))}>{DELAYS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>)}</Field>
          <p className="help" style={{ margin: 0 }} data-testid="propose-deadline">Réponse attendue avant le <strong>{fmtWhen(pv.at)}</strong>{pv.capped ? " (début du shift : l'échéance ne le dépasse jamais)" : ""}.</p>
          {err && <Callout kind="bad" title="Proposition non envoyée">{err}</Callout>}
          <div className="row modal-actions"><Button onClick={() => setOpen(false)} disabled={busy}>Annuler</Button><Button variant="primary" onClick={() => void send()} disabled={busy} aria-busy={busy}>Envoyer la proposition</Button></div>
        </div>
      </Modal>
    </>
  );
}
