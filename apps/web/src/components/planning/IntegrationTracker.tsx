"use client";
import { useState } from "react";
import { Badge, Button, Callout, Field, Select } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { useApi } from "@/components/hooks";
import { api } from "@/lib/api";
import { invalidate } from "@/lib/invalidate";
import { dayLabel, fmtHM, timeShort } from "@/lib/schedule";
import { errText } from "@/lib/wfm";

type CoverItem = { slot_key: string; state: "to_place" | "unassigned" | "conflict"; day: string; start: string; end: string; site: string; site_name: string; minutes: number;
  shift_id: string | null; assignment_id: string | null; employee: string | null; conflicts: string[] };
type Coverage = { total: number; covered: number; conflict: number; unassigned: number; to_place: number; assigned: number; remaining: number; need_minutes: number;
  covered_minutes: number; remaining_minutes: number; needs_missing: boolean; complete: boolean; items: CoverItem[] };
type Item = { id: string; kind: "brand"; brand: string; name: string; coverage: Coverage } | { id: string; kind: "employee"; employee_id: string; name: string; assigned: number; minutes: number };
type Emp = { id: string; name: string; brands?: Record<string, string> };

const STATE: Record<CoverItem["state"], { label: string; tone: "warn" | "info" | "bad" }> = {
  to_place: { label: "À placer", tone: "info" }, unassigned: { label: "Placé, sans collaborateur", tone: "warn" }, conflict: { label: "Affecté en conflit", tone: "bad" },
};

/**
 * Suivi persistant (serveur) des ajouts intégrés « manuellement » au planning du mois : couverture de la marque d'après ses besoins du mois,
 * mise à jour à chaque modification (bus d'invalidation : écran, autre onglet, autre manager). Un shift affecté en conflit n'est jamais présenté comme couvert ; sans besoins définis :
 * « Besoins à renseigner ». Pour attribuer, le choix du collaborateur ouvre la fenêtre habituelle (contrôles, confirmations, rappels).
 */
