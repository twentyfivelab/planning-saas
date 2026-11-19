"use client";
import { FormEvent, useEffect, useState } from "react";
import { useApi } from "@/components/hooks";
import { Badge, Button, Callout, Field, Input, Select } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";
import { api, ApiError } from "@/lib/api";
import { brandColor } from "@/lib/brand";
import { LEVELS, LEVEL_LABEL, type BrandRow, type Level } from "@/lib/brandGroups";
import { NO_PREF, TIME_PREF_HELP, TIME_PREF_LABEL, parseNum, validateDays, type TimePref } from "@/lib/employeeRules";
import { errText } from "@/lib/wfm";

const DAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"];
type Site = { id: string; code: string; name: string; archived_from?: string | null };
type Match = { id: string; name: string; reasons: string[]; strong: boolean; deleted: boolean };
type Dup = { message: string; can_confirm: boolean; matches: Match[] };
export type IdentityData = { first_name: string; last_name: string; birth_date: string; address_street: string; address_postal_code: string; address_city: string; address_country: string; phone: string; email: string };
const EMPTY: IdentityData = { first_name: "", last_name: "", birth_date: "", address_street: "", address_postal_code: "", address_city: "", address_country: "", phone: "", email: "" };
const nul = (v: string) => (v.trim() === "" ? null : v.trim());

function IdentityFields({ v, set }: { v: IdentityData; set: (p: Partial<IdentityData>) => void }) {
  return (
    <>
      <fieldset className="sheet-section">
        <legend className="h2">Identité</legend>
        <div className="sheet-pair">
          <Field label="Prénom *">{(p) => <Input {...p} name="first_name" required maxLength={100} autoComplete="off" value={v.first_name} onChange={(e) => set({ first_name: e.target.value })} />}</Field>
          <Field label="Nom *">{(p) => <Input {...p} name="last_name" required maxLength={100} autoComplete="off" value={v.last_name} onChange={(e) => set({ last_name: e.target.value })} />}</Field>
        </div>
        <Field label="Date de naissance">{(p) => <Input {...p} name="birth_date" type="date" value={v.birth_date} onChange={(e) => set({ birth_date: e.target.value })} style={{ maxWidth: "12rem" }} />}</Field>
      </fieldset>
      <fieldset className="sheet-section">
        <legend className="h2">Adresse et contact</legend>
        <Field label="Rue et numéro">{(p) => <Input {...p} name="address_street" maxLength={200} value={v.address_street} onChange={(e) => set({ address_street: e.target.value })} />}</Field>
        <div className="grid-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(9rem, 1fr))" }}>
          <Field label="Code postal">{(p) => <Input {...p} name="address_postal_code" maxLength={16} value={v.address_postal_code} onChange={(e) => set({ address_postal_code: e.target.value })} />}</Field>
          <Field label="Ville">{(p) => <Input {...p} name="address_city" maxLength={100} value={v.address_city} onChange={(e) => set({ address_city: e.target.value })} />}</Field>
          <Field label="Pays">{(p) => <Input {...p} name="address_country" maxLength={100} value={v.address_country} onChange={(e) => set({ address_country: e.target.value })} />}</Field>
        </div>
        <div className="sheet-pair">
          <Field label="Téléphone">{(p) => <Input {...p} name="phone" type="tel" maxLength={32} value={v.phone} onChange={(e) => set({ phone: e.target.value })} />}</Field>
          <Field label="E-mail">{(p) => <Input {...p} name="email" type="email" maxLength={200} value={v.email} onChange={(e) => set({ email: e.target.value })} />}</Field>
        </div>
      </fieldset>
    </>
  );
}

function DupBox({ dup, onConfirm, onRestore, busy }: { dup: Dup; onConfirm: () => void; onRestore: (m: Match) => void; busy: boolean }) {
  return (
    <Callout kind="warn" title="Doublon possible">
      <p style={{ margin: 0 }}>{dup.message}</p>
      <ul style={{ margin: "var(--sp-1) 0", paddingLeft: "1.1rem" }} data-testid="duplicate-matches">{dup.matches.map((m) => (
        <li key={m.id}><strong>{m.name}</strong>{m.deleted ? " (supprimé)" : ""} : {m.reasons.join(", ")} {m.deleted && <Button size="sm" disabled={busy} onClick={() => onRestore(m)}>Réintégrer {m.name}</Button>}</li>))}</ul>
      {dup.can_confirm ? <Button disabled={busy} onClick={onConfirm}>Il s&apos;agit d&apos;une autre personne : ajouter quand même</Button>
        : <p className="help" style={{ margin: 0 }}>Même e-mail ou même téléphone : l&apos;ajout est refusé. Vérifiez la fiche existante.</p>}
    </Callout>
  );
}

