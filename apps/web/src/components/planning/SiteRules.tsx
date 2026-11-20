"use client";
import { useEffect, useState } from "react";
import { useApi } from "@/components/hooks";
import { Button, Callout, Card, Field, Select } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { invalidate } from "@/lib/invalidate";
import { errText } from "@/lib/wfm";

type Site = { id: string; code: string; name: string; continuous_presence: boolean; paid_breaks?: boolean; archived_from: string | null };
type Travel = { id: string; from_site: string; to_site: string; minutes: number };

/** Règles entre sites : présence continue (pause sans relève signalée) et temps de déplacement entre deux sites (écart minimal entre deux
 *  shifts d'un même collaborateur, dans les deux sens). Les plannings déjà créés gardent les temps de déplacement de leur création. */
export function SiteRules({ canEdit }: { canEdit: boolean }) {
  const sites = useApi<Site[]>("/sites");
  const travel = useApi<Travel[]>("/site-travel");
  const [err, setErr] = useState("");
  const [f, setF] = useState({ from_site: "", to_site: "", minutes: "" });
  const [pending, setPending] = useState<Record<string, boolean>>({}); // état affiché immédiatement, confirmé par le serveur (annulé en cas d'erreur)
  const list = (sites.data ?? []).filter((s) => !s.archived_from);
  useEffect(() => { // état serveur rechargé : l'affichage provisoire n'est plus nécessaire
    setPending((x) => Object.fromEntries(Object.entries(x).filter(([id, on]) => sites.data?.find((s) => s.id === id)?.continuous_presence !== on)));
  }, [sites.data]);
  const [paidPending, setPaidPending] = useState<Record<string, boolean>>({});
  useEffect(() => { setPaidPending((x) => Object.fromEntries(Object.entries(x).filter(([id, on]) => !!sites.data?.find((s) => s.id === id)?.paid_breaks !== on))); }, [sites.data]);
  async function togglePaid(s: Site, on: boolean) {
    setPaidPending((x) => ({ ...x, [s.id]: on })); setErr("");
    try { await api(`/sites/${s.id}`, { method: "PUT", json: { code: s.code, name: s.name, paid_breaks: on } }); sites.reload(); invalidate(); }
    catch (e) { setPaidPending((x) => Object.fromEntries(Object.entries(x).filter(([id]) => id !== s.id))); setErr(errText(e)); }
  }
  async function togglePresence(s: Site, on: boolean) {
    setPending((x) => ({ ...x, [s.id]: on })); setErr("");
    try { await api(`/sites/${s.id}`, { method: "PUT", json: { code: s.code, name: s.name, continuous_presence: on } }); sites.reload(); invalidate(); }
    catch (e) { setPending((x) => Object.fromEntries(Object.entries(x).filter(([id]) => id !== s.id))); setErr(errText(e)); }
  }
  const nameOf = (c: string) => list.find((s) => s.code === c)?.name ?? c;
  const run = async (fn: () => Promise<unknown>, after: () => void) => { setErr(""); try { await fn(); after(); invalidate(); } catch (e) { setErr(errText(e)); } };
  const exists = (travel.data ?? []).some((t) => (t.from_site === f.from_site && t.to_site === f.to_site) || (t.from_site === f.to_site && t.to_site === f.from_site));
  const minutes = Number(f.minutes);
  const valid = f.from_site && f.to_site && f.from_site !== f.to_site && f.minutes !== "" && Number.isInteger(minutes) && minutes >= 0 && minutes <= 600 && !exists;

  return (
    <Card title="Présence continue, pauses payées et déplacements" eyebrow="Règles des sites">
      <div className="stack" data-testid="site-rules">
        <fieldset className="sheet-section">
          <legend className="h2">Présence continue</legend>
          <p className="help">Site coché : chaque pause doit pouvoir être prise pendant qu&apos;une autre personne est présente. Sinon, une alerte « pause sans relève » apparaît dans les alertes du planning (aucun blocage).</p>
          <div className="row">{list.map((s) => (
            <label key={s.id} className="chip-check"><input type="checkbox" disabled={!canEdit} checked={pending[s.id] ?? s.continuous_presence}
              onChange={(e) => togglePresence(s, e.target.checked)} /><span>{s.name}</span></label>))}</div>
        </fieldset>
        <fieldset className="sheet-section" data-testid="paid-breaks">
          <legend className="h2">Pauses payées</legend>
          <p className="help">Site coché : la pause est rémunérée. Les compteurs et les exports distinguent alors les <strong>heures payées</strong> (travail effectif + pauses payées) du <strong>travail effectif</strong>, qui reste la base du plafond mensuel et des règles. Le réglage s&apos;applique aux shifts attribués à partir de maintenant : les heures déjà enregistrées ne changent pas.</p>
          <div className="row">{list.map((s) => (
            <label key={s.id} className="chip-check"><input type="checkbox" disabled={!canEdit} checked={paidPending[s.id] ?? !!s.paid_breaks}
              onChange={(e) => togglePaid(s, e.target.checked)} /><span>{s.name}</span></label>))}</div>
        </fieldset>
        <fieldset className="sheet-section">
          <legend className="h2">Temps de déplacement</legend>
          <p className="help">Écart minimal entre deux shifts d&apos;un même collaborateur sur ces deux sites (dans les deux sens). Le repos quotidien s&apos;applique toujours : l&apos;écart exigé est le plus grand des deux. Les plannings déjà créés gardent les temps de leur création.</p>
          {(travel.data ?? []).length > 0 ? (
            <div className="table-wrap"><table className="table table-cards">
              <thead><tr><th>Sites</th><th>Temps</th><th><span className="sr-only">Actions</span></th></tr></thead>
              <tbody>{(travel.data ?? []).map((t) => (
                <tr key={t.id}><td className="cell-main" data-label="Sites">{nameOf(t.from_site)} ↔ {nameOf(t.to_site)}</td><td data-label="Temps" className="num">{t.minutes} min</td>
                  <td>{canEdit && <Button size="sm" variant="ghost" aria-label={`Retirer le temps entre ${nameOf(t.from_site)} et ${nameOf(t.to_site)}`} onClick={() => run(() => api(`/site-travel/${t.id}`, { method: "DELETE" }), travel.reload)}>Retirer</Button>}</td></tr>))}</tbody>
            </table></div>
          ) : <p className="muted">Aucun temps de déplacement : deux shifts sur des sites différents ne sont séparés que par le repos quotidien.</p>}
          {canEdit && (
            <div className="row" style={{ alignItems: "flex-end" }}>
              <Field label="De">{(p) => <Select {...p} value={f.from_site} onChange={(e) => setF({ ...f, from_site: e.target.value })}><option value="">Choisir…</option>{list.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}</Select>}</Field>
              <Field label="À">{(p) => <Select {...p} value={f.to_site} onChange={(e) => setF({ ...f, to_site: e.target.value })}><option value="">Choisir…</option>{list.filter((s) => s.code !== f.from_site).map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}</Select>}</Field>
              <Field label="Minutes">{(p) => <input {...p} className="input" type="number" min={0} max={600} step={5} value={f.minutes} onChange={(e) => setF({ ...f, minutes: e.target.value })} style={{ width: "7rem" }} />}</Field>
              <Button icon="plus" disabled={!valid} onClick={() => run(() => api("/site-travel", { method: "POST", json: { from_site: f.from_site, to_site: f.to_site, minutes } }), () => { setF({ from_site: "", to_site: "", minutes: "" }); travel.reload(); })}>Ajouter</Button>
            </div>)}
          {exists && <p className="help" role="alert">Un temps existe déjà pour ces deux sites : retirez-le pour le modifier.</p>}
        </fieldset>
        {err && <Callout kind="bad" title="Enregistrement impossible">{err}</Callout>}
      </div>
    </Card>
  );
}
