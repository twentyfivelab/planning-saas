"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge, Button, Callout, Field, Input, Select } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError } from "@/lib/api";
import { invalidate } from "@/lib/invalidate";
import { dayLabel, timeShort, type Assignment } from "@/lib/schedule";
import { errText } from "@/lib/wfm";

type Issue = { code: string; level: string; message: string };
type Refused = { code: string; issues: Issue[]; can_override: boolean; refusal?: string | null; message: string };
const label = (a: Assignment) => `${dayLabel(a.day)} · ${a.site_name ?? a.site} · ${timeShort(a.start)}–${timeShort(a.end)}`;

/** Envoi d'une opération composée avec le MÊME parcours de confirmation qu'une affectation manuelle : alertes listées, rien n'est
 *  enregistré sans confirmation, dérogation réservée aux rôles autorisés, règles non dérogeables jamais contournées. */
export function useConfirmed() {
  const [refused, setRefused] = useState<Refused | null>(null);
  const [busy, setBusy] = useState(false); const [err, setErr] = useState("");
  async function send<T>(url: string, body: Record<string, unknown>, force: boolean): Promise<T | null> {
    setBusy(true); setErr("");
    try { const r = await api<T>(url, { method: "POST", json: { ...body, force } }); setRefused(null); return r; }
    catch (e) {
      const d = e instanceof ApiError ? (e.detail as Refused | undefined) : undefined;
      if (d && typeof d === "object" && Array.isArray(d.issues)) setRefused(d); else setErr(errText(e));
      return null;
    } finally { setBusy(false); }
  }
  const reset = useCallback(() => { setRefused(null); setErr(""); }, []);
  return { refused, busy, err, send, reset };
}

export function Refusal({ r, reason, setReason }: { r: Refused; reason: string; setReason: (v: string) => void }) {
  const blocked = r.code === "blocked";
  return (
    <Callout kind={blocked ? "bad" : "warn"} title={blocked ? "Opération impossible" : `${r.issues.length} alerte${r.issues.length > 1 ? "s" : ""} avant enregistrement`}>
      <ul style={{ margin: 0, paddingLeft: "1.1rem" }} data-testid="op-issues">{r.issues.map((i, n) => <li key={n}><Badge tone={i.level === "blocking" ? "bad" : i.level === "soft" ? "neutral" : "warn"}>{i.level === "blocking" ? "Non dérogeable" : i.level === "soft" ? "Préférence" : "Dérogation"}</Badge> {i.message}</li>)}</ul>
      {!blocked && (r.can_override ? <Field label="Motif de la dérogation (facultatif)">{(p) => <Input {...p} value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} />}</Field>
        : <p style={{ margin: "var(--sp-2) 0 0" }}>{r.refusal ?? r.message}</p>)}
      <p className="help" style={{ margin: "var(--sp-2) 0 0" }}>Rien n&apos;a été modifié.</p>
    </Callout>
  );
}

