"use client";
import { useEffect, useState } from "react";
import { Badge, Button, Callout, EmptyState, Progress } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { useApi } from "@/components/hooks";
import { api } from "@/lib/api";
import { parseDetail, type AssignDetail } from "@/lib/manualShift";
import { errText, fmtCHF, fmtH } from "@/lib/wfm";
import { AlertStep } from "./DayShiftsModal";
import { ProposalStatus, ProposeControl, type ReplacementRequest } from "./ReplacementProposal";

export type TermLine = { term: string; label: string; points: number; effect: "favorable" | "defavorable" };
export type Candidate = {
  employee_id: string; employee_uuid: string | null; name: string; status: "compatible" | "impossible"; brand_level_label: string; minutes: number; target_minutes: number; after_minutes: number;
  available: boolean; skills_ok: boolean; has_account?: boolean; cost_cents: number | null; delta_cost: number | null; score: number | null; terms: TermLine[]; blocking: { code: string; message: string }[];
};
type Ranking = { holder_name: string | null; holder_id: string | null; candidates: Candidate[]; compatible: number; cost_if_uncovered: number | null; day: string; site: string; start: string; end: string; weights_note: string };
export type ReplaceTarget = { shift_id: string; label: string } | null;

export const points = (n: number) => `${n > 0 ? "+" : ""}${n.toLocaleString("fr-CH")} pt${Math.abs(n) > 1 ? "s" : ""}`;

export function TermList({ terms }: { terms: TermLine[] }) {
  if (!terms.length) return <p className="help">Aucun critère ne change avec ce choix.</p>;
  return <ul className="term-list">{terms.map((t) => <li key={t.term}><span>{t.label}</span><span className="num" data-effect={t.effect}>{points(t.points)}</span></li>)}</ul>;
}

