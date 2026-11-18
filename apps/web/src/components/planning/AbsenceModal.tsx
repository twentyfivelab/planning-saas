"use client";
import { useEffect, useState } from "react";
import { Badge, Button, Callout, Field, Input, Select } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { invalidate } from "@/lib/invalidate";
import { hourRange, longDate } from "@/lib/reassign";
import { errText } from "@/lib/wfm";
import { ReplacementsModal, type Candidate, type ReplaceTarget } from "./ReplacementsModal";
import { SimulationPreview } from "./SimulationPreview";

type Impact = { employee: { id: string; name: string }; start: string; end: string; without_candidate: number; shifts: { shift_id: string; assignment_id: string; day: string; site: string; start: string; end: string; locked: boolean; compatible: number; candidates: Candidate[] }[] };

/** Absence imprévue : enregistre l'indisponibilité puis propose trois réponses, de la plus locale à la plus large. Aucun shift n'est retiré sans décision. */
export function AbsenceModal({ open, periodId, period, emps, canOptimize, canEdit, onClose, onChanged }: { open: boolean; periodId: string; period: { start_date: string; end_date: string } | null; emps: { id: string; name: string }[]; canOptimize: boolean; canEdit: boolean; onClose: () => void; onChanged: () => void }) {
  const toast = useToast();
  const [emp, setEmp] = useState(""); const [start, setStart] = useState(""); const [end, setEnd] = useState(""); const [reason, setReason] = useState("");
  const [impact, setImpact] = useState<Impact | null>(null);
  const [busy, setBusy] = useState(false); const [err, setErr] = useState(""); const [radius, setRadius] = useState(0);
  const [run, setRun] = useState<string | null>(null);
  const [replace, setReplace] = useState<ReplaceTarget>(null);
  useEffect(() => { if (open) { setImpact(null); setErr(""); setRun(null); setReason(""); setEmp(""); setStart(""); setEnd(""); } }, [open]);
  async function declare() {
    if (!emp || !start) return;
    setBusy(true); setErr("");
    try { const r = await api<Impact>(`/periods/${periodId}/absences`, { method: "POST", json: { employee_id: emp, start, end: end || start, reason: reason.trim() || null } }); setImpact(r); invalidate(); toast.push(`Absence enregistrée pour ${r.employee.name}.`, "ok"); }
    catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  async function refresh() {
    if (!impact) return;
    try { setImpact(await api<Impact>(`/periods/${periodId}/absence-impact?employee_id=${impact.employee.id}&start=${impact.start}&end=${impact.end}`)); } catch { /* conserve la liste affichée */ }
    onChanged();
  }
  async function partial() {
    if (!impact) return;
    setBusy(true); setErr("");
    try { const r = await api<{ run_id: string }>(`/periods/${periodId}/local-reoptimize`, { method: "POST", json: { employee_id: impact.employee.id, start: impact.start, end: impact.end, radius_days: radius } }); setRun(r.run_id); }
    catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  return (
    <>
      <Modal open={open} onClose={() => !busy && onClose()} title="Déclarer une absence" description="L'absence est enregistrée dans les indisponibilités. Le planning ne change que sur votre décision.">
        <div className="stack">
          {!impact && (
            <>
              <div className="toolbar">
                <Field label="Collaborateur">{(p) => <Select {...p} value={emp} onChange={(e) => setEmp(e.target.value)}><option value="">Choisir…</option>{emps.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</Select>}</Field>
                <Field label="Du">{(p) => <Input {...p} type="date" value={start} min={period?.start_date} max={period?.end_date} onChange={(e) => setStart(e.target.value)} />}</Field>
                <Field label="Au" help="Vide : un seul jour">{(p) => <Input {...p} type="date" value={end} min={start || period?.start_date} max={period?.end_date} onChange={(e) => setEnd(e.target.value)} />}</Field>
              </div>
              <Field label="Motif (facultatif)">{(p) => <Input {...p} value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)} />}</Field>
              <div className="row modal-actions"><Button onClick={onClose}>Annuler</Button><Button variant="primary" disabled={!emp || !start || busy} aria-busy={busy} onClick={declare}>Enregistrer et voir les shifts concernés</Button></div>
            </>
          )}
          {impact && (
            <>
              <p><strong>{impact.employee.name}</strong> : {impact.shifts.length} shift{impact.shifts.length > 1 ? "s" : ""} concerné{impact.shifts.length > 1 ? "s" : ""}{impact.without_candidate > 0 ? `, dont ${impact.without_candidate} sans remplaçant compatible` : ""}.</p>
              {impact.shifts.length === 0 ? <Callout kind="ok">Aucun shift planifié sur ces dates : rien d&apos;autre à faire.</Callout> : (
                <>
                  <section aria-label="Remplacement simple" className="stack" style={{ gap: "var(--sp-2)" }}>
                    <h3 className="h2">1. Remplacement simple</h3>
                    <p className="help">Un remplaçant par shift, sans toucher aux autres affectations.</p>
                    <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0, gap: "var(--sp-2)" }}>
                      {impact.shifts.map((s) => (
                        <li key={s.shift_id} className="surface" style={{ padding: "var(--sp-3)" }}>
                          <div className="spread">
                            <div><strong>{longDate(s.day)}</strong> <span className="muted">· {s.site} · {hourRange(s.start, s.end)}</span> {s.locked && <Badge tone="accent" icon="lock">Verrouillé</Badge>}</div>
                            <Button size="sm" disabled={!canEdit} onClick={() => setReplace({ shift_id: s.shift_id, label: `${longDate(s.day)} · ${s.site} · ${hourRange(s.start, s.end)}` })}>Voir les {s.compatible} remplaçant{s.compatible > 1 ? "s" : ""}</Button>
                          </div>
                          {s.candidates[0] ? <p className="help" style={{ margin: "var(--sp-1) 0 0" }}>Meilleur candidat : <strong>{s.candidates[0].name}</strong> ({s.candidates[0].brand_level_label})</p> : <p className="help" style={{ margin: "var(--sp-1) 0 0" }}>Aucun remplaçant compatible.</p>}
                        </li>))}
                    </ul>
                  </section>
                  {canOptimize && (
                    <section aria-label="Réoptimisation partielle" className="stack" style={{ gap: "var(--sp-2)" }}>
                      <h3 className="h2">2. Réoptimisation partielle</h3>
                      <p className="help">Le moteur réorganise seulement ces shifts, et si besoin ceux des jours voisins ; tout le reste est figé. Vous voyez le résultat avant de l&apos;appliquer.</p>
                      <div className="row" style={{ alignItems: "flex-end" }}>
                        <Field label="Jours voisins inclus">{(p) => <Select {...p} value={radius} onChange={(e) => setRadius(Number(e.target.value))}><option value={0}>Aucun : uniquement ces shifts</option><option value={1}>± 1 jour</option><option value={2}>± 2 jours</option><option value={3}>± 3 jours</option></Select>}</Field>
                        <Button icon="sparkles" disabled={busy} onClick={partial}>Calculer une proposition</Button>
                      </div>
                      {run && <SimulationPreview runId={run} canApply={canOptimize} onApplied={() => { setRun(null); void refresh(); }} />}
                    </section>
                  )}
                  {canOptimize && (
                    <section aria-label="Réoptimisation complète" className="stack" style={{ gap: "var(--sp-2)" }}>
                      <h3 className="h2">3. Réoptimisation complète</h3>
                      <p className="help">Recalcule tout le mois (hors shifts verrouillés) : à lancer depuis « Générer », qui garde une copie de sécurité du planning actuel.</p>
                      <div><a className="btn" href="/generate">Régénérer le mois</a></div>
                    </section>
                  )}
                </>
              )}
              <div className="row modal-actions"><Button onClick={onClose} disabled={busy}>Fermer</Button></div>
            </>
          )}
          {err && <Callout kind="bad" title="Opération impossible">{err}</Callout>}
        </div>
      </Modal>
      <ReplacementsModal target={replace} periodId={periodId} canEdit={canEdit} onClose={() => setReplace(null)} onDone={() => { setReplace(null); void refresh(); }} />
    </>
  );
}