export function IntegrationTracker({ periodId, emps, canEdit, onPick, onChanged }: { periodId: string; emps: Emp[]; canEdit: boolean;
  onPick: (emp: Emp, day: string) => void; onChanged: () => void }) {
  const toast = useToast();
  const q = useApi<{ items: Item[] }>(`/periods/${periodId}/integrations`);
  const [assigning, setAssigning] = useState<{ brand: string; name: string; row: CoverItem } | null>(null);
  const [who, setWho] = useState(""); const [busy, setBusy] = useState(false);
  const items = q.data?.items ?? [];
  if (!items.length) return null;

  async function dismiss(id: string) {
    try { await api(`/periods/${periodId}/integrations/${id}/dismiss`, { method: "POST" }); invalidate(); } catch (e) { toast.push(errText(e), "bad"); }
  }
  async function place(it: Extract<Item, { kind: "brand" }>, row: CoverItem) {
    setBusy(true);
    try {
      await api(`/periods/${periodId}/integrations/${it.id}/place`, { method: "POST", json: { slot_key: row.slot_key } });
      toast.push(`Shift ${it.name} placé le ${dayLabel(row.day)} : choisissez maintenant le collaborateur.`, "ok");
      onChanged(); setWho(""); setAssigning({ brand: it.brand, name: it.name, row });
    } catch (e) { toast.push(errText(e), "bad"); } finally { setBusy(false); }
  }
  const allowed = assigning ? emps.filter((e) => e.brands && assigning.brand in e.brands) : [];

  return (
    <div className="stack" data-testid="integration-tracker">
      {items.map((it) => it.kind === "employee" ? (
        <Callout key={it.id} kind="info" title={`${it.name} fait partie de l'effectif de ce mois`}>
          <span data-testid="tracker-employee">{it.assigned ? `${it.assigned} shift${it.assigned > 1 ? "s" : ""} attribué${it.assigned > 1 ? "s" : ""} (${fmtHM(it.minutes)}).` : "Aucun shift attribué pour l'instant."} Attribuez-lui des shifts depuis son planning ; les contrôles habituels s&apos;appliquent.</span>
          {canEdit && <div className="row" style={{ marginTop: "var(--sp-1)" }}><Button size="sm" onClick={() => void dismiss(it.id)}>Masquer</Button></div>}
        </Callout>
      ) : (() => {
        const c = it.coverage;
        if (c.needs_missing) return (
          <Callout key={it.id} kind="warn" title={`${it.name} : Besoins à renseigner`}>
            <span data-testid="tracker-brand">Aucun besoin n&apos;est défini pour {it.name} ce mois-ci : la couverture ne peut pas être suivie. <a href="/catalog" style={{ textDecoration: "underline" }}>Renseigner les besoins dans « Sites et marques »</a></span>
          </Callout>);
        if (c.complete) return (
          <Callout key={it.id} kind="ok" title={`Tous les shifts de ${it.name} sont attribués et sans conflit.`}>
            <span data-testid="tracker-brand">{c.total} shift{c.total > 1 ? "s" : ""} · {fmtHM(c.covered_minutes)} couvertes. Reste à attribuer : 0 shift · 0 h. Vous serez prévenu·e si la couverture redevient incomplète.</span>
            {canEdit && <div className="row" style={{ marginTop: "var(--sp-1)" }}><Button size="sm" onClick={() => void dismiss(it.id)}>Masquer le suivi</Button></div>}
          </Callout>);
        return (
          <Callout key={it.id} kind="warn" title={`${it.name} : ${c.assigned} shift${c.assigned > 1 ? "s" : ""} attribué${c.assigned > 1 ? "s" : ""} sur ${c.total} — ${c.remaining} reste${c.remaining > 1 ? "nt" : ""} à compléter.`}>
            <p style={{ margin: 0 }} data-testid="tracker-remaining"><strong>Reste à attribuer : {c.remaining} shift{c.remaining > 1 ? "s" : ""} · {fmtHM(c.remaining_minutes)}</strong></p>
            <p className="help" style={{ margin: 0 }} data-testid="tracker-brand">
              {fmtHM(c.covered_minutes)} couvertes · {fmtHM(c.remaining_minutes)} restantes
              {c.to_place ? ` · ${c.to_place} à placer` : ""}{c.unassigned ? ` · ${c.unassigned} placé${c.unassigned > 1 ? "s" : ""} sans collaborateur` : ""}{c.conflict ? ` · ${c.conflict} en conflit (non compté${c.conflict > 1 ? "s" : ""} comme couvert${c.conflict > 1 ? "s" : ""})` : ""}
            </p>
            <p className="help" style={{ margin: 0 }}>Une notification vous préviendra lorsque tous les besoins de {it.name} seront couverts sans conflit.</p>
            <details className="history-details" data-testid="tracker-details"><summary>Voir les shifts à compléter ({c.items.length})</summary>
              <ul className="cover-list">{c.items.map((r) => (
                <li key={r.slot_key} className="cover-row" data-state={r.state}>
                  <span><strong>{dayLabel(r.day)}</strong> · {timeShort(r.start)}–{timeShort(r.end)} · {r.site_name} <Badge tone={STATE[r.state].tone}>{STATE[r.state].label}</Badge>
                    {r.employee && <span className="faint"> — {r.employee}</span>}
                    {r.conflicts.length > 0 && <span className="help" style={{ display: "block" }}>{r.conflicts.join(" · ")}</span>}</span>
                  {canEdit && r.state === "to_place" && <Button size="sm" disabled={busy} onClick={() => void place(it, r)}>Placer et attribuer</Button>}
                  {canEdit && r.state === "unassigned" && <Button size="sm" onClick={() => { setWho(""); setAssigning({ brand: it.brand, name: it.name, row: r }); }}>Attribuer…</Button>}
                </li>))}</ul>
            </details>
          </Callout>);
      })())}
      <Modal open={!!assigning} onClose={() => setAssigning(null)} title={assigning ? `Attribuer le shift ${assigning.name}` : ""}
        description={assigning ? `${dayLabel(assigning.row.day)} · ${timeShort(assigning.row.start)}–${timeShort(assigning.row.end)} · ${assigning.row.site_name}` : undefined}>
        {assigning && <form className="stack" onSubmit={(e) => { e.preventDefault(); const emp = allowed.find((x) => x.id === who); if (emp) { setAssigning(null); onPick(emp, assigning.row.day); } }}>
          {allowed.length === 0 ? <Callout kind="warn" title={`Aucun collaborateur autorisé pour ${assigning.name}`}>Autorisez des collaborateurs pour cette marque dans « Sites et marques ».</Callout> : (
            <Field label="Collaborateur" help="La fenêtre suivante liste les shifts du jour et vérifie les contraintes avant toute attribution.">{(p) => (
              <Select {...p} value={who} onChange={(e) => setWho(e.target.value)}><option value="">Choisir…</option>{allowed.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</Select>)}</Field>)}
          <div className="row modal-actions"><Button type="button" onClick={() => setAssigning(null)}>Annuler</Button><Button type="submit" variant="primary" disabled={!who}>Continuer</Button></div>
        </form>}
      </Modal>
    </div>
  );
}
