"use client";
import { useEffect, useRef, useState } from "react";
import { Badge, Button, Callout, EmptyState, Field, Input } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { useApi } from "@/components/hooks";
import { api } from "@/lib/api";
import { invalidate } from "@/lib/invalidate";
import { brandColor } from "@/lib/brand";
import { fmtHM } from "@/lib/schedule";
import { hourRange, longDate } from "@/lib/reassign";
import { blockingOf, canAccept, parseDetail, rowLabel, sortRows, type AssignDetail, type DayRow } from "@/lib/manualShift";

export type DayTarget = { emp: { id: string; name: string; brands?: Record<string, string> }; day: string } | null;
type Day = { day: string; shifts: DayRow[]; employee_has_shift: DayRow | null; can_override: boolean };
type View = { step: "list" } | { step: "confirm"; row: DayRow } | { step: "alert"; row: DayRow; detail: AssignDetail };

/**
 * Ajout / transfert manuel depuis le calendrier d'un collaborateur : liste de TOUS les shifts du jour (toutes marques et boutiques),
 * clic sur un shift libre = attribution, clic sur un shift occupé = transfert (confirmation). Les contraintes sont vérifiées par le serveur ;
 * en cas d'alerte, « Accepter quand même » (rôle d'administration, hors règles non dérogeables) ou « Annuler » (planning inchangé).
 */