/** Fiche d'ajout complète, à monter à chaque ouverture (`{open && <EmployeeAddModal open … />}`). Après un enregistrement réussi,
 *  seul le message de confirmation du serveur est affiché. */
export function EmployeeAddModal({ open, onClose, onAdded, capLabel }: { open: boolean; onClose: () => void; onAdded: (message: string, created?: { id: string; name: string }) => void; capLabel?: string | null }) {
  const brands = useApi<(BrandRow & { archived_from?: string | null })[]>(open ? "/brands" : null);
  const sites = useApi<Site[]>(open ? "/sites" : null);
  const [id, setId] = useState<IdentityData>(EMPTY);
  const [monthly, setMonthly] = useState(""); const [weekly, setWeekly] = useState("");
  const [chosen, setChosen] = useState<Record<string, Level>>({});
  const [siteSel, setSiteSel] = useState<string[]>([]);
  const [avail, setAvail] = useState<number[]>([]); const [unavail, setUnavail] = useState<number[]>([]);
  const [dates, setDates] = useState<string[]>([]); const [newDate, setNewDate] = useState("");
  const [pref, setPref] = useState<TimePref | null>(null); const [strict, setStrict] = useState(false);
  const [minD, setMinD] = useState<number | null>(null); const [maxD, setMaxD] = useState<number | null>(null);
  const [err, setErr] = useState(""); const [dup, setDup] = useState<Dup | null>(null); const [busy, setBusy] = useState(false);
  // état vierge : la fenêtre est montée à chaque ouverture (aucune réinitialisation différée qui effacerait une saisie en cours)
  const toggle = (arr: number[], d: number) => (arr.includes(d) ? arr.filter((x) => x !== d) : [...arr, d].sort());
  const clientErrors = [
    ...(id.first_name.trim() && id.last_name.trim() ? [] : ["Le prénom et le nom sont obligatoires."]),
    ...validateDays(minD, maxD, 31),
    ...avail.filter((d) => unavail.includes(d)).map((d) => `${DAYS[d]} : à la fois disponible et indisponible.`),
  ];

  async function submit(confirm = false) {
    if (clientErrors.length) { setErr(clientErrors.join(" ")); return; }
    setBusy(true); setErr("");
    try {
      const body = {
        first_name: id.first_name.trim(), last_name: id.last_name.trim(), birth_date: id.birth_date || null,
        address_street: nul(id.address_street), address_postal_code: nul(id.address_postal_code), address_city: nul(id.address_city), address_country: nul(id.address_country),
        phone: nul(id.phone), email: nul(id.email),
        monthly_hours: monthly === "" ? null : Number(monthly), weekly_hours: weekly === "" ? null : Number(weekly),
        brands: chosen, sites: siteSel, available_weekdays: avail, unavailable_weekdays: unavail, unavailable_dates: dates,
        time_pref: pref, time_pref_strict: !!pref && strict, min_days_month: minD, max_days_month: maxD, confirm_duplicate: confirm,
      };
      const r = await api<{ message: string; id: string; name: string }>("/employees/onboard", { method: "POST", json: body });
      onAdded(r.message, { id: r.id, name: r.name });
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && typeof e.detail === "object" && (e.detail as { code?: string })?.code === "duplicate") setDup(e.detail as Dup);
      else setErr(errText(e));
    } finally { setBusy(false); }
  }
  async function restore(m: Match) {
    setBusy(true);
    try { const r = await api<{ message: string }>(`/employees/${m.id}/restore`, { method: "POST" }); onAdded(r.message); }
    catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  const activeBrands = (brands.data ?? []).filter((b) => !b.archived_from);
  return (
    <Modal open={open} onClose={() => !busy && onClose()} title="Ajouter un collaborateur" description="Les champs marqués * sont obligatoires. Ce qui n'est pas connu reste vide : rien n'est supposé.">
      <form className="stack" style={{ gap: "var(--sp-4)" }} onSubmit={(e: FormEvent) => { e.preventDefault(); void submit(false); }} data-testid="employee-add-form">
        <IdentityFields v={id} set={(p) => { setId({ ...id, ...p }); setDup(null); }} />
        <fieldset className="sheet-section">
          <legend className="h2">Volume horaire contractuel</legend>
          <div className="sheet-pair">
            <Field label="Heures par mois" help="Objectif du contrat, utilisé par le moteur">{(p) => <Input {...p} name="monthly_hours" type="number" min={0} max={744} step="any" value={monthly} onChange={(e) => setMonthly(e.target.value)} />}</Field>
            <Field label="Heures par semaine" help="Enregistré au contrat">{(p) => <Input {...p} name="weekly_hours" type="number" min={0} max={168} step="any" value={weekly} onChange={(e) => setWeekly(e.target.value)} />}</Field>
          </div>
          {capLabel && <p className="help">Plafond de l&apos;entreprise : {capLabel} de travail effectif par mois, tous sites et marques cumulés.</p>}
        </fieldset>
        <fieldset className="sheet-section">
          <legend className="h2">Marques et sites autorisés</legend>
          <div className="stack" style={{ gap: "var(--sp-1)" }}>{activeBrands.map((b) => (
            <div key={b.code} className="row">
              <label className="row"><input type="checkbox" checked={b.code in chosen} onChange={(e) => { const n = { ...chosen }; if (e.target.checked) n[b.code] = "priority"; else delete n[b.code]; setChosen(n); }} /><i className="dot" style={{ ["--c" as string]: brandColor(b.code) }} />{b.name}</label>
              {b.code in chosen && <select className="select" aria-label={`Priorité ${b.name}`} value={chosen[b.code]} onChange={(e) => setChosen({ ...chosen, [b.code]: e.target.value as Level })}>{LEVELS.map((l) => <option key={l} value={l}>{LEVEL_LABEL[l]}</option>)}</select>}
            </div>))}
            {!activeBrands.length && <p className="help">Aucune marque définie.</p>}
          </div>
          {Object.keys(chosen).length === 0 && <p className="help">Aucune marque cochée : aucun shift ne pourra lui être attribué tant qu&apos;une marque n&apos;est pas autorisée.</p>}
          <p className="label" style={{ marginTop: "var(--sp-2)" }}>Sites autorisés</p>
          <div className="row">{(sites.data ?? []).filter((x) => !x.archived_from).map((x) => (
            <label key={x.code} className="row"><input type="checkbox" checked={siteSel.includes(x.code)} onChange={() => setSiteSel(siteSel.includes(x.code) ? siteSel.filter((c) => c !== x.code) : [...siteSel, x.code])} />{x.name}</label>))}</div>
          <p className="help">Aucun site coché : tous les sites de ses marques autorisées.</p>
        </fieldset>
        <fieldset className="sheet-section">
          <legend className="h2">Disponibilités et indisponibilités</legend>
          <p className="label">Jours de disponibilité</p>
          <div className="row">{DAYS.map((n, i) => <label key={n} className="row"><input type="checkbox" checked={avail.includes(i)} onChange={() => setAvail(toggle(avail, i))} />{n}</label>)}</div>
          <p className="help">Aucun jour coché : disponible tous les jours (hors indisponibilités).</p>
          <p className="label">Indisponible chaque semaine</p>
          <div className="row">{DAYS.map((n, i) => <label key={n} className="row"><input type="checkbox" checked={unavail.includes(i)} onChange={() => setUnavail(toggle(unavail, i))} />{n}</label>)}</div>
          <p className="label">Dates d&apos;indisponibilité</p>
          <div className="row" style={{ alignItems: "flex-end" }}>
            <Field label="Date">{(p) => <Input {...p} type="date" value={newDate} onChange={(e) => setNewDate(e.target.value)} />}</Field>
            <Button disabled={!newDate || dates.includes(newDate)} onClick={() => { setDates([...dates, newDate].sort()); setNewDate(""); }}>Ajouter la date</Button>
          </div>
          {dates.length > 0 && <ul className="row" style={{ listStyle: "none", padding: 0, margin: 0 }}>{dates.map((d) => <li key={d}><Badge>{d.split("-").reverse().join("/")} <button type="button" className="link-btn" aria-label={`Retirer le ${d}`} onClick={() => setDates(dates.filter((x) => x !== d))}>×</button></Badge></li>)}</ul>}
        </fieldset>
        <fieldset className="sheet-section">
          <legend className="h2">Préférences horaires</legend>
          <div className="sheet-pair">
            <Field label="Préférence horaire" help={pref ? TIME_PREF_HELP[pref] : "Tous les horaires autorisés sont possibles."}>{(p) => (
              <Select {...p} value={pref ?? NO_PREF} onChange={(e) => { const v = (e.target.value || null) as TimePref | null; setPref(v); if (!v) setStrict(false); }}>
                <option value={NO_PREF}>Pas de préférence</option>
                {(Object.keys(TIME_PREF_LABEL) as TimePref[]).map((k) => <option key={k} value={k}>{TIME_PREF_LABEL[k]}</option>)}
              </Select>)}</Field>
            <div role="radiogroup" aria-label="Nature de la préférence horaire" className="radio-col">
              <label className="row"><input type="radio" name="add-strict" disabled={!pref} checked={!strict} onChange={() => setStrict(false)} /> Souple <span className="faint">— dans la mesure du possible</span></label>
              <label className="row"><input type="radio" name="add-strict" disabled={!pref} checked={strict} onChange={() => setStrict(true)} /> Stricte <span className="faint">— obligatoire</span></label>
            </div>
          </div>
        </fieldset>
        <fieldset className="sheet-section">
          <legend className="h2">Jours travaillés par mois</legend>
          <div className="sheet-pair sheet-pair-end">
            <Field label="Minimum de jours par mois">{(p) => <Select {...p} value={minD === null ? NO_PREF : String(minD)} onChange={(e) => setMinD(parseNum(e.target.value))}><option value={NO_PREF}>Pas de préférence</option>{Array.from({ length: 31 }, (_, i) => i + 1).map((n) => <option key={n} value={n}>{n}</option>)}</Select>}</Field>
            <Field label="Maximum de jours par mois">{(p) => <Select {...p} value={maxD === null ? NO_PREF : String(maxD)} onChange={(e) => setMaxD(parseNum(e.target.value))}><option value={NO_PREF}>Pas de préférence</option>{Array.from({ length: 31 }, (_, i) => i + 1).map((n) => <option key={n} value={n}>{n}</option>)}</Select>}</Field>
          </div>
          <p className="help">Deux limites obligatoires et indépendantes ; une journée compte une seule fois, même avec plusieurs affectations. « Pas de préférence » désactive seulement la limite correspondante{capLabel ? ` ; le plafond de ${capLabel} par mois reste appliqué` : ""}. Une combinaison impossible bloque la génération, avec la raison.</p>
        </fieldset>
        {dup && <DupBox dup={dup} busy={busy} onConfirm={() => void submit(true)} onRestore={restore} />}
        {(err || (clientErrors.length > 0 && (id.first_name || id.last_name))) && <Callout kind="bad" title="Ajout impossible">{err || clientErrors.join(" ")}</Callout>}
        <div className="row modal-actions"><Button onClick={onClose} disabled={busy}>Annuler</Button><Button type="submit" variant="primary" disabled={busy} aria-busy={busy}>{busy ? "Vérification…" : "Ajouter le collaborateur"}</Button></div>
      </form>
    </Modal>
  );
}

