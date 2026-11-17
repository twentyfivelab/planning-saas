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
import { IncompatModal } from "./IncompatModal";
import { computeCounter, type SundayEmployee, type SundaySummary } from "@/lib/sundays";
import {
  NO_PREF, TIME_PREF_HELP, TIME_PREF_LABEL, dayCountOptions, parseNum, sundayOptions, validateDays, validateDraft,
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
/** exception du mois sur les jours minimum / maximum par mois (sinon : valeurs habituelles de la fiche) */
export type DaysException = { set: boolean; min: number | null; max: number | null };
type ImpactRow = { period_id: string; name: string; status: string; frozen: boolean; frozen_at: string | null; hard: number; soft: number; if_applied: { hard: number; soft: number } };
type Impact = { employee_code: string; periods: ImpactRow[] };
/** true = enregistré ; texte = refus du serveur, affiché tel quel (raison précise) */
export type SaveResult = boolean | string;

export function EmployeeSheet({ emp, all, summary, periodDays, period, monthLabel, monthExc, onMonthExc, daysExc, onDaysExc, capLabel, onOpenPeriod, onClose, onSave }: {
  emp: SheetEmployee | null; all: SheetEmployee[]; summary: SundaySummary | null; periodDays: number; period: { start_date: string; end_date: string } | null; monthLabel?: string;
  /** exception du mois sur le nombre maximum de jours (sinon : valeur habituelle) */
  monthExc?: MonthException; onMonthExc?: (v: MonthException) => Promise<boolean>; onOpenPeriod?: (periodId: string) => void;
  daysExc?: DaysException; onDaysExc?: (v: DaysException) => Promise<SaveResult>; capLabel?: string | null;
  onClose: () => void; onSave: (e: SheetEmployee, d: FicheDraft) => Promise<SaveResult>;
}) {
  const [dexc, setDexc] = useState<DaysException | null>(null);
  const [dexcStatus, setDexcStatus] = useState<Status>("idle");
  const [saveErr, setSaveErr] = useState("");
  const [detail, setDetail] = useState<{ period: ImpactRow; params: "plan" | "current" } | null>(null);
  const dexcTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [exc, setExc] = useState<MonthException | null>(null);
  const [excStatus, setExcStatus] = useState<Status>("idle");
  const [impact, setImpact] = useState<ImpactRow[]>([]);
  const [impactCode, setImpactCode] = useState("");
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
    const init: FicheDraft = { max_days_count: emp.max_days_count, max_days_period: emp.max_days_period, time_pref: emp.time_pref, time_pref_strict: emp.time_pref_strict, sunday_quota: emp.sunday_quota, sunday_mode: emp.sunday_mode, brands: emp.brands ?? {},
      min_days_month: emp.min_days_month ?? null, max_days_month: emp.max_days_month ?? null };
    saved.current = JSON.stringify(init); setD(init); setStatus("idle"); setDatesStatus("idle"); setAvail(null); setImpact([]); setExcStatus("idle"); setSaveErr(""); setDexcStatus("idle");
    setExc(monthExc ?? null); setDexc(daysExc ?? null);
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
      const perm = (x: FicheDraft) => JSON.stringify([x.brands, x.time_pref, x.time_pref_strict, x.max_days_count, x.max_days_period, x.min_days_month ?? null, x.max_days_month ?? null]);
      const permanentChanged = (() => { try { return perm(JSON.parse(saved.current)) !== perm(d); } catch { return false; } })();
      const r = await onSave(emp, d);
      const ok = r === true;
      setSaveErr(typeof r === "string" ? r : "");
      if (ok) { saved.current = key; setStatus("saved"); } else setStatus("error");
      // paramètre PERMANENT modifié : effet sur les plannings déjà créés (ils conservent leurs paramètres ; aucune modification automatique)
      if (ok && permanentChanged) api<Impact>(`/employees/${emp.id}/impact`).then((x) => { setImpact(x.periods); setImpactCode(x.employee_code); }).catch(() => {});
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
  const dexcErrors = dexc?.set ? validateDays(dexc.min, dexc.max, periodDays) : [];
  function changeDexc(v: DaysException) {
    setDexc(v); setDexcStatus("saving"); setSaveErr("");
    clearTimeout(dexcTimer.current);
    if (v.set && validateDays(v.min, v.max, periodDays).length) { setDexcStatus("idle"); return; }
    dexcTimer.current = setTimeout(async () => { const r = onDaysExc ? await onDaysExc(v) : false; setDexcStatus(r === true ? "saved" : "error"); if (typeof r === "string") setSaveErr(r); }, 400);
  }

  function saveDates(next: string[]) {
    setAvail((a) => (a ? { ...a, dates: next } : a)); setDatesStatus("saving");
    clearTimeout(dateTimer.current);
    dateTimer.current = setTimeout(async () => {
      try { await api(`/employees/${emp!.id}/unavailable-dates`, { method: "PUT", json: { dates: next } }); setDatesStatus("saved"); invalidate(); }
      catch { setDatesStatus("error"); }
    }, 300);
  }
  const chosen = Object.keys(d.brands);
  const sts = [status, datesStatus, excStatus, dexcStatus];
  const overall = sts.includes("saving") ? "Enregistrement…" : sts.includes("error") ? "Échec de l'enregistrement" : errors.length || excErrors.length || dexcErrors.length ? "Corrigez les paramètres pour enregistrer" : sts.includes("saved") ? "Enregistré automatiquement" : "Les modifications sont enregistrées automatiquement";

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

        <fieldset className="sheet-section" data-testid="days-month">
          <legend className="h2">Jours travaillés par mois</legend>
          {dexc && monthLabel && (
            <div role="radiogroup" aria-label="Portée des jours par mois" className="radio-col" style={{ marginBottom: "var(--sp-2)" }}>
              <label className="row"><input type="radio" name="dscope" checked={!dexc.set} onChange={() => changeDexc({ set: false, min: null, max: null })} /> Valeurs habituelles <span className="faint">— prochains plannings</span></label>
              <label className="row"><input type="radio" name="dscope" checked={dexc.set} onChange={() => changeDexc({ set: true, min: d.min_days_month ?? null, max: d.max_days_month ?? null })} /> Exception pour {monthLabel} <span className="faint">— les autres mois ne changent pas</span></label>
            </div>
          )}
          <div className="sheet-pair sheet-pair-end">
            <Field label={dexc?.set ? `Minimum de jours (${monthLabel})` : "Minimum de jours par mois"}>{(p) => (
              <Select {...p} value={(dexc?.set ? dexc.min : d.min_days_month) == null ? NO_PREF : String(dexc?.set ? dexc.min : d.min_days_month)}
                onChange={(e) => (dexc?.set ? changeDexc({ ...dexc, min: parseNum(e.target.value) }) : set({ min_days_month: parseNum(e.target.value) }))}>
                <option value={NO_PREF}>Pas de préférence</option>
                {dayCountOptions("month", periodDays).map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>)}</Field>
            <Field label={dexc?.set ? `Maximum de jours (${monthLabel})` : "Maximum de jours par mois"}>{(p) => (
              <Select {...p} value={(dexc?.set ? dexc.max : d.max_days_month) == null ? NO_PREF : String(dexc?.set ? dexc.max : d.max_days_month)}
                onChange={(e) => (dexc?.set ? changeDexc({ ...dexc, max: parseNum(e.target.value) }) : set({ max_days_month: parseNum(e.target.value) }))}>
                <option value={NO_PREF}>Pas de préférence</option>
                {dayCountOptions("month", periodDays).map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>)}</Field>
          </div>
          {dexc?.set && <p className="help">Valeurs habituelles : minimum {d.min_days_month ?? "pas de préférence"}, maximum {d.max_days_month ?? "pas de préférence"}.</p>}
          <p className="help">Minimum et maximum sont deux limites obligatoires et indépendantes ; une journée compte une seule fois, même avec plusieurs affectations. Si une limite ne peut pas être respectée, la génération est bloquée et la raison est affichée.</p>
          <p className="help">« Pas de préférence » désactive seulement la limite de jours correspondante{capLabel ? ` : le plafond de ${capLabel} de travail effectif par mois (tous sites et marques cumulés) reste toujours appliqué` : ""}.</p>
        </fieldset>

        <fieldset className="sheet-section">
          <legend className="h2">Nombre maximum de jours par semaine</legend>
          {exc && monthLabel && (
            <div role="radiogroup" aria-label="Portée du nombre maximum de jours par semaine" className="radio-col" style={{ marginBottom: "var(--sp-2)" }}>
              <label className="row"><input type="radio" name="mdscope" checked={!exc.set} onChange={() => changeExc({ set: false, count: null, period: null })} /> Valeur habituelle <span className="faint">— tous les mois</span></label>
              <label className="row"><input type="radio" name="mdscope" checked={exc.set} onChange={() => changeExc({ set: true, count: d.max_days_period === "week" ? d.max_days_count : null, period: d.max_days_period === "week" ? "week" : null })} /> Exception pour {monthLabel} <span className="faint">— les autres mois ne changent pas</span></label>
            </div>
          )}
          <Field label={exc?.set ? `Jours par semaine (${monthLabel})` : "Jours par semaine"}>{(p) => (
            <Select {...p} value={exc?.set ? (exc.count === null ? NO_PREF : String(exc.count)) : (d.max_days_count === null || d.max_days_period !== "week" ? NO_PREF : String(d.max_days_count))}
              onChange={(e) => { const n = parseNum(e.target.value); if (exc?.set) changeExc({ set: true, count: n, period: n === null ? null : "week" }); else set({ max_days_count: n, max_days_period: n === null ? null : "week" }); }} style={{ maxWidth: "14rem" }}>
              <option value={NO_PREF}>Pas de préférence</option>
              {dayCountOptions("week", periodDays).map((n) => <option key={n} value={n}>{n}</option>)}
            </Select>)}</Field>
          {d.max_days_period === "month" && d.max_days_count !== null && !exc?.set && <p className="help"><Badge tone="info" icon="info">Ancien réglage</Badge> « {d.max_days_count} jours sur la période » : utilisez désormais le maximum de jours par mois ci-dessus.</p>}
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
          <Callout kind="info" title="Plannings existants et ce changement" >
            <p style={{ margin: 0 }}>Les plannings déjà créés conservent leurs paramètres : ce changement s&apos;applique aux prochains plannings. Rien n&apos;a été modifié.</p>
            <ul style={{ listStyle: "none", padding: 0, margin: "var(--sp-2) 0 0" }} className="stack" data-testid="impact-list">{impact.map((p) => {
              const own = p.hard + p.soft; const next = p.if_applied.hard + p.if_applied.soft;
              return (
                <li key={p.period_id} className="row">
                  <strong>{p.name}</strong>
                  {p.frozen ? <span className="muted">{own ? `${own} incompatibilité${own > 1 ? "s" : ""} avec ses paramètres` : "aucune incompatibilité avec ses paramètres"} · {next} incompatibilité{next > 1 ? "s" : ""} si vous lui appliquez les paramètres actuels</span>
                    : <span className="muted">{own} incompatibilité{own > 1 ? "s" : ""}</span>}
                  {own > 0 && <Button size="sm" onClick={() => setDetail({ period: p, params: "plan" })}>Voir le détail</Button>}
                  {p.frozen && next > 0 && <Button size="sm" onClick={() => setDetail({ period: p, params: "current" })}>Détail si appliqués</Button>}
                  <Button size="sm" variant="ghost" onClick={() => onOpenPeriod?.(p.period_id)}>Ouvrir le planning</Button>
                </li>);
            })}</ul>
          </Callout>
        )}
        {detail && <IncompatModal open onClose={() => setDetail(null)} periodId={detail.period.period_id} periodName={detail.period.name} params={detail.params} employeeCode={impactCode} employeeName={emp.name} />}
        {saveErr && <Callout kind="bad" title="Paramètres refusés (non enregistrés)">{saveErr}</Callout>}
        {dexcErrors.length > 0 && <Callout kind="bad" title={`Exception de ${monthLabel ?? "ce mois"} incohérente (non enregistrée)`}><ul style={{ margin: 0, paddingLeft: "1.1rem" }}>{dexcErrors.map((m) => <li key={m}>{m}</li>)}</ul></Callout>}
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
