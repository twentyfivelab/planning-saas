"use client";
import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Callout, Field, Select } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";
import { SundayCounter } from "./SundayCounter";
import { computeCounter, type SundayEmployee, type SundaySummary } from "@/lib/sundays";
import {
  NO_PREF, PERIOD_LABEL, TIME_PREF_HELP, TIME_PREF_LABEL, dayCountOptions, parseNum, sundayOptions, validateDraft,
  type MaxDaysPeriod, type RulesDraft, type TimePref,
} from "@/lib/employeeRules";

export type SheetEmployee = { id: string; code: string; name: string } & RulesDraft;

/** Fiche individuelle : jours maximum (nombre + période), préférence horaire (souple/stricte), quota de dimanches (max/exact). */
export function EmployeeSheet({ emp, all, summary, periodDays, saving, error, onClose, onSave }: {
  emp: SheetEmployee | null; all: SheetEmployee[]; summary: SundaySummary | null; periodDays: number; saving: boolean; error: string;
  onClose: () => void; onSave: (e: SheetEmployee, d: RulesDraft) => void;
}) {
  const [d, setD] = useState<RulesDraft | null>(null);
  useEffect(() => { if (emp) setD({ max_days_count: emp.max_days_count, max_days_period: emp.max_days_period, time_pref: emp.time_pref, time_pref_strict: emp.time_pref_strict, sunday_quota: emp.sunday_quota, sunday_mode: emp.sunday_mode }); }, [emp]);
  const nSun = summary?.sundays.length ?? 5;
  const errors = d ? validateDraft(d, nSun, periodDays) : [];
  // compteur « après enregistrement » : quotas de tous les collaborateurs, avec le brouillon de celui-ci
  const projected = useMemo(() => {
    if (!summary || !emp || !d) return null;
    const list: SundayEmployee[] = all.map((e) => (e.id === emp.id ? { code: e.code, sunday_quota: d.sunday_quota, sunday_mode: d.sunday_mode } : { code: e.code, sunday_quota: e.sunday_quota, sunday_mode: e.sunday_mode }));
    return computeCounter(summary, list);
  }, [summary, emp, d, all]);
  if (!emp || !d) return <Modal open={false} onClose={onClose} title="">{null}</Modal>;
  const set = (p: Partial<RulesDraft>) => setD({ ...d, ...p });

  return (
    <Modal open onClose={onClose} title={`Fiche — ${emp.name}`} description="« Pas de préférence » = aucune limite : rien n'est supposé.">
      <form onSubmit={(e) => { e.preventDefault(); if (!errors.length) onSave(emp, d); }} className="stack" style={{ gap: "var(--sp-4)" }}>
        <fieldset className="sheet-section">
          <legend className="h2">Nombre maximum de jours travaillés</legend>
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
          <p className="help">Limite dure : le moteur ne dépasse jamais ce nombre de jours, y compris sur les semaines à cheval sur deux mois.</p>
        </fieldset>

        <fieldset className="sheet-section">
          <legend className="h2">Préférence horaire</legend>
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
          <p className="help">Les catégories s&apos;appliquent aux boutiques ayant plusieurs horaires ; une boutique à horaire unique reste ouverte à tous.</p>
        </fieldset>

        <fieldset className="sheet-section">
          <legend className="h2">Dimanches travaillés sur la période</legend>
          <div className="sheet-pair">
            <Field label="Nombre de dimanches">{(p) => (
              <Select {...p} value={d.sunday_quota === null ? NO_PREF : String(d.sunday_quota)} onChange={(e) => set({ sunday_quota: parseNum(e.target.value), sunday_mode: e.target.value === NO_PREF ? "max" : d.sunday_mode })}>
                <option value={NO_PREF}>Pas de préférence</option>
                {sundayOptions(nSun).map((n) => <option key={n} value={n}>{n} dimanche{n > 1 ? "s" : ""}</option>)}
              </Select>)}</Field>
            <div role="radiogroup" aria-label="Nature du quota de dimanches" className="radio-col">
              <label className="row"><input type="radio" name="smode" disabled={d.sunday_quota === null} checked={d.sunday_mode === "max"} onChange={() => set({ sunday_mode: "max" })} /> Maximum <span className="faint">— plafond</span></label>
              <label className="row"><input type="radio" name="smode" disabled={d.sunday_quota === null} checked={d.sunday_mode === "exact"} onChange={() => set({ sunday_mode: "exact" })} /> Objectif exact <span className="faint">— réserve</span></label>
            </div>
          </div>
          {summary && emp.code in summary.employees && summary.employees[emp.code].available_sundays < nSun && (
            <p className="help"><Badge tone="warn" icon="info">Disponibilité</Badge> {summary.employees[emp.code].available_sundays} dimanche(s) disponible(s) sur {nSun}.</p>)}
        </fieldset>

        {summary && projected && <div className="sheet-counter" aria-live="polite">
          <p className="label">Compteur des dimanches après enregistrement</p>
          <p className="num"><strong>{projected.reserved}</strong> réservés · <strong>{projected.remaining}</strong> restant à attribuer sur <strong>{projected.total}</strong></p>
          {projected.alerts.filter((a) => a.level === "warning").map((a) => <p key={a.text} className="error-text">{a.text}</p>)}
        </div>}
        {errors.length > 0 && <Callout kind="bad" title="Paramètres incohérents"><ul style={{ margin: 0, paddingLeft: "1.1rem" }}>{errors.map((m) => <li key={m}>{m}</li>)}</ul></Callout>}
        {error && <Callout kind="bad" title="Échec de l'enregistrement">{error}</Callout>}
        <div className="row modal-actions">
          <Button onClick={onClose} disabled={saving}>Annuler</Button>
          <Button type="submit" variant="primary" disabled={saving || errors.length > 0}>{saving ? "Enregistrement…" : "Enregistrer la fiche"}</Button>
        </div>
      </form>
    </Modal>
  );
}

export { SundayCounter };
