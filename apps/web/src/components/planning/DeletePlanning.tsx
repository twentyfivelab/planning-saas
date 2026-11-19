"use client";
import { useEffect, useState } from "react";
import { Badge, Button, Callout, Field, Input } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError } from "@/lib/api";
import { invalidate } from "@/lib/invalidate";
import { errText } from "@/lib/wfm";

type Preview = { period_id: string; name: string; label: string; status?: string; status_label?: string; assignments: number; locked: number; shifts: number;
  versions: { total: number; published: number; validated: number }; runs: number; time_entries: number; reminders: number; blocking: string[]; can_delete: boolean };

/** Suppression d'un planning généré : aperçu de ce qui est retiré, confirmation par le mot de passe du compte connecté (vérifiée par le
 *  serveur), aucune double soumission. Le mot de passe n'est conservé nulle part : effacé à la fermeture et après chaque envoi. */
export function DeletePlanningModal({ periodId, open, onClose, onDeleted }: { periodId: string; open: boolean; onClose: () => void; onDeleted: (message: string) => void }) {
  const toast = useToast();
  const [pv, setPv] = useState<Preview | null>(null); const [loadErr, setLoadErr] = useState("");
  const [pw, setPw] = useState(""); const [busy, setBusy] = useState(false); const [err, setErr] = useState("");
  useEffect(() => {
    if (!open) { setPw(""); setErr(""); setPv(null); return; }
    setLoadErr("");
    api<Preview>(`/periods/${periodId}/deletion-preview`).then(setPv).catch((e) => setLoadErr(errText(e)));
  }, [open, periodId]);
  const close = () => { if (!busy) { setPw(""); setErr(""); onClose(); } };
  async function confirm() {
    if (busy || !pw) return; // une seule soumission à la fois
    setBusy(true); setErr("");
    const secret = pw; setPw(""); // le mot de passe ne reste pas dans l'écran
    try {
      const r = await api<{ message: string }>(`/periods/${periodId}/delete`, { method: "POST", json: { password: secret } });
      invalidate(); toast.push(r.message, "ok"); onDeleted(r.message);
    } catch (e) {
      const d = e instanceof ApiError ? (e.detail as { code?: string; message?: string } | undefined) : undefined;
      setErr(d?.message ?? errText(e));
    } finally { setBusy(false); }
  }
  const title = pv ? `Supprimer le planning de ${pv.label} ?` : "Supprimer ce planning ?";
  return (
    <Modal open={open} onClose={close} title={title} variant="confirm" description="Ce planning sera retiré des plannings actifs. Cette action sera enregistrée dans l'historique avec votre identité.">
      <div className="stack" data-testid="delete-planning">
        {loadErr && <Callout kind="bad" title="Aperçu indisponible">{loadErr}</Callout>}
        {!pv && !loadErr && <div className="skeleton" style={{ height: "6rem" }} aria-hidden="true" />}
        {pv && <>
          <dl className="facts" data-testid="delete-summary">
            <div><dt>Mois et année</dt><dd>{pv.label.charAt(0).toUpperCase() + pv.label.slice(1)}</dd></div>
            {pv.status_label && <div><dt>Statut</dt><dd>{pv.status_label}</dd></div>}
            <div><dt>Affectations</dt><dd className="num">{pv.assignments}{pv.locked ? ` (dont ${pv.locked} verrouillée${pv.locked > 1 ? "s" : ""})` : ""}</dd></div>
            <div><dt>Shifts</dt><dd className="num">{pv.shifts}</dd></div>
            <div><dt>Versions associées</dt><dd className="num">{pv.versions.total}{pv.versions.published ? ` · ${pv.versions.published} publiée(s)` : ""}{pv.versions.validated ? ` · ${pv.versions.validated} validée(s)` : ""}</dd></div>
            {pv.reminders > 0 && <div><dt>Rappels « À régulariser »</dt><dd className="num">{pv.reminders}</dd></div>}
          </dl>
          <ul className="help" style={{ margin: 0, paddingLeft: "1.1rem" }}>
            <li>Les affectations et shifts sont retirés des vues actives ; une archive est conservée avec le planning supprimé.</li>
            <li>Les versions et les calculs sont conservés pour la traçabilité, mais ne sont plus consultables ni restaurables.{pv.versions.published ? <> <Badge tone="warn">Version publiée</Badge> Les collaborateurs ne la verront plus dans « Mon planning ».</> : null}</li>
            <li>Aucun autre mois, collaborateur ou paramètre n&apos;est modifié, et aucun planning n&apos;est recréé automatiquement.</li>
          </ul>
          {pv.blocking.length > 0 ? <Callout kind="bad" title="Suppression impossible">{pv.blocking.map((b) => <p key={b} style={{ margin: 0 }}>{b}</p>)}</Callout> : (
            <form className="stack" onSubmit={(e) => { e.preventDefault(); void confirm(); }}>
              <Field label="Mot de passe de votre compte" help="Vérifié par le serveur, jamais enregistré.">{(p) => (
                <Input {...p} type="password" autoComplete="current-password" value={pw} disabled={busy} onChange={(e) => { setPw(e.target.value); setErr(""); }} />)}</Field>
              {err && <Callout kind="bad" title="Suppression non effectuée"><span data-testid="delete-error">{err}</span></Callout>}
              <div className="row modal-actions">
                <Button type="button" onClick={close} disabled={busy}>Annuler</Button>
                <Button type="submit" variant="danger" disabled={busy || !pw} aria-busy={busy}>{busy ? "Suppression…" : "Confirmer la suppression"}</Button>
              </div>
            </form>
          )}
          {pv.blocking.length > 0 && <div className="row modal-actions"><Button onClick={close}>Fermer</Button></div>}
        </>}
      </div>
    </Modal>
  );
}

