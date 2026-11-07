"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, Button, Callout, Field, Select } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";
import { UnavailabilityCalendar } from "./UnavailabilityCalendar";
import { EmployeeExtras } from "./EmployeeExtras";
import { SundayCounter } from "./SundayCounter";
import { useApi } from "@/components/hooks";
import { api } from "@/lib/api";
import { brandColor } from "@/lib/brand";
import { LEVELS, LEVEL_LABEL, groupBrands, setBrand, setGroup, type BrandRow, type Level } from "@/lib/brandGroups";
import { invalidate } from "@/lib/invalidate";
import { computeCounter, type SundayEmployee, type SundaySummary } from "@/lib/sundays";
import {
  NO_PREF, PERIOD_LABEL, TIME_PREF_HELP, TIME_PREF_LABEL, dayCountOptions, parseNum, sundayOptions, validateDraft,
  type MaxDaysPeriod, type RulesDraft, type TimePref,
} from "@/lib/employeeRules";

export type FicheDraft = RulesDraft & { brands: Record<string, string> };
export type SheetEmployee = { id: string; code: string; name: string; brands: Record<string, string> } & RulesDraft;
type Status = "idle" | "saving" | "saved" | "error";
type Schedules = Record<string, { start: string; end: string }[]>;
type Availability = { dates: string[]; weekdays: number[]; leaves: { start: string; end: string }[] };
const hr = (s: string) => `${s.slice(0, 2)}h${s.slice(3, 5) === "00" ? "" : s.slice(3, 5)}`;

/**
 * Fiche individuelle : jours maximum, préférence horaire, dimanches, marques/boutiques autorisées (avec priorité) et calendrier
 * d'indisponibilités. TOUT est enregistré automatiquement (dès que les valeurs sont cohérentes) et recalcule les compteurs.
 */
export type MonthException = { set: boolean; count: number | null; period: MaxDaysPeriod | null };
type Impact = { periods: { period_id: string; name: string; status: string; hard: number; soft: number }[] };

