"use client";
import { useMemo, useState } from "react";
import { Button, Callout, Field, Select } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/Toast";
import { invalidate } from "@/lib/invalidate";
import { Refusal, useConfirmed } from "./SwapDuplicate";

type Item = { assignment_id: string; start: string; end: string; site_name: string; brands: string[]; locked: boolean };
type Emp = { id: string; name: string; brands?: Record<string, string>; deleted_at?: string | null };
const DOW = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."];

/** Modification groupée : plusieurs shifts du mois passent à un autre collaborateur en une seule opération (tout ou rien), avec le même
 *  contrôle et la même confirmation qu'une affectation manuelle. */
export function BulkTransfer({ periodId, owner, shifts, emps, onDone }: { periodId: string; owner: string; shifts: { date: string; item: Item }[]; emps: Emp[]; onDone: () => void }) {
  const toast = useToast();
  const op = useConfirmed();
  const [picked, setPicked] = useState<string[]>([]); const [to, setTo] = useState(""); const [reason, setReason] = useState("");
  const chosen = shifts.filter((x) => picked.includes(x.item.assignment_id));
  const brands = useMemo(() => [...new Set(chosen.flatMap((x) => x.item.brands))], [chosen]);
  const pool = emps.filter((e) => !e.deleted_at && e.id !== owner && brands.every((b) => b in (e.brands ?? {})));
  async function go(force: boolean) {
    const r = await op.send<{ changed: number; forced: boolean }>(`/periods/${periodId}/bulk-transfer`,
      { operations: picked.map((id) => ({ assignment_id: id, to_employee_id: to })), reason: reason || null }, force);
    if (r) { toast.push(`${r.changed} shift(s) transféré(s)${r.forced ? " (dérogation tracée)" : ""}.`, r.forced ? "warn" : "ok"); setPicked([]); setTo(""); invalidate(); onDone(); }
  }
  const fr = (iso: string) => { const d = new Date(`${iso}T12:00:00Z`); return `${DOW[(d.getUTCDay() + 6) % 7]} ${iso.slice(8)}/${iso.slice(5, 7)}`; };
  return (
    <section className="glass-raised card stack" aria-label="Transférer plusieurs shifts" data-testid="bulk-transfer">
      <h3 className="h2" style={{ margin: 0 }}>Transférer plusieurs shifts</h3>
      <p className="help" style={{ margin: 0 }}>Une seule opération, tout ou rien : chaque transfert est contrôlé sur le planning qui résulte de l&apos;ensemble. Les shifts verrouillés ne sont pas proposés.</p>
      <div className="row" role="group" aria-label="Shifts à transférer">{shifts.filter((x) => !x.item.locked).map((x) => (
        <label key={x.item.assignment_id} className="chip-check"><input type="checkbox" checked={picked.includes(x.item.assignment_id)}
          onChange={(e) => { setPicked(e.target.checked ? [...picked, x.item.assignment_id] : picked.filter((p) => p !== x.item.assignment_id)); op.reset(); }} />
          <span>{fr(x.date)} · {x.item.start}–{x.item.end} · {x.item.site_name}</span></label>))}</div>
      <div className="row" style={{ alignItems: "flex-end" }}>
        <Field label="Transférer à">{(p) => <Select {...p} value={to} disabled={!picked.length} onChange={(e) => { setTo(e.target.value); op.reset(); }}><option value="">Choisir…</option>{pool.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</Select>}</Field>
        {op.refused?.code === "needs_confirmation" && op.refused.can_override
          ? <Button variant="primary" onClick={() => go(true)} disabled={op.busy} aria-busy={op.busy}>Confirmer le transfert</Button>
          : <Button variant="primary" onClick={() => go(false)} disabled={!picked.length || !to || op.busy || op.refused?.code === "blocked"} aria-busy={op.busy}>Transférer {picked.length || ""} shift{picked.length > 1 ? "s" : ""}</Button>}
      </div>
      {op.refused && <Refusal r={op.refused} reason={reason} setReason={setReason} />}
      {op.err && <Callout kind="bad" title="Transfert non enregistré">{op.err}</Callout>}
    </section>
  );
}