export function DayShiftsModal({ target, periodId, onClose, onChanged, onCreateNew }: { target: DayTarget; periodId: string; onClose: () => void; onChanged: () => void; onCreateNew: () => void }) {
  const toast = useToast();
  const day = useApi<Day>(target ? `/periods/${periodId}/day-shifts?day=${target.day}&employee_id=${target.emp.id}` : null);
  const [view, setView] = useState<View>({ step: "list" });
  const [busy, setBusy] = useState(false); const [err, setErr] = useState(""); const [reason, setReason] = useState("");
  const cancelRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { setView({ step: "list" }); setErr(""); setReason(""); }, [target]);

  async function submit(row: DayRow, force: boolean) {
    if (!target || busy) return;
    setBusy(true); setErr("");
    try {
      await api(`/periods/${periodId}/manual-assign`, { method: "POST", json: { employee_id: target.emp.id, shift_id: row.shift_id, force, reason: reason.trim() || null, expected_from: row.assigned_to?.id ?? "free" } });
      toast.push(row.status === "assigned" ? `Shift de ${row.assigned_to?.name} transféré à ${target.emp.name}.` : `Shift attribué à ${target.emp.name}.`, force ? "warn" : "ok");
      onChanged();
    } catch (e: unknown) {
      const d = parseDetail(e);
      if (d?.code === "stale") { setView({ step: "list" }); setErr(d.message); day.reload(); }
      else if (d && (d.issues?.length || d.code === "forbidden")) setView({ step: "alert", row, detail: d });
      else setErr(e instanceof Error ? e.message : "Opération impossible");
    } finally { setBusy(false); }
  }
  const pick = (row: DayRow) => { if (row.mine) return; setErr(""); if (row.status === "assigned") setView({ step: "confirm", row }); else void submit(row, false); };

  const rows = sortRows(day.data?.shifts ?? []);
  const name = target?.emp.name ?? "";
  return (
    <Modal open={!!target} onClose={() => !busy && onClose()} title={target ? `Ajouter un jour de travail — ${name}` : ""} description={target ? longDate(target.day) : undefined} initialFocusRef={cancelRef}>
      {target && view.step === "list" && (
        <div className="stack">
          {day.data?.employee_has_shift && <Callout kind="info">{name} travaille déjà ce jour-là ({day.data.employee_has_shift.site}, {hourRange(day.data.employee_has_shift.start, day.data.employee_has_shift.end)}) : un seul shift par jour.</Callout>}
          {day.loading && !day.data ? <p className="muted" role="status">Chargement des shifts du jour…</p> : day.error ? <Callout kind="bad" title="Chargement impossible">{day.error}</Callout> : rows.length === 0 ? (
            <EmptyState title="Aucun shift prévu ce jour-là">Créez un shift avec l&apos;horaire d&apos;une marque autorisée.</EmptyState>
          ) : (
            <ul className="dshift-list" aria-label={`Shifts du ${longDate(target.day)}`}>
              {rows.map((r) => (
                <li key={r.shift_id}>
                  <button type="button" className="dshift" data-status={r.status} disabled={r.mine || busy} aria-label={`${rowLabel(r, name)} : ${r.brands.join(" + ")}, ${r.site}, ${hourRange(r.start, r.end)}`} onClick={() => pick(r)}>
                    <i className="dshift-bar" style={{ ["--c" as string]: brandColor(r.brands[0] ?? r.site) }} />
                    <span className="dshift-main">
                      <strong>{r.brands.length ? r.brands.join(" + ") : r.site}</strong>
                      <span className="muted">{r.site} · <span className="num">{hourRange(r.start, r.end)}</span> · {fmtHM(r.effective_minutes)} effectives</span>
                    </span>
                    <span className="dshift-side">
                      {r.status === "available" ? <Badge tone="ok" icon="check">Disponible</Badge> : <Badge tone={r.mine ? "accent" : "neutral"} icon={r.locked ? "lock" : undefined}>{r.mine ? `Déjà ${name}` : r.assigned_to?.name}</Badge>}
                      {!r.mine && r.issues.some((i) => i.level === "blocking") && <Badge tone="bad" icon="alert">Impossible</Badge>}
                      {!r.mine && !r.issues.some((i) => i.level === "blocking") && r.issues.length > 0 && <Badge tone="warn" icon="alert" title={r.issues.map((i) => i.message).join("\n")}>{r.issues.length} alerte{r.issues.length > 1 ? "s" : ""}</Badge>}
                      {!r.mine && <span className="dshift-go">{r.status === "available" ? "Attribuer" : "Transférer"}</span>}
                    </span>
                  </button>
                </li>))}
            </ul>
          )}
          {err && <Callout kind="bad" title="Opération impossible">{err}</Callout>}
          <div className="row modal-actions"><Button variant="ghost" icon="plus" onClick={onCreateNew} disabled={busy}>Créer un nouveau shift</Button><Button ref={cancelRef} onClick={onClose} disabled={busy}>Fermer</Button></div>
        </div>
      )}
      {target && view.step === "confirm" && (
        <div className="stack">
          <div className="swap" aria-hidden="true">
            <div className="swap-card" data-side="from"><span className="eyebrow">Actuellement</span><strong>{view.row.assigned_to?.name}</strong></div>
            <Icon name="swap" size={20} className="swap-arrow" />
            <div className="swap-card" data-side="to"><span className="eyebrow">Nouveau</span><strong>{name}</strong></div>
          </div>
          <p>Transférer ce shift de <strong>{view.row.assigned_to?.name}</strong> à <strong>{name}</strong> ? Il sera retiré de son planning et ajouté au planning de {name}, avec les mêmes horaires, marque et boutique.</p>
          <dl className="facts">
            <div><dt>Date</dt><dd>{longDate(target.day)}</dd></div>
            <div><dt>Horaires</dt><dd className="num">{hourRange(view.row.start, view.row.end)}</dd></div>
            <div><dt>Boutique</dt><dd>{view.row.site}</dd></div>
            <div><dt>Marque</dt><dd className="row">{view.row.brands.map((b) => <Badge key={b}><i className="dot" style={{ ["--c" as string]: brandColor(b) }} />{b}</Badge>)}</dd></div>
          </dl>
          {view.row.locked && <Callout kind="warn" title="Shift verrouillé">Ce shift est verrouillé : le transfert demandera une autorisation d&apos;administration.</Callout>}
          {err && <Callout kind="bad" title="Opération impossible">{err}</Callout>}
          <div className="row modal-actions">
            <Button onClick={() => setView({ step: "list" })} disabled={busy}>Retour</Button>
            <Button variant="primary" icon="swap" onClick={() => submit(view.row, false)} disabled={busy} aria-busy={busy}>{busy ? "Vérification…" : "Confirmer le transfert"}</Button>
          </div>
        </div>
      )}
      {target && view.step === "alert" && <AlertStep detail={view.detail} name={name} shift={`${view.row.brands.join(" + ") || view.row.site} · ${view.row.site} · ${hourRange(view.row.start, view.row.end)}`} reason={reason} setReason={setReason} busy={busy}
        onCancel={() => { setView({ step: "list" }); setReason(""); }} onAccept={() => submit(view.row, true)} />}
    </Modal>
  );
}