export function EmployeeSheet({ emp, all, summary, periodDays, period, monthLabel, monthExc, onMonthExc, onOpenPeriod, onClose, onSave }: {
  emp: SheetEmployee | null; all: SheetEmployee[]; summary: SundaySummary | null; periodDays: number; period: { start_date: string; end_date: string } | null; monthLabel?: string;
  /** exception du mois sur le nombre maximum de jours (sinon : valeur habituelle) */
  monthExc?: MonthException; onMonthExc?: (v: MonthException) => Promise<boolean>; onOpenPeriod?: (periodId: string) => void;
  onClose: () => void; onSave: (e: SheetEmployee, d: FicheDraft) => Promise<boolean>;
}) {
  const [exc, setExc] = useState<MonthException | null>(null);
  const [excStatus, setExcStatus] = useState<Status>("idle");
  const [impact, setImpact] = useState<Impact["periods"]>([]);
  const excTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [d, setD] = useState<FicheDraft | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [datesStatus, setDatesStatus] = useState<Status>("idle");
  const [avail, setAvail] = useState<Availability | null>(null);
  const saved = useRef<string>("");
  const brandRows = useApi<BrandRow[]>("/brands");
  const schedules = useApi<Schedules>("/brand-schedules");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const dateTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    if (!emp) return;
    const init: FicheDraft = { max_days_count: emp.max_days_count, max_days_period: emp.max_days_period, time_pref: emp.time_pref, time_pref_strict: emp.time_pref_strict, sunday_quota: emp.sunday_quota, sunday_mode: emp.sunday_mode, brands: emp.brands ?? {} };
    saved.current = JSON.stringify(init); setD(init); setStatus("idle"); setDatesStatus("idle"); setAvail(null); setImpact([]); setExcStatus("idle");
    setExc(monthExc ?? null);
    api<Availability>(`/employees/${emp.id}/availability`).then(setAvail).catch(() => setAvail({ dates: [], weekdays: [], leaves: [] }));
  }, [emp]); // eslint-disable-line react-hooks/exhaustive-deps -- réinitialisé à l'ouverture d'une fiche uniquement

  const nSun = summary?.sundays.length ?? 5;
  const errors = d ? validateDraft(d, nSun, periodDays) : [];
  const key = d ? JSON.stringify(d) : "";
  // enregistrement automatique des paramètres (après 500 ms sans modification, si cohérents)
  useEffect(() => {
    if (!emp || !d || key === saved.current || errors.length) return;
    clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      setStatus("saving");
      const permanentChanged = (() => { try { const b = JSON.parse(saved.current); return JSON.stringify([b.brands, b.time_pref, b.time_pref_strict, b.max_days_count, b.max_days_period]) !== JSON.stringify([d.brands, d.time_pref, d.time_pref_strict, d.max_days_count, d.max_days_period]); } catch { return false; } })();
      const ok = await onSave(emp, d);
      if (ok) { saved.current = key; setStatus("saved"); } else setStatus("error");
      // paramètre PERMANENT modifié : signaler les plannings déjà créés devenus incompatibles (aucune modification automatique)
      if (ok && permanentChanged) api<Impact>(`/employees/${emp.id}/impact`).then((r) => setImpact(r.periods)).catch(() => {});
    }, 500);
    return () => clearTimeout(timer.current);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, emp]);

  const projected = useMemo(() => {
    if (!summary || !emp || !d) return null;
    const list: SundayEmployee[] = all.map((e) => (e.id === emp.id ? { code: e.code, sunday_quota: d.sunday_quota, sunday_mode: d.sunday_mode } : { code: e.code, sunday_quota: e.sunday_quota, sunday_mode: e.sunday_mode }));
    return computeCounter(summary, list);
  }, [summary, emp, d, all]);
  const groups = useMemo(() => groupBrands((brandRows.data ?? []).filter((b) => !(b as { archived_from?: string | null }).archived_from || (emp?.brands ?? {})[b.code] !== undefined)), [brandRows.data, emp]);

  if (!emp || !d) return <Modal open={false} onClose={onClose} title="">{null}</Modal>;
  const excErrors = exc && exc.set && ((exc.count === null) !== (exc.period === null)) ? ["Exception du mois : choisissez à la fois le nombre de jours et la période."] : [];
  function changeExc(v: MonthException) {
    setExc(v); setExcStatus("saving");
    clearTimeout(excTimer.current);
    if (v.set && (v.count === null) !== (v.period === null)) { setExcStatus("idle"); return; }
    excTimer.current = setTimeout(async () => { const ok = onMonthExc ? await onMonthExc(v) : false; setExcStatus(ok ? "saved" : "error"); }, 400);
  }
  const set = (p: Partial<FicheDraft>) => { setD({ ...d, ...p }); setStatus("idle"); };

  function saveDates(next: string[]) {
    setAvail((a) => (a ? { ...a, dates: next } : a)); setDatesStatus("saving");
    clearTimeout(dateTimer.current);
    dateTimer.current = setTimeout(async () => {
      try { await api(`/employees/${emp!.id}/unavailable-dates`, { method: "PUT", json: { dates: next } }); setDatesStatus("saved"); invalidate(); }
      catch { setDatesStatus("error"); }
    }, 300);
  }
  const chosen = Object.keys(d.brands);
  const overall = status === "saving" || datesStatus === "saving" || excStatus === "saving" ? "Enregistrement…" : status === "error" || datesStatus === "error" || excStatus === "error" ? "Échec de l'enregistrement" : errors.length || excErrors.length ? "Corrigez les paramètres pour enregistrer" : status === "saved" || datesStatus === "saved" || excStatus === "saved" ? "Enregistré automatiquement" : "Les modifications sont enregistrées automatiquement";

  return (
    <Modal open onClose={onClose} hideClose title={`Fiche — ${emp.name}`} description="« Pas de préférence » = aucune limite : rien n'est supposé. Tout est enregistré automatiquement.">
      <div className="stack" style={{ gap: "var(--sp-4)" }}>
        <p className="help" role="status" aria-live="polite"><Badge tone={status === "error" || datesStatus === "error" ? "bad" : errors.length ? "warn" : "ok"} icon={overall.startsWith("Enregistré") ? "check" : "info"}>{overall}</Badge></p>

        <fieldset className="sheet-section">
          <legend className="h2">Marques et boutiques autorisées</legend>
          <p className="help">Réglage permanent (tous les mois). Une marque non cochée n&apos;est jamais attribuée à ce collaborateur. Priorité : prioritaire, secondaire ou renfort (utilisé seulement si nécessaire).</p>
          <div className="brand-groups">
            {groups.map((g) => {
              const on = g.brands.filter((b) => b.code in d.brands).length;
              return (
                <div key={g.key} className="brand-group">
                  <label className="row brand-head">
                    <input type="checkbox" checked={on === g.brands.length} ref={(el) => { if (el) el.indeterminate = on > 0 && on < g.brands.length; }} onChange={(e) => set({ brands: setGroup(d.brands, g, e.target.checked) })} aria-label={g.brands.length > 1 ? `${g.label} : toutes les boutiques` : g.label} />
                    <strong>{g.label}</strong>{g.brands.length > 1 && <span className="faint">toutes les boutiques</span>}
                  </label>
                  {(g.brands.length > 1 ? g.brands : g.brands).map((b) => (
                    g.brands.length === 1 ? (
                      on === 1 && <BrandLevel key={b.code} code={b.code} level={d.brands[b.code] as Level} onLevel={(l) => set({ brands: { ...d.brands, [b.code]: l } })} />
                    ) : (
                      <div key={b.code} className="brand-shop">
                        <label className="row"><input type="checkbox" checked={b.code in d.brands} onChange={(e) => set({ brands: setBrand(d.brands, b.code, e.target.checked) })} /><i className="dot" style={{ ["--c" as string]: brandColor(b.code) }} />{b.label}</label>
                        {b.code in d.brands && <BrandLevel code={b.code} level={d.brands[b.code] as Level} onLevel={(l) => set({ brands: { ...d.brands, [b.code]: l } })} />}
                      </div>
                    )
                  ))}
                </div>
              );
            })}
          </div>
          {chosen.length === 0 && <Callout kind="warn">Aucune marque autorisée : aucun shift ne pourra être attribué à ce collaborateur.</Callout>}
          {chosen.length > 0 && schedules.data && (
            <div aria-label="Horaires proposés selon les marques autorisées">
              <p className="label">Horaires proposés (selon les marques cochées)</p>
              <ul className="row" style={{ listStyle: "none", padding: 0, margin: "var(--sp-1) 0 0" }}>
                {chosen.map((b) => <li key={b}><Badge><i className="dot" style={{ ["--c" as string]: brandColor(b) }} />{b} : {(schedules.data![b] ?? []).map((x) => `${hr(x.start)}–${hr(x.end)}`).join(", ") || "aucun horaire défini"}</Badge></li>)}
              </ul>
            </div>
          )}
        </fieldset>

        <fieldset className="sheet-section">
          <legend className="h2">Jours d&apos;indisponibilité</legend>
          <p className="help">Sélectionnez les dates où ce collaborateur ne peut pas travailler : le moteur ne lui attribuera jamais de shift ces jours-là.</p>
          {avail && period ? <UnavailabilityCalendar dates={avail.dates} anchor={period.start_date} weekdays={avail.weekdays} leaves={avail.leaves} status={datesStatus} onChange={saveDates} /> : <div className="skeleton" style={{ height: "14rem" }} aria-hidden="true" />}
        </fieldset>

        <fieldset className="sheet-section">
          <legend className="h2">Nombre maximum de jours travaillés</legend>
          {exc && monthLabel && (
            <div role="radiogroup" aria-label="Portée du nombre maximum de jours" className="radio-col" style={{ marginBottom: "var(--sp-2)" }}>
              <label className="row"><input type="radio" name="mdscope" checked={!exc.set} onChange={() => changeExc({ set: false, count: null, period: null })} /> Valeur habituelle <span className="faint">— tous les mois</span></label>
              <label className="row"><input type="radio" name="mdscope" checked={exc.set} onChange={() => changeExc({ set: true, count: d.max_days_count, period: d.max_days_period })} /> Exception pour {monthLabel} <span className="faint">— les autres mois ne changent pas</span></label>
            </div>
          )}
          {exc?.set ? (
            <>
              <div className="sheet-pair">
                <Field label={`Nombre de jours (${monthLabel})`}>{(p) => (
                  <Select {...p} value={exc.count === null ? NO_PREF : String(exc.count)} onChange={(e) => changeExc({ ...exc, count: parseNum(e.target.value) })}>
                    <option value={NO_PREF}>Pas de préférence</option>
                    {dayCountOptions(exc.period, periodDays).map((n) => <option key={n} value={n}>{n}</option>)}
                  </Select>)}</Field>
                <Field label={`Période (${monthLabel})`}>{(p) => (
                  <Select {...p} value={exc.period ?? NO_PREF} onChange={(e) => changeExc({ ...exc, period: (e.target.value || null) as MaxDaysPeriod | null })}>
                    <option value={NO_PREF}>Pas de préférence</option>
                    {(Object.keys(PERIOD_LABEL) as MaxDaysPeriod[]).map((k) => <option key={k} value={k}>{PERIOD_LABEL[k]}</option>)}
                  </Select>)}</Field>
              </div>
              <p className="help">Valeur habituelle : {d.max_days_count ? `${d.max_days_count} j / ${d.max_days_period === "week" ? "semaine" : "mois"}` : "pas de préférence"}.</p>
            </>
          ) : (
            <div className="sheet-pair">
              <Field label="Nombre de jours">{(p) => (
                <Select {...p} value={d.max_days_count === null ? NO_PREF : String(d.max_days_count)} onChange={(e) => set({ max_days_count: parseNum(e.target.value) })}>
                  <option value={NO_PREF}>Pas de préférence</option>
                  {dayCountOptions(d.max_days_period, periodDays).map((n) => <option key={n} value={n}>{n}</option>)}
                </Select>)}</Field>
              <Field label="Période">{(p) => (
                <Select {...p} value={d.max_days_period ?? NO_PREF} onChange={(e) => set({ max_days_period: (e.target.value || null) as MaxDaysPeriod | null })}>
                  <option value={NO_PREF}>Pas de préférence</option>
                  {(Object.keys(PERIOD_LABEL) as MaxDaysPeriod[]).map((k) => <option key={k} value={k}>{PERIOD_LABEL[k]}</option>)}
                </Select>)}</Field>
            </div>
          )}
          <p className="help">Limite dure : le moteur ne dépasse jamais ce nombre de jours, y compris sur les semaines à cheval sur deux mois.</p>
        </fieldset>

        <fieldset className="sheet-section">
          <legend className="h2">Préférence horaire</legend>
          <p className="help">Réglage permanent (tous les mois).</p>
          <div className="sheet-pair">
            <Field label="Préférence horaire" help={d.time_pref ? TIME_PREF_HELP[d.time_pref] : "Tous les horaires autorisés sont possibles."}>{(p) => (
              <Select {...p} value={d.time_pref ?? NO_PREF} onChange={(e) => { const v = (e.target.value || null) as TimePref | null; set({ time_pref: v, time_pref_strict: v ? d.time_pref_strict : false }); }}>
                <option value={NO_PREF}>Pas de préférence</option>
                {(Object.keys(TIME_PREF_LABEL) as TimePref[]).map((k) => <option key={k} value={k}>{TIME_PREF_LABEL[k]}</option>)}
              </Select>)}</Field>
            <div role="radiogroup" aria-label="Nature de la préférence horaire" className="radio-col">
              <label className="row"><input type="radio" name="strict" disabled={!d.time_pref} checked={!d.time_pref_strict} onChange={() => set({ time_pref_strict: false })} /> Souple <span className="faint">— dans la mesure du possible</span></label>
              <label className="row"><input type="radio" name="strict" disabled={!d.time_pref} checked={d.time_pref_strict} onChange={() => set({ time_pref_strict: true })} /> Stricte <span className="faint">— obligatoire</span></label>
            </div>
          </div>
          <p className="help">Appliquée uniquement parmi les shifts réellement disponibles pour les marques cochées ; une boutique à horaire unique reste ouverte à tous.</p>
        </fieldset>

        <fieldset className="sheet-section">
          <legend className="h2">Dimanches travaillés{monthLabel ? ` — ${monthLabel}` : " sur la période"}</legend>
          {monthLabel && <p className="help">Réglage propre à ce mois : modifier un autre mois ne change pas celui-ci.</p>}
          <div className="sheet-pair">
            <Field label="Nombre de dimanches">{(p) => (
              <Select {...p} value={d.sunday_quota === null ? NO_PREF : String(d.sunday_quota)} onChange={(e) => { const q = parseNum(e.target.value); set({ sunday_quota: q, sunday_mode: q === null ? "max" : d.sunday_quota === null ? "exact" : d.sunday_mode }); }}>
                <option value={NO_PREF}>Pas de préférence</option>
                {sundayOptions(nSun).map((n) => <option key={n} value={n}>{n} dimanche{n > 1 ? "s" : ""}</option>)}
              </Select>)}</Field>
            <div role="radiogroup" aria-label="Nature du quota de dimanches" className="radio-col">
              <label className="row"><input type="radio" name="smode" disabled={d.sunday_quota === null} checked={d.sunday_mode === "max"} onChange={() => set({ sunday_mode: "max" })} /> Maximum <span className="faint">— plafond</span></label>
              <label className="row"><input type="radio" name="smode" disabled={d.sunday_quota === null} checked={d.sunday_mode === "exact"} onChange={() => set({ sunday_mode: "exact" })} /> Objectif exact <span className="faint">— à atteindre</span></label>
            </div>
          </div>
          {summary && emp.code in summary.employees && summary.employees[emp.code].available_sundays < nSun && (
            <p className="help"><Badge tone="warn" icon="info">Disponibilité</Badge> {summary.employees[emp.code].available_sundays} dimanche(s) disponible(s) sur {nSun}.</p>)}
        </fieldset>

        <EmployeeExtras emp={emp} all={all} />

        {summary && projected && <div className="sheet-counter" aria-live="polite" data-testid="sheet-counter">
          <p className="label">Compteur des dimanches (mis à jour en direct)</p>
          <p className="num"><strong>{projected.reserved}</strong> réservés · <strong>{projected.remaining}</strong> restant à attribuer sur <strong>{projected.total}</strong></p>
          {projected.alerts.filter((a) => a.level === "warning").map((a) => <p key={a.text} className="error-text">{a.text}</p>)}
        </div>}
        {impact.length > 0 && (
          <Callout kind="warn" title="Plannings existants concernés par ce changement">
            <p style={{ margin: 0 }}>Ce réglage permanent rend certaines affectations incompatibles. Rien n&apos;a été modifié : ouvrez le planning pour corriger à la main ou réoptimiser.</p>
            <ul className="row" style={{ listStyle: "none", padding: 0, margin: "var(--sp-2) 0 0" }}>{impact.map((p) => (
              <li key={p.period_id}><Button size="sm" onClick={() => onOpenPeriod?.(p.period_id)}>{p.name} · {p.hard + p.soft} incompatibilité{p.hard + p.soft > 1 ? "s" : ""}</Button></li>))}</ul>
          </Callout>
        )}
        {excErrors.length > 0 && <Callout kind="bad" title="Exception du mois incomplète (non enregistrée)">{excErrors[0]}</Callout>}
        {errors.length > 0 && <Callout kind="bad" title="Paramètres incohérents (non enregistrés)"><ul style={{ margin: 0, paddingLeft: "1.1rem" }}>{errors.map((m) => <li key={m}>{m}</li>)}</ul></Callout>}
        <div className="row modal-actions"><Button variant="primary" onClick={onClose}>Fermer</Button></div>
      </div>
    </Modal>
  );
}

function BrandLevel({ code, level, onLevel }: { code: string; level: Level; onLevel: (l: Level) => void }) {
  return (
    <label className="row brand-level"><span className="sr-only">Priorité de {code}</span>
      <select className="select" aria-label={`Priorité ${code}`} value={level} onChange={(e) => onLevel(e.target.value as Level)}>
        {LEVELS.map((l) => <option key={l} value={l}>{LEVEL_LABEL[l]}</option>)}
      </select></label>
  );
}

export { SundayCounter };