/** Nom, prénom et coordonnées d'un collaborateur existant (le nom affiché devient « Prénom Nom »). */
export function EmployeeIdentityModal({ employeeId, onClose, onSaved }: { employeeId: string | null; onClose: () => void; onSaved: (name: string) => void }) {
  const [v, setV] = useState<IdentityData | null>(null); const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  const [shown, setShown] = useState<{ name: string; unknown: boolean } | null>(null);
  useEffect(() => {
    if (!employeeId) return;
    setV(null); setErr("");
    api<Record<string, string | boolean | null>>(`/employees/${employeeId}/identity`).then((r) => {
      setShown({ name: String(r.name ?? ""), unknown: !!r.split_unknown });
      setV(Object.fromEntries(Object.keys(EMPTY).map((k) => [k, (r[k] as string | null) ?? ""])) as IdentityData);
    }).catch((e) => setErr(errText(e)));
  }, [employeeId]);
  async function save(e: FormEvent) {
    e.preventDefault(); if (!v) return;
    if (!v.first_name.trim() || !v.last_name.trim()) { setErr("Le prénom et le nom sont obligatoires."); return; }
    setBusy(true); setErr("");
    try {
      const r = await api<{ name: string }>(`/employees/${employeeId}/identity`, { method: "PUT", json: {
        first_name: v.first_name.trim(), last_name: v.last_name.trim(), birth_date: v.birth_date || null, address_street: nul(v.address_street), address_postal_code: nul(v.address_postal_code),
        address_city: nul(v.address_city), address_country: nul(v.address_country), phone: nul(v.phone), email: nul(v.email) } });
      onSaved(r.name);
    } catch (x) { setErr(errText(x)); } finally { setBusy(false); }
  }
  return (
    <Modal open={!!employeeId} onClose={() => !busy && onClose()} title="Identité et coordonnées" description="Nom et prénom dans deux champs distincts ; le nom affiché dans les plannings devient « Prénom Nom ».">
      {!v ? (err ? <Callout kind="bad">{err}</Callout> : <div className="skeleton" style={{ height: "12rem" }} aria-hidden="true" />) : (
        <form className="stack" onSubmit={save}>
          {shown?.unknown && <Callout kind="info" title="Prénom et nom à compléter">Nom affiché actuellement : <strong>{shown.name}</strong>. La répartition entre prénom et nom n&apos;a pas été confirmée : elle n&apos;est pas déduite. Le nom affiché reste inchangé tant que vous ne saisissez pas les deux champs.</Callout>}
          <IdentityFields v={v} set={(p) => setV({ ...v, ...p })} />
          {err && <Callout kind="bad" title="Enregistrement impossible">{err}</Callout>}
          <div className="row modal-actions"><Button onClick={onClose} disabled={busy}>Annuler</Button><Button type="submit" variant="primary" disabled={busy}>Enregistrer</Button></div>
        </form>
      )}
    </Modal>
  );
}
