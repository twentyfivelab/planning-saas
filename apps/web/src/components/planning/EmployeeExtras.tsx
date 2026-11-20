"use client";
import { useEffect, useState } from "react";
import { useMe } from "@/components/Shell";
import { Badge, Button, Callout, Field, Select } from "@/components/ui/primitives";
import { useApi } from "@/components/hooks";
import { api } from "@/lib/api";
import { invalidate } from "@/lib/invalidate";
import { PRESENCE_HELP, PRESENCE_SCOPE, RELATION_LABEL, RELATION_SCOPE, SKILL_CATEGORY, WEEKDAYS, errText } from "@/lib/wfm";

type Skill = { id: string; code: string; name: string; category: string };
type Owned = { code: string; name: string; category: string; valid_until: string | null };
type Pref = { id: string; employee_id: string; kind: string; params: { weekdays?: number[]; sites?: string[]; start?: string; end?: string }; is_hard: boolean };
type Rel = { id: string; employee_id: string; other_employee_id: string; kind: string; strict: boolean; scope?: string };
type Partial = { id: string; employee_id: string; on_date: string; start_time: string; end_time: string; reason: string | null };

/** Fiche collaborateur, suite : qualifications, jours de repos et sites (souples ou stricts), horaires obligatoires, absences sur une
 *  partie de la journée, relations avec d'autres collaborateurs. */
