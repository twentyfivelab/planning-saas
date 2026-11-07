"use client";
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useApi, useMonthState } from "@/components/hooks";
import { useToast } from "@/components/ui/Toast";
import { EmployeeSheet, type FicheDraft, type MonthException, type SheetEmployee } from "@/components/planning/EmployeeSheet";
import type { MonthCalendar } from "@/components/planning/MonthNeeds";
import { api } from "@/lib/api";
import { invalidate } from "@/lib/invalidate";
import { monthLabel, parseMonthKey } from "@/lib/months";
import { computeCounter } from "@/lib/sundays";
import type { MaxDaysPeriod } from "@/lib/employeeRules";

export type SheetEmp = SheetEmployee & { brands: Record<string, string>; allocation_weight: number; active: boolean };
export type MonthParam = {
  employee_id: string; sunday_quota: number | null; sunday_mode: "max" | "exact"; source: string;
  max_days_set: boolean; max_days_count: number | null; max_days_period: MaxDaysPeriod | null;
};

/**
 * Fiche collaborateur dans le contexte d'UN mois (page Collaborateurs et assistant de création) : mêmes composants et même logique.
 * Permanent : marques, préférences horaires, jours maximum habituels. Mensuel : dimanches, exception de jours maximum, indisponibilités datées.
 */
export function useMonthSheet(month: string) {
  const toast = useToast(); const router = useRouter();
  const [, setMonth] = useMonthState();
  const emps = useApi<SheetEmp[]>("/employees");
  const { y, m } = parseMonthKey(month);
  const cal = useApi<MonthCalendar>(`/calendar?year=${y}&month=${m}`);
  const mp = useApi<MonthParam[]>(`/month-params?month=${month}`);
  const mpById = useMemo(() => new Map((mp.data ?? []).map((x) => [x.employee_id, x])), [mp.data]);
  // quota de dimanches du mois superposé (les jours maximum de la fiche restent la valeur habituelle)
  const empsM = useMemo(() => (emps.data ?? []).map((e) => { const p = mpById.get(e.id); return p ? { ...e, sunday_quota: p.sunday_quota, sunday_mode: p.sunday_mode } : e; }), [emps.data, mpById]);
  const [sheet, setSheet] = useState<SheetEmp | null>(null);
  const summary = cal.data?.sunday ?? null;
  const reload = () => { cal.reload(); mp.reload(); emps.reload(); };

  async function onSave(e: SheetEmployee, d: FicheDraft): Promise<boolean> {
    const cur = emps.data?.find((x) => x.id === e.id); if (!cur) return false;
    try {
      const body = { code: cur.code, name: cur.name, allocation_weight: cur.allocation_weight, active: cur.active, ...d, sunday_quota: cur.sunday_quota ?? null, sunday_mode: cur.sunday_mode ?? "max" };
      const saved = await api<SheetEmp>(`/employees/${e.id}`, { method: "PUT", json: body });
      const before = mpById.get(e.id);
      if (!before || before.sunday_quota !== d.sunday_quota || before.sunday_mode !== d.sunday_mode) {
        const r = await api<MonthParam & { notice?: string | null }>(`/employees/${e.id}/month-params/${month}`, { method: "PUT", json: { sunday_quota: d.sunday_quota, sunday_mode: d.sunday_mode } });
        if (r.notice) toast.push(r.notice, "info");
        mp.mutate([...(mp.data ?? []).filter((x) => x.employee_id !== e.id), r]);
      }
      emps.mutate((emps.data ?? []).map((x) => (x.id === saved.id ? { ...x, ...saved } : x)));
      cal.reload(); invalidate();
      return true;
    } catch { return false; }
  }
  async function onMonthExc(v: MonthException): Promise<boolean> {
    if (!sheet) return false;
    try {
      const r = await api<MonthParam & { notice?: string | null }>(`/employees/${sheet.id}/month-params/${month}`, { method: "PUT", json: { max_days_set: v.set, max_days_count: v.count, max_days_period: v.period } });
      if (r.notice) toast.push(r.notice, "info");
      mp.mutate([...(mp.data ?? []).filter((x) => x.employee_id !== sheet.id), r]); invalidate();
      return true;
    } catch { return false; }
  }
  const counter = summary && emps.data ? computeCounter(summary, empsM.map((x) => ({ code: x.code, sunday_quota: x.sunday_quota, sunday_mode: x.sunday_mode }))) : null;
  const exc = sheet ? mpById.get(sheet.id) : undefined;
  const element = (
    <EmployeeSheet emp={sheet} all={empsM} monthLabel={monthLabel(month)} summary={summary} periodDays={cal.data?.days ?? 31}
      period={cal.data ? { start_date: cal.data.start, end_date: cal.data.end } : null}
      monthExc={sheet ? { set: !!exc?.max_days_set, count: exc?.max_days_set ? exc.max_days_count : null, period: exc?.max_days_set ? exc.max_days_period : null } : undefined}
      onMonthExc={onMonthExc}
      onOpenPeriod={async (pid) => { const ps = await api<{ id: string; start_date: string }[]>("/periods"); const p = ps.find((x) => x.id === pid); if (p) { setMonth(p.start_date.slice(0, 7)); setSheet(null); router.push("/planning"); } }}
      onClose={() => setSheet(null)} onSave={onSave} />
  );
  /** valeurs EFFECTIVES du mois (exception comprise) pour l'affichage */
  const effective = (e: SheetEmp) => { const p = mpById.get(e.id); return p?.max_days_set ? { ...e, max_days_count: p.max_days_count, max_days_period: p.max_days_period, exception: true } : { ...e, exception: false }; };
  return { emps, empsM, cal, mp, summary, counter, ready: !!mp.data && !!emps.data && !!cal.data, open: (e: SheetEmp) => setSheet(empsM.find((x) => x.id === e.id) ?? e), element, effective, reload };
}