/** Échange réciproque : deux collaborateurs échangent leurs shifts, en une seule opération (tout ou rien). */
export function SwapModal({ a, periodId, all, onClose, onDone }: { a: Assignment | null; periodId: string; all: Assignment[]; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const op = useConfirmed();
  const [who, setWho] = useState(""); const [other, setOther] = useState(""); const [reason, setReason] = useState("");
  const { reset } = op;
  useEffect(() => { setWho(""); setOther(""); setReason(""); reset(); }, [a?.assignment_id, reset]);
  const people = useMemo(() => {
    const m = new Map<string, string>();
    for (const x of all) if (a && x.employee_id !== a.employee_id) m.set(x.employee_id, x.employee);
    return [...m].sort((p, q) => p[1].localeCompare(q[1], "fr"));
  }, [all, a]);
  const theirs = all.filter((x) => x.employee_id === who).sort((p, q) => (p.day + p.start).localeCompare(q.day + q.start));
  const target = theirs.find((x) => x.assignment_id === other);
  async function go(force: boolean) {
    if (!a || !target) return;
    const r = await op.send<{ forced: boolean }>(`/periods/${periodId}/swap`, { a: a.assignment_id, b: target.assignment_id, reason: reason || null }, force);
    if (r) { toast.push(`Échange enregistré : ${a.employee} ↔ ${target.employee}${r.forced ? " (dérogation tracée)" : ""}.`, r.forced ? "warn" : "ok"); invalidate(); onDone(); }
  }
  return (
    <Modal open={!!a} onClose={() => !op.busy && onClose()} title="Échanger deux shifts" description={a ? `${a.employee} · ${label(a)}` : undefined}>
      {a && (
        <div className="stack" data-testid="swap-modal">
          <p className="help">Les deux collaborateurs échangent leurs shifts en une seule opération. Chacun est contrôlé sur le planning qui résulte de l&apos;échange (règles, plafond, repos, disponibilités) ; les deux affectations deviennent verrouillées.</p>
          <div className="row" style={{ alignItems: "flex-end" }}>
            <Field label="Avec">{(p) => <Select {...p} value={who} onChange={(e) => { setWho(e.target.value); setOther(""); op.reset(); }}><option value="">Choisir…</option>{people.map(([id, n]) => <option key={id} value={id}>{n}</option>)}</Select>}</Field>
            <Field label="Son shift">{(p) => <Select {...p} value={other} disabled={!who} onChange={(e) => { setOther(e.target.value); op.reset(); }} style={{ minWidth: "16rem" }}><option value="">Choisir…</option>{theirs.map((x) => <option key={x.assignment_id} value={x.assignment_id}>{label(x)}{x.day === a.day ? " (même jour)" : ""}</option>)}</Select>}</Field>
          </div>
          {target && <p style={{ margin: 0 }}><strong>{a.employee}</strong> prendra {label(target)} · <strong>{target.employee}</strong> prendra {label(a)}.</p>}
          {op.refused && <Refusal r={op.refused} reason={reason} setReason={setReason} />}
          {op.err && <Callout kind="bad" title="Échange non enregistré">{op.err}</Callout>}
          <div className="row modal-actions">
            <Button onClick={onClose} disabled={op.busy}>Annuler</Button>
            {op.refused?.code === "needs_confirmation" && op.refused.can_override
              ? <Button variant="primary" onClick={() => go(true)} disabled={op.busy} aria-busy={op.busy}>Confirmer l&apos;échange</Button>
              : <Button variant="primary" onClick={() => go(false)} disabled={!target || op.busy || op.refused?.code === "blocked"} aria-busy={op.busy}>Échanger</Button>}
          </div>
        </div>
      )}
    </Modal>
  );
}

/** Duplication : mêmes horaires, site, pause et marques, sur d'autres jours du planning, pour le même collaborateur. */
export function DuplicateModal({ a, period, onClose, onDone }: { a: Assignment | null; period: { start_date: string; end_date: string } | null; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const op = useConfirmed();
  const [days, setDays] = useState<string[]>([]); const [reason, setReason] = useState("");
  const { reset } = op;
  useEffect(() => { setDays([]); setReason(""); reset(); }, [a?.assignment_id, reset]);
  const all = useMemo(() => {
    if (!period) return [] as string[];
    const out: string[] = []; const d = new Date(`${period.start_date}T12:00:00Z`); const end = new Date(`${period.end_date}T12:00:00Z`);
    while (d <= end) { out.push(d.toISOString().slice(0, 10)); d.setUTCDate(d.getUTCDate() + 1); }
    return out;
  }, [period]);
  async function go(force: boolean) {
    if (!a) return;
    const r = await op.send<{ created: unknown[]; forced: boolean }>(`/assignments/${a.assignment_id}/duplicate`, { days, reason: reason || null }, force);
    if (r) { toast.push(`${r.created.length} copie(s) créée(s) pour ${a.employee}${r.forced ? " (dérogation tracée)" : ""}.`, r.forced ? "warn" : "ok"); invalidate(); onDone(); }
  }
  return (
    <Modal open={!!a} onClose={() => !op.busy && onClose()} title="Dupliquer ce shift" description={a ? `${a.employee} · ${label(a)}` : undefined}>
      {a && (
        <div className="stack" data-testid="duplicate-modal">
          <p className="help">Une copie par jour choisi : mêmes horaires, site, pause et marques, pour {a.employee}. Chaque copie est contrôlée en tenant compte des précédentes ; tout ou rien. Les copies sont verrouillées et retirables.</p>
          <div className="row" role="group" aria-label="Jours de copie">{all.map((d) => (
            <label key={d} className="chip-check"><input type="checkbox" disabled={d === a.day} checked={days.includes(d)}
              onChange={(e) => { setDays(e.target.checked ? [...days, d].sort() : days.filter((x) => x !== d)); op.reset(); }} /><span>{dayLabel(d)}</span></label>))}</div>
          {op.refused && <Refusal r={op.refused} reason={reason} setReason={setReason} />}
          {op.err && <Callout kind="bad" title="Duplication non enregistrée">{op.err}</Callout>}
          <div className="row modal-actions">
            <Button onClick={onClose} disabled={op.busy}>Annuler</Button>
            {op.refused?.code === "needs_confirmation" && op.refused.can_override
              ? <Button variant="primary" onClick={() => go(true)} disabled={op.busy} aria-busy={op.busy}>Confirmer la duplication</Button>
              : <Button variant="primary" onClick={() => go(false)} disabled={!days.length || op.busy || op.refused?.code === "blocked"} aria-busy={op.busy}>Dupliquer sur {days.length} jour{days.length > 1 ? "s" : ""}</Button>}
          </div>
        </div>
      )}
    </Modal>
  );
}