export function EmployeeExtras({ emp, all }: { emp: { id: string; name: string }; all: { id: string; name: string }[] }) {
  const me = useMe();
  const canSkills = me.permissions.includes("employees.write"), canRules = me.permissions.includes("rules.write");
  const catalog = useApi<Skill[]>("/skills");
  const owned = useApi<Owned[]>(`/employees/${emp.id}/skills`);
  const prefs = useApi<Pref[]>("/employee-preferences");
  const rels = useApi<Rel[]>("/relationship-preferences");
  const sites = useApi<{ code: string; name: string }[]>("/sites");
  const partials = useApi<Partial[]>("/partial-absences");
  const [err, setErr] = useState("");
  const [other, setOther] = useState(""); const [kind, setKind] = useState("avoid_together"); const [strict, setStrict] = useState(false); const [scope, setScope] = useState("site_day");
  const [win, setWin] = useState({ start: "", end: "" });
  const [pa, setPa] = useState({ on_date: "", start_time: "", end_time: "", reason: "" });
  useEffect(() => { setErr(""); setOther(""); setPa({ on_date: "", start_time: "", end_time: "", reason: "" }); }, [emp.id]);
  const canAvail = me.permissions.includes("availability.write");
  const run = async (f: () => Promise<unknown>, after: () => void) => { setErr(""); try { await f(); after(); invalidate(); } catch (e) { setErr(errText(e)); } };

  const mine = (k: string, hard: boolean) => prefs.data?.find((p) => p.employee_id === emp.id && p.kind === k && p.is_hard === hard);
  async function setPref(k: "rest_weekdays" | "sites", hard: boolean, values: (string | number)[]) {
    const cur = mine(k, hard);
    const params = k === "rest_weekdays" ? { weekdays: values } : { sites: values };
    await run(async () => {
      if (!values.length) { if (cur) await api(`/employee-preferences/${cur.id}`, { method: "DELETE" }); return; }
      const body = { employee_id: emp.id, kind: k, params, is_hard: hard, strength: 1 };
      if (cur) await api(`/employee-preferences/${cur.id}`, { method: "PUT", json: body }); else await api("/employee-preferences", { method: "POST", json: body });
    }, prefs.reload);
  }
  const toggle = <T,>(arr: T[], v: T, on: boolean) => (on ? [...arr, v] : arr.filter((x) => x !== v));
  const ownedCodes = owned.data?.map((s) => s.code) ?? [];
  const canStrict = kind === "avoid_together" || kind === "mentor";
  const myRels = (rels.data ?? []).filter((r) => r.employee_id === emp.id || r.other_employee_id === emp.id);
  const window_ = mine("work_window", true);
  useEffect(() => { setWin({ start: window_?.params.start ?? "", end: window_?.params.end ?? "" }); }, [window_?.id, window_?.params.start, window_?.params.end]);
  const myPartials = (partials.data ?? []).filter((x) => x.employee_id === emp.id).sort((a, b) => (a.on_date + a.start_time).localeCompare(b.on_date + b.start_time));
  const hhmm = (t: string) => t.slice(0, 5);
  const frDate = (d: string) => d.split("-").reverse().join("/");
  async function saveWindow(clear: boolean) {
    await run(async () => {
      if (clear) { if (window_) await api(`/employee-preferences/${window_.id}`, { method: "DELETE" }); return; }
      const body = { employee_id: emp.id, kind: "work_window", params: { start: win.start, end: win.end }, is_hard: true, strength: 1 };
      if (window_) await api(`/employee-preferences/${window_.id}`, { method: "PUT", json: body }); else await api("/employee-preferences", { method: "POST", json: body });
    }, prefs.reload);
  }
  const nameOf = (id: string) => all.find((e) => e.id === id)?.name ?? "—";

  return (
    <>
      <fieldset className="sheet-section">
        <legend className="h2">Qualifications, langues et certifications</legend>
        <p className="help">Réglage permanent. Le moteur n&apos;affecte jamais une personne à un besoin dont il lui manque une qualification.</p>
        {catalog.data?.length ? (
          <div className="row">{catalog.data.map((s) => (
            <label key={s.id} className="chip-check" title={SKILL_CATEGORY[s.category]}><input type="checkbox" disabled={!canSkills} checked={ownedCodes.includes(s.code)} aria-label={`${s.name} (${SKILL_CATEGORY[s.category] ?? s.category})`}
              onChange={(e) => run(() => api(`/employees/${emp.id}/skills`, { method: "PUT", json: { skills: (e.target.checked ? [...(owned.data ?? []), { code: s.code, valid_until: null }] : (owned.data ?? []).filter((x) => x.code !== s.code)).map((x) => ({ code: x.code, valid_until: x.valid_until })) } }), owned.reload)} /><span>{s.name}</span></label>))}</div>
        ) : <p className="help">Aucune qualification définie : ajoutez-en dans « Clients et missions ».</p>}
      </fieldset>
      <fieldset className="sheet-section">
        <legend className="h2">Jours de repos</legend>
        <p className="help">Réglage permanent. Souhaité : respecté dans la mesure du possible. Obligatoire : jamais de shift ce jour-là.</p>
        {([[false, "Souhaités"], [true, "Obligatoires"]] as const).map(([hard, label]) => {
          const cur = mine("rest_weekdays", hard)?.params.weekdays ?? [];
          return <div key={label} className="row" role="group" aria-label={`Jours de repos ${label.toLowerCase()}`}><span className="label" style={{ minWidth: "6.5rem" }}>{label}</span>{WEEKDAYS.map((d, i) => <label key={d} className="chip-check"><input type="checkbox" disabled={!canRules} checked={cur.includes(i)} onChange={(e) => setPref("rest_weekdays", hard, toggle(cur, i, e.target.checked).sort())} /><span>{d}</span></label>)}</div>;
        })}
      </fieldset>
      <fieldset className="sheet-section">
        <legend className="h2">Sites</legend>
        <p className="help">Préférés : favorisés si possible. Autorisés : si au moins un est coché, jamais d&apos;affectation ailleurs. Rien de coché : tous les sites.</p>
        {([[false, "Préférés"], [true, "Autorisés"]] as const).map(([hard, label]) => {
          const cur = mine("sites", hard)?.params.sites ?? [];
          return <div key={label} className="row" role="group" aria-label={`Sites ${label.toLowerCase()}`}><span className="label" style={{ minWidth: "6.5rem" }}>{label}</span>{(sites.data ?? []).map((s) => <label key={s.code} className="chip-check"><input type="checkbox" disabled={!canRules} checked={cur.includes(s.code)} onChange={(e) => setPref("sites", hard, toggle(cur, s.code, e.target.checked))} /><span>{s.name}</span></label>)}</div>;
        })}
      </fieldset>
      <fieldset className="sheet-section" data-testid="work-window">
        <legend className="h2">Horaires obligatoires</legend>
        <p className="help">Contrainte stricte : chaque shift commence au plus tôt et se termine au plus tard à ces heures, le même jour. Vide : aucune limite.
          Les plannings déjà créés gardent leurs paramètres ; la différence y est seulement signalée.</p>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <Field label="Début au plus tôt">{(p) => <input {...p} className="input" type="time" value={win.start} disabled={!canRules} onChange={(e) => setWin({ ...win, start: e.target.value })} />}</Field>
          <Field label="Fin au plus tard">{(p) => <input {...p} className="input" type="time" value={win.end} disabled={!canRules} onChange={(e) => setWin({ ...win, end: e.target.value })} />}</Field>
          {canRules && <Button disabled={!win.start || !win.end || win.end <= win.start} onClick={() => saveWindow(false)}>Enregistrer</Button>}
          {canRules && window_ && <Button variant="ghost" onClick={() => saveWindow(true)}>Aucune limite</Button>}
        </div>
        {win.start && win.end && win.end <= win.start && <p className="help" role="alert">La fin doit suivre le début.</p>}
      </fieldset>
      <fieldset className="sheet-section" data-testid="partial-absences">
        <legend className="h2">Absences sur une partie de la journée</legend>
        <p className="help">Rendez-vous, formation… Seuls les shifts qui chevauchent ce créneau sont impossibles ; le reste de la journée reste planifiable.</p>
        {myPartials.length > 0 && <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0, gap: "var(--sp-1)" }}>{myPartials.map((x) => (
          <li key={x.id} className="row"><Badge tone="warn">{frDate(x.on_date)} · {hhmm(x.start_time)}–{hhmm(x.end_time)}</Badge>{x.reason && <span className="muted">{x.reason}</span>}
            {canAvail && <Button size="sm" variant="ghost" onClick={() => run(() => api(`/partial-absences/${x.id}`, { method: "DELETE" }), partials.reload)} aria-label={`Retirer l'absence du ${frDate(x.on_date)}`}>Retirer</Button>}</li>))}</ul>}
        {canAvail && (
          <div className="row" style={{ alignItems: "flex-end" }}>
            <Field label="Jour">{(p) => <input {...p} className="input" type="date" value={pa.on_date} onChange={(e) => setPa({ ...pa, on_date: e.target.value })} />}</Field>
            <Field label="De">{(p) => <input {...p} className="input" type="time" value={pa.start_time} onChange={(e) => setPa({ ...pa, start_time: e.target.value })} />}</Field>
            <Field label="À">{(p) => <input {...p} className="input" type="time" value={pa.end_time} onChange={(e) => setPa({ ...pa, end_time: e.target.value })} />}</Field>
            <Field label="Motif (facultatif)">{(p) => <input {...p} className="input" maxLength={200} value={pa.reason} onChange={(e) => setPa({ ...pa, reason: e.target.value })} />}</Field>
            <Button icon="plus" disabled={!pa.on_date || !pa.start_time || !pa.end_time || pa.end_time <= pa.start_time}
              onClick={() => run(() => api("/partial-absences", { method: "POST", json: { employee_id: emp.id, ...pa, reason: pa.reason || null } }), () => { setPa({ on_date: "", start_time: "", end_time: "", reason: "" }); partials.reload(); })}>Ajouter</Button>
          </div>)}
      </fieldset>
      <fieldset className="sheet-section">
        <legend className="h2">Relations avec d&apos;autres collaborateurs</legend>
        <p className="help">Aucun nom n&apos;est inscrit dans le moteur : tout se règle ici.</p>
        {myRels.length > 0 && <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0, gap: "var(--sp-1)" }}>{myRels.map((r) => (
          <li key={r.id} className="row"><Badge tone={r.strict ? "accent" : "neutral"}>{r.strict ? "Stricte" : "Préférence"}</Badge><span>{r.kind === "avoid_together" ? `À séparer (${RELATION_SCOPE[r.scope ?? "site_day"]})` : r.kind === "mentor" || r.kind === "work_together" ? `${RELATION_LABEL[r.kind]} (${PRESENCE_SCOPE[r.scope ?? "site_day"]})` : RELATION_LABEL[r.kind] ?? r.kind} : <strong>{r.employee_id === emp.id ? nameOf(r.other_employee_id) : nameOf(r.employee_id)}</strong></span>
            {canRules && <Button size="sm" variant="ghost" onClick={() => run(() => api(`/relationship-preferences/${r.id}`, { method: "DELETE" }), rels.reload)} aria-label={`Retirer la relation avec ${r.employee_id === emp.id ? nameOf(r.other_employee_id) : nameOf(r.employee_id)}`}>Retirer</Button>}</li>))}</ul>}
        {canRules && (
          <div className="row" style={{ alignItems: "flex-end" }}>
            <Field label="Type de relation">{(p) => <Select {...p} value={kind} onChange={(e) => { setKind(e.target.value); setStrict(false); setScope("site_day"); }}>{Object.entries(RELATION_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select>}</Field>
            {kind === "avoid_together" && <Field label="Portée">{(p) => <Select {...p} value={scope} onChange={(e) => setScope(e.target.value)}>{Object.entries(RELATION_SCOPE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select>}</Field>}
            {(kind === "mentor" || kind === "work_together") && <Field label={kind === "mentor" ? "Présence du tuteur" : "Présence du binôme"} help={PRESENCE_HELP[scope]}>{(p) => <Select {...p} value={scope} onChange={(e) => setScope(e.target.value)}>{Object.entries(PRESENCE_SCOPE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select>}</Field>}
            <Field label="Avec">{(p) => <Select {...p} value={other} onChange={(e) => setOther(e.target.value)}><option value="">Choisir…</option>{all.filter((e) => e.id !== emp.id).map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</Select>}</Field>
            <label className="row"><input type="checkbox" disabled={!canStrict} checked={strict} onChange={(e) => setStrict(e.target.checked)} /> Stricte</label>
            <Button disabled={!other} icon="plus" onClick={() => run(() => api("/relationship-preferences", { method: "POST", json: { employee_id: emp.id, other_employee_id: other, kind, strict, scope: kind === "avoid_together" || kind === "mentor" || kind === "work_together" ? scope : "site_day" } }), () => { setOther(""); setScope("site_day"); rels.reload(); })}>Ajouter</Button>
          </div>)}
      </fieldset>
      {err && <Callout kind="bad" title="Enregistrement impossible">{err}</Callout>}
    </>
  );
}