export function AlertStep({ detail, name, shift, reason, setReason, busy, onCancel, onAccept }: { detail: AssignDetail; name: string; shift: string; reason: string; setReason: (s: string) => void; busy: boolean; onCancel: () => void; onAccept: () => void }) {
  const blocking = blockingOf(detail.issues);
  const accept = canAccept(detail);
  return (
    <div className="stack" role="alertdialog" aria-label="Contraintes détectées">
      <p className="help"><strong>{name}</strong> · {shift}</p>
      <Callout kind={blocking.length ? "bad" : "warn"} title={blocking.length ? "Affectation impossible" : (detail.issues ?? []).every((i) => i.level === "soft") ? "Préférence non respectée" : `${detail.issues?.length ?? 0} contrainte${(detail.issues?.length ?? 0) > 1 ? "s" : ""} non respectée${(detail.issues?.length ?? 0) > 1 ? "s" : ""}`} icon="alert">
        <ul className="issue-list">
          {(detail.issues ?? []).map((i) => (
            <li key={i.code + i.message}>
              <strong>{i.rule ?? i.code}</strong>
              {i.legal && <Badge tone="warn">Règle légale ou de référence</Badge>}
              {i.level === "blocking" && <Badge tone="bad">Non dérogeable</Badge>}
              {i.level === "soft" && <Badge tone="info">Préférence</Badge>}
              <span className="issue-msg">{i.message}</span>
              {(i.limit || i.reached) && <dl className="issue-facts">
                {i.limit && <div><dt>Valeur autorisée</dt><dd className="num">{i.limit}</dd></div>}
                {i.reached && <div><dt>Valeur atteinte</dt><dd className="num">{i.reached}</dd></div>}
              </dl>}
              {i.consequence && <span className="help">Conséquence : {i.consequence}</span>}
            </li>))}
          {!detail.issues?.length && <li>{detail.message}</li>}
        </ul>
      </Callout>
      {blocking.length > 0 ? <p className="help">Cette règle ne peut pas être contournée. Annulez : le planning reste inchangé.</p>
        : accept ? <>
          <p className="help">Vous pouvez accepter quand même : l&apos;affectation sera enregistrée, verrouillée et signalée comme dérogation dans l&apos;historique (date, utilisateur, motif).</p>
          <Field label="Motif de la dérogation (facultatif)">{(p) => <Input {...p} value={reason} maxLength={300} placeholder={`Pourquoi affecter ${name} malgré l'alerte ?`} onChange={(e) => setReason(e.target.value)} />}</Field>
        </> : <p className="help">{detail.code === "forbidden" ? detail.message : detail.refusal ?? "Seul un propriétaire, un administrateur ou un manager peut approuver une dérogation."}</p>}
      <div className="row modal-actions">
        <Button onClick={onCancel} disabled={busy} autoFocus>Annuler</Button>
        {accept && <Button variant="primary" icon="check" onClick={onAccept} disabled={busy} aria-busy={busy}>{busy ? "Enregistrement…" : "Accepter quand même"}</Button>}
      </div>
    </div>
  );
}

/** Retrait d'un shift du planning d'un collaborateur (il redevient « disponible »). Verrouillé : autorisation d'administration. */
export function RemoveDialog({ a, onClose, onDone }: { a: { assignment_id: string; employee: string; employee_id?: string; day: string; site: string; start: string; end: string; locked: boolean } | null; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false); const [err, setErr] = useState(""); const cancelRef = useRef<HTMLButtonElement>(null);
  useEffect(() => setErr(""), [a]);
  async function remove() {
    if (!a) return; setBusy(true); setErr("");
    try { await api(`/assignments/${a.assignment_id}?force=${a.locked}${a.employee_id ? `&expected_employee_id=${a.employee_id}` : ""}`, { method: "DELETE" }); toast.push(`Shift retiré du planning de ${a.employee}. Il est de nouveau disponible.`, "ok"); onDone(); }
    catch (e: unknown) { const d = parseDetail(e); setErr(d?.message ?? (e instanceof Error ? e.message : "Retrait impossible")); if (d?.code === "stale" || d?.code === "gone") invalidate("planning"); }
    finally { setBusy(false); }
  }
  return (
    <Modal open={!!a} onClose={() => !busy && onClose()} title="Retirer ce shift ?" hideClose variant="confirm" initialFocusRef={cancelRef}
      description={a ? `${a.employee} · ${longDate(a.day)} · ${a.site}, ${hourRange(a.start, a.end)}` : undefined}>
      {a && (
        <>
          <p>Le shift sera retiré du planning de <strong>{a.employee}</strong> et redeviendra disponible. Les compteurs sont recalculés immédiatement.</p>
          {a.locked && <Callout kind="warn" title="Shift verrouillé">Le retrait demande une autorisation d&apos;administration.</Callout>}
          {err && <Callout kind="bad" title="Retrait impossible">{err}</Callout>}
          <div className="row modal-actions"><Button ref={cancelRef} onClick={onClose} disabled={busy}>Annuler</Button><Button variant="primary" onClick={remove} disabled={busy} aria-busy={busy}>{busy ? "Retrait…" : "Retirer le shift"}</Button></div>
        </>
      )}
    </Modal>
  );
}