type RecoveryPreview = { period_id: string; name: string; label: string; deleted_at: string | null; deleted_by_name: string | null; archived: number; archived_locked: number;
  blocking: string[]; can_recover: boolean; restorable: number; missing_employees: { day: string; start: string; end: string; site: string; employee: string }[]; missing_shifts: number };

/** Récupération contrôlée d'un planning supprimé : essai à blanc (rien n'est modifié), puis confirmation par mot de passe. Un NOUVEAU
 *  planning est créé pour ce mois à partir de l'archive ; le planning supprimé et la trace de sa suppression restent inchangés. */
export function RecoverPlanningModal({ periodId, open, onClose, onRecovered }: { periodId: string; open: boolean; onClose: () => void; onRecovered: (message: string, newId: string) => void }) {
  const toast = useToast();
  const [pv, setPv] = useState<RecoveryPreview | null>(null); const [loadErr, setLoadErr] = useState("");
  const [pw, setPw] = useState(""); const [busy, setBusy] = useState(false); const [err, setErr] = useState("");
  useEffect(() => {
    if (!open) { setPw(""); setErr(""); setPv(null); return; }
    setLoadErr("");
    api<RecoveryPreview>(`/periods/${periodId}/recovery-preview`).then(setPv).catch((e) => setLoadErr(errText(e)));
  }, [open, periodId]);
  const close = () => { if (!busy) { setPw(""); setErr(""); onClose(); } };
  async function confirm() {
    if (busy || !pw) return;
    setBusy(true); setErr("");
    const secret = pw; setPw("");
    try {
      const r = await api<{ message: string; period_id: string }>(`/periods/${periodId}/recover`, { method: "POST", json: { password: secret } });
      invalidate(); toast.push(r.message, "ok"); onRecovered(r.message, r.period_id);
    } catch (e) {
      const d = e instanceof ApiError ? (e.detail as { message?: string } | undefined) : undefined;
      setErr(d?.message ?? errText(e));
    } finally { setBusy(false); }
  }
  return (
    <Modal open={open} onClose={close} title={pv ? `Récupérer le planning de ${pv.label} ?` : "Récupérer ce planning ?"}
      description="Un nouveau planning est créé pour ce mois à partir de l'archive. Le planning supprimé, son archive et l'historique restent inchangés ; aucun autre mois n'est modifié et rien n'est publié.">
      <div className="stack" data-testid="recover-planning">
        {loadErr && <Callout kind="bad" title="Aperçu indisponible">{loadErr}</Callout>}
        {!pv && !loadErr && <div className="skeleton" style={{ height: "6rem" }} aria-hidden="true" />}
        {pv && <>
          <dl className="facts" data-testid="recover-summary">
            <div><dt>Supprimé</dt><dd>{pv.deleted_at ? new Date(pv.deleted_at).toLocaleString("fr-CH") : "—"}{pv.deleted_by_name ? ` par ${pv.deleted_by_name}` : ""}</dd></div>
            <div><dt>Affectations archivées</dt><dd className="num">{pv.archived}{pv.archived_locked ? ` (dont ${pv.archived_locked} verrouillée(s))` : ""}</dd></div>
            {pv.can_recover && <div><dt>Replacées</dt><dd className="num">{pv.restorable}</dd></div>}
          </dl>
          {pv.missing_employees.length > 0 && <Callout kind="warn" title={`${pv.missing_employees.length} affectation(s) ne seront pas replacées`}>
            Collaborateur introuvable (supprimé depuis) : {pv.missing_employees.slice(0, 5).map((x) => `${x.employee} le ${x.day} ${x.start}–${x.end}`).join(" · ")}{pv.missing_employees.length > 5 ? " …" : ""}. Aucun autre collaborateur n&apos;est affecté à sa place.</Callout>}
          {pv.blocking.length > 0 ? <>
            <Callout kind="bad" title="Récupération impossible">{pv.blocking.map((b) => <p key={b} style={{ margin: 0 }}>{b}</p>)}</Callout>
            <div className="row modal-actions"><Button onClick={close}>Fermer</Button></div>
          </> : (
            <form className="stack" onSubmit={(e) => { e.preventDefault(); void confirm(); }}>
              <Field label="Mot de passe de votre compte" help="Vérifié par le serveur, jamais enregistré.">{(p) => (
                <Input {...p} type="password" autoComplete="current-password" value={pw} disabled={busy} onChange={(e) => { setPw(e.target.value); setErr(""); }} />)}</Field>
              {err && <Callout kind="bad" title="Récupération non effectuée"><span data-testid="recover-error">{err}</span></Callout>}
              <div className="row modal-actions">
                <Button type="button" onClick={close} disabled={busy}>Annuler</Button>
                <Button type="submit" variant="primary" disabled={busy || !pw} aria-busy={busy}>{busy ? "Récupération…" : "Confirmer la récupération"}</Button>
              </div>
            </form>
          )}
        </>}
      </div>
    </Modal>
  );
}
