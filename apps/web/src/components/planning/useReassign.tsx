"use client";
import { useCallback, useMemo, useRef, useState } from "react";
import { Badge, Button, Callout } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { brandColor } from "@/lib/brand";
import { hourRange, longDate, previewConflicts } from "@/lib/reassign";
import { fmtHM, History, type Assignment } from "@/lib/schedule";

type Emp = { id: string; name: string; brands?: Record<string, string> };
export type Pending = { a: Assignment; to: Emp; from: Emp | undefined };

/**
 * UNIQUE point d'entrée des réaffectations : `request` ouvre toujours la confirmation ; l'appel API (`commit`) est privé à ce hook.
 * Toute nouvelle méthode de réaffectation (glisser-déposer, sélecteur, fiche, raccourci…) doit passer par `request`.
 * « Annuler / Rétablir » rejouent une réaffectation déjà confirmée et ne redemandent pas de confirmation.
 */
export function useReassign({ all, emps, refresh, getSchedule }: { all: Assignment[]; emps: Emp[]; refresh: () => void; getSchedule: () => Promise<Assignment[]> }) {
  const toast = useToast();
  const history = useRef(new History());
  const [, bump] = useState(0);
  const [pending, setPending] = useState<Pending | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const byId = useMemo(() => new Map(emps.map((e) => [e.id, e])), [emps]);

  const commit = useCallback(async (a: Assignment, toId: string, record: boolean): Promise<boolean> => {
    try {
      const r = await api<{ conflicts: string[] }>(`/assignments/${a.assignment_id}`, { method: "PUT", json: { employee_id: toId } });
      if (record) history.current.push({ assignmentId: a.assignment_id, from: a.employee_id, to: toId });
      const mine = r.conflicts.filter((c) => c.includes(a.slot_key));
      const who = byId.get(toId)?.name ?? "le collaborateur";
      const undo = record ? { label: "Annuler", run: () => { void step("undo"); } } : undefined;
      toast.push(mine.length ? `Shift réaffecté à ${who} — ${mine.length} conflit(s) détecté(s) : voir la carte signalée.` : `Shift réaffecté à ${who}.`, mine.length ? "warn" : "ok", undo);
      refresh(); bump((x) => x + 1);
      return true;
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "erreur inconnue";
      setError(`Le remplacement n'a pas pu être enregistré (${msg}). L'affectation d'origine est conservée.`);
      return false;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [byId, refresh, toast]);

  async function step(kind: "undo" | "redo") {
    const m = kind === "undo" ? history.current.undo() : history.current.redo(); if (!m) return;
    const list = await getSchedule();
    const a = list.find((x) => x.assignment_id === m.assignmentId); if (!a) return;
    const ok = await commit(a, kind === "undo" ? m.from : m.to, false);
    if (ok) toast.push(kind === "undo" ? "Modification annulée : l'affectation précédente est restaurée." : "Modification rétablie.", "info");
    else { toast.push("L'annulation n'a pas pu être enregistrée. Réessayez.", "bad"); setError(""); }
  }

  /** Demande de réaffectation : n'enregistre RIEN, ouvre la confirmation. */
  const request = useCallback((a: Assignment, toId: string) => {
    if (a.locked) { toast.push("Affectation verrouillée : déverrouillez-la d'abord.", "warn"); return; }
    if (toId === a.employee_id) return;
    const to = byId.get(toId); if (!to) return;
    setError(""); setPending({ a, to, from: byId.get(a.employee_id) });
  }, [byId, toast]);

  const cancel = useCallback(() => { if (!saving) { setPending(null); setError(""); } }, [saving]);
  async function confirm() {
    if (!pending || saving) return;
    setSaving(true); setError("");
    const ok = await commit(pending.a, pending.to.id, true);
    setSaving(false);
    if (ok) setPending(null);
  }

  const dialog = (
    <ConfirmDialog pending={pending} all={all} saving={saving} error={error} onCancel={cancel} onConfirm={confirm} />
  );
  return { request, undo: () => step("undo"), redo: () => step("redo"), canUndo: history.current.canUndo, canRedo: history.current.canRedo, dialog };
}

export function ConfirmDialog({ pending, all, saving, error, onCancel, onConfirm }: { pending: Pending | null; all: Assignment[]; saving: boolean; error: string; onCancel: () => void; onConfirm: () => void }) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const a = pending?.a;
  const warnings = pending && a ? previewConflicts(a, pending.to.id, all, pending.to.brands) : [];
  const brands = a ? Object.keys(a.allocations) : [];
  return (
    <Modal open={!!pending} onClose={onCancel} title="Confirmer le remplacement ?" hideClose variant="confirm" initialFocusRef={cancelRef}
      description={pending && a ? `Remplacement de ${pending.from?.name ?? "l'ancien collaborateur"} par ${pending.to.name}, ${longDate(a.day)}, ${a.site}, ${hourRange(a.start, a.end)}.` : undefined}>
      {pending && a && (
        <>
          <div className="swap" aria-hidden="true">
            <div className="swap-card" data-side="from"><span className="eyebrow">Actuellement</span><strong>{pending.from?.name ?? "—"}</strong></div>
            <Icon name="swap" size={20} className="swap-arrow" />
            <div className="swap-card" data-side="to"><span className="eyebrow">Nouveau</span><strong>{pending.to.name}</strong></div>
          </div>
          <dl className="facts">
            <div><dt>Date</dt><dd>{longDate(a.day)}</dd></div>
            <div><dt>Horaires</dt><dd className="num">{hourRange(a.start, a.end)}</dd></div>
            <div><dt>Site</dt><dd>{a.site}</dd></div>
            <div><dt>Marque{brands.length > 1 ? "s" : ""}</dt><dd className="row">{brands.map((b) => <Badge key={b}><i className="dot" style={{ ["--c" as string]: brandColor(b) }} />{b}</Badge>)}</dd></div>
            <div><dt>Travail effectif</dt><dd className="num">{fmtHM(a.effective_minutes)} <span className="faint">(présence {fmtHM(a.presence_minutes)}, pause {a.break_minutes} min)</span></dd></div>
          </dl>
          {warnings.length > 0 ? (
            <Callout kind="warn" title={`${warnings.length} avertissement${warnings.length > 1 ? "s" : ""} avant enregistrement`}>
              <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>{warnings.map((w) => <li key={w.text}>{w.text}</li>)}</ul>
              <p className="help" style={{ marginTop: "var(--sp-1)" }}>Vous pouvez confirmer : le conflit sera enregistré et signalé sur la carte.</p>
            </Callout>
          ) : <p className="help"><Icon name="info" size={13} style={{ verticalAlign: "-2px" }} /> Aucun conflit détecté à l&apos;avance. Le serveur revérifie toutes les contraintes après l&apos;enregistrement.</p>}
          {error && <Callout kind="bad" title="Échec de l'enregistrement">{error}</Callout>}
          <div className="row modal-actions">
            <Button ref={cancelRef} onClick={onCancel} disabled={saving}>Annuler</Button>
            <Button variant="primary" onClick={onConfirm} disabled={saving} aria-busy={saving}>{saving ? "Enregistrement…" : "Confirmer le remplacement"}</Button>
          </div>
        </>
      )}
    </Modal>
  );
}
