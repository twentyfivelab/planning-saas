"use client";
import { useState } from "react";
import { Badge, Button, Callout, Field, Select } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { useApi } from "@/components/hooks";
import { api } from "@/lib/api";
import { dayLabel, fmtHM } from "@/lib/schedule";
import { errText } from "@/lib/wfm";

type Need = { slot_key: string; day: string; start: string; end: string; site: string; site_name: string; brands: string[]; brand_label: string; minutes: number; shift_id: string | null; placed: boolean };
type Resp = { total: number; minutes: number; brands: { brand: string; codes: string[]; shifts: number; minutes: number; budget_minutes: number | null; planned_minutes: number }[]; items: Need[] };
type Emp = { id: string; name: string; brands?: Record<string, string> };

/** Besoins optionnels du mois sans collaborateur : visibles (par marque, avec le budget du mois), et complétables à la main.
 *  « Placer et attribuer » crée le shift du besoin puis ouvre la fenêtre habituelle d'attribution (contrôles, confirmations, rappels). */
export function OptionalNeeds({ periodId, emps, canEdit, onPick, onChanged }: { periodId: string; emps: Emp[]; canEdit: boolean; onPick: (emp: Emp, day: string) => void; onChanged: () => void }) {
  const toast = useToast();
  const q = useApi<Resp>(`/periods/${periodId}/optional-needs`);
  const [assigning, setAssigning] = useState<Need | null>(null); const [who, setWho] = useState(""); const [busy, setBusy] = useState(false);
  const d = q.data;
  if (!d || !d.total) return null;
  async function place(n: Need) {
    setBusy(true);
    try {
      if (!n.placed) await api(`/periods/${periodId}/needs/place`, { method: "POST", json: { slot_key: n.slot_key } });
      setWho(""); setAssigning(n); onChanged();
    } catch (e) { toast.push(errText(e), "bad"); } finally { setBusy(false); }
  }
  const allowed = assigning ? emps.filter((e) => e.brands && assigning.brands.every((b) => b in e.brands!)) : [];
  return (
    <details className="glass card" id="besoins-optionnels" data-testid="optional-needs">
      <summary><strong>Besoins optionnels non attribués : {d.total} shift{d.total > 1 ? "s" : ""} ({fmtHM(d.minutes)})</strong> <span className="help">— retenus par le moteur selon les budgets et l&apos;équilibre des heures ; à compléter à la main si vous le souhaitez</span></summary>
      <div className="stack" style={{ marginTop: "var(--sp-2)" }}>
        <ul className="help" style={{ margin: 0, paddingLeft: "1.1rem" }} data-testid="optional-by-brand">
          {d.brands.map((b) => <li key={b.brand}><strong>{b.brand}</strong> : {b.shifts} shift(s), {fmtHM(b.minutes)} non attribués · {b.budget_minutes === null ? "aucun budget ce mois-ci (aucun volume visé)" : `budget ${fmtHM(b.budget_minutes)}, planifié ${fmtHM(b.planned_minutes)}`}</li>)}
        </ul>
        <ul className="cover-list">{d.items.map((n) => (
          <li key={n.slot_key} className="cover-row" data-testid="optional-need">
            <span><strong>{dayLabel(n.day)}</strong> · {n.start}–{n.end} · {n.site_name} · {n.brand_label} <span className="faint">({fmtHM(n.minutes)})</span>{n.placed && <> <Badge tone="warn">Placé, sans collaborateur</Badge></>}</span>
            {canEdit && <Button size="sm" disabled={busy} onClick={() => void place(n)}>{n.placed ? "Attribuer…" : "Placer et attribuer"}</Button>}
          </li>))}</ul>
      </div>
      <Modal open={!!assigning} onClose={() => setAssigning(null)} title={assigning ? `Attribuer le shift ${assigning.brand_label}` : ""}
        description={assigning ? `${dayLabel(assigning.day)} · ${assigning.start}–${assigning.end} · ${assigning.site_name}` : undefined}>
        {assigning && <form className="stack" onSubmit={(e) => { e.preventDefault(); const emp = allowed.find((x) => x.id === who); if (emp) { setAssigning(null); onPick(emp, assigning.day); } }}>
          {allowed.length === 0 ? <Callout kind="warn" title="Aucun collaborateur autorisé">Autorisez des collaborateurs pour {assigning.brand_label} dans « Sites et marques ».</Callout> : (
            <Field label="Collaborateur" help="La fenêtre suivante liste les shifts du jour et vérifie les contraintes avant toute attribution.">{(p) => (
              <Select {...p} value={who} onChange={(e) => setWho(e.target.value)}><option value="">Choisir…</option>{allowed.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</Select>)}</Field>)}
          <div className="row modal-actions"><Button type="button" onClick={() => setAssigning(null)}>Annuler</Button><Button type="submit" variant="primary" disabled={!who}>Continuer</Button></div>
        </form>}
      </Modal>
    </details>
  );
}