/** Remplaçants classés par le moteur : règles strictes vérifiées, puis coût réel du changement. Le manager choisit directement. */
export function ReplacementsModal({ target, periodId, canEdit, onClose, onDone }: { target: ReplaceTarget; periodId: string; canEdit: boolean; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const r = useApi<Ranking>(target ? `/shifts/${target.shift_id}/replacements` : null);
  const pr = useApi<{ request: ReplacementRequest | null }>(target ? `/shifts/${target.shift_id}/replacement-request` : null);
  const openReq = pr.data?.request?.status === "open" ? pr.data.request : null;
  const [alert, setAlert] = useState<{ c: Candidate; d: AssignDetail } | null>(null);
  const [busy, setBusy] = useState(false); const [err, setErr] = useState(""); const [reason, setReason] = useState("");
  useEffect(() => { setAlert(null); setErr(""); setReason(""); }, [target]);
  async function choose(c: Candidate, force = false) {
    if (!target || !c.employee_uuid || busy) return;
    setBusy(true); setErr("");
    try {
      await api(`/periods/${periodId}/manual-assign`, { method: "POST", json: { employee_id: c.employee_uuid, shift_id: target.shift_id, force, reason: reason.trim() || null, expected_from: r.data?.holder_id ?? "free" } });
      toast.push(r.data?.holder_name ? `Shift de ${r.data.holder_name} transféré à ${c.name}.` : `Shift attribué à ${c.name}.`, force ? "warn" : "ok");
      onDone();
    } catch (e) {
      const d = parseDetail(e);
      if (d?.code === "stale") { setErr(d.message); setAlert(null); r.reload(); }
      else if (d && (d.issues?.length || d.code === "forbidden")) setAlert({ c, d });
      else setErr(errText(e));
    } finally { setBusy(false); }
  }
  const ok = r.data?.candidates.filter((c) => c.status === "compatible") ?? [];
  const no = r.data?.candidates.filter((c) => c.status === "impossible") ?? [];
  return (
    <Modal open={!!target} onClose={() => !busy && onClose()} title="Remplaçants proposés" description={target?.label}>
      {alert ? <AlertStep detail={alert.d} name={alert.c.name} shift={target?.label ?? ""} reason={reason} setReason={setReason} busy={busy} onCancel={() => setAlert(null)} onAccept={() => choose(alert.c, true)} /> : (
        <div className="stack">
          {r.loading && !r.data ? <p className="muted" role="status">Calcul du classement…</p> : r.error ? <Callout kind="bad" title="Classement indisponible">{r.error}</Callout> : r.data && (
            <>
              {pr.data?.request && <ProposalStatus req={pr.data.request} canEdit={canEdit} onChanged={pr.reload} />}
              {openReq && <p className="help">Une proposition est en cours : « Choisir » attribue directement le shift et rend la proposition caduque (le collaborateur sollicité en est informé).</p>}
              <p className="help">{r.data.holder_name ? <>Titulaire actuel : <strong>{r.data.holder_name}</strong>. </> : <>Shift non couvert. </>}Chaque candidat est contrôlé par le vérificateur, puis classé selon la variation réelle du coût du planning. {r.data.weights_note}</p>
              {ok.length === 0 ? <EmptyState icon="users" title="Aucun remplaçant compatible">Aucun collaborateur ne respecte toutes les règles strictes pour ce shift. Voir le détail ci-dessous.</EmptyState> : (
                <ol className="cand-list" aria-label="Remplaçants compatibles, du plus pertinent au moins pertinent">
                  {ok.map((c, i) => (
                    <li key={c.employee_id} className="cand">
                      <div className="spread">
                        <div className="row"><span className="cand-rank num" aria-label={`Rang ${i + 1}`}>{i + 1}</span><strong>{c.name}</strong><Badge tone={c.brand_level_label === "Prioritaire" ? "ok" : "neutral"}>{c.brand_level_label}</Badge></div>
                        {canEdit && <div className="row" style={{ flexWrap: "nowrap" }}>
                          {target && r.data && <ProposeControl shift={{ shift_id: target.shift_id, day: r.data.day, start: r.data.start }} candidate={c} disabled={busy || !!openReq} onSent={pr.reload} />}
                          <Button size="sm" variant={i === 0 ? "primary" : "default"} disabled={busy} onClick={() => choose(c)} aria-label={`Choisir ${c.name}`}>Choisir</Button>
                        </div>}
                      </div>
                      <div className="cand-score"><Progress value={c.score ?? 0} label={`Pertinence de ${c.name}`} /><span className="num">{c.score} / 100</span></div>
                      <dl className="cand-facts">
                        <div><dt>Disponibilité</dt><dd>{c.available ? "Disponible" : "Indisponible"}</dd></div>
                        <div><dt>Qualifications</dt><dd>{c.skills_ok ? "Conformes" : "Manquantes"}</dd></div>
                        <div><dt>Heures attribuées</dt><dd className="num">{fmtH(c.minutes)} → {fmtH(c.after_minutes)}</dd></div>
                        <div><dt>Objectif</dt><dd className="num">{fmtH(c.target_minutes)}</dd></div>
                        <div><dt>Coût estimé</dt><dd className="num">{fmtCHF(c.cost_cents) ?? "Non renseigné"}</dd></div>
                        <div><dt>Coût pour le moteur</dt><dd className="num">{points(c.delta_cost ?? 0)}</dd></div>
                      </dl>
                      <details><summary>Détail du score</summary><TermList terms={c.terms} /></details>
                    </li>))}
                </ol>
              )}
              {no.length > 0 && (
                <details><summary>{no.length} collaborateur{no.length > 1 ? "s" : ""} écarté{no.length > 1 ? "s" : ""} par une règle stricte</summary>
                  <ul className="stack" style={{ listStyle: "none", padding: 0, margin: "var(--sp-2) 0 0", gap: "var(--sp-1)" }}>
                    {no.map((c) => <li key={c.employee_id} className="row"><Icon name="x" size={13} /><strong>{c.name}</strong><span className="muted">{c.blocking[0]?.message}</span></li>)}
                  </ul>
                </details>)}
            </>
          )}
          {err && <Callout kind="bad" title="Opération impossible">{err}</Callout>}
          <div className="row modal-actions"><Button onClick={onClose} disabled={busy}>Fermer</Button></div>
        </div>
      )}
    </Modal>
  );
}
