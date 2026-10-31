"use client";
import { FormEvent, useState } from "react";
import { useMe } from "@/components/Shell";
import { useApi, usePeriod } from "@/components/hooks";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, PageHead, SearchInput, SkeletonCard } from "@/components/ui/primitives";
import { EmployeeSheet, SundayCounter, type SheetEmployee } from "@/components/planning/EmployeeSheet";
import { computeCounter, type SundaySummary } from "@/lib/sundays";
import { summarize, type RulesDraft } from "@/lib/employeeRules";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { brandColor } from "@/lib/brand";
import { t } from "@/lib/i18n";

type Emp = SheetEmployee & { brands: Record<string, string>; allocation_weight: number; active: boolean };
type Contract = { id: string; employee_id: string };

export default function Employees() {
  const me = useMe(); const toast = useToast();
  const emps = useApi<Emp[]>("/employees");
  const contracts = useApi<Contract[]>("/contracts");
  const { period } = usePeriod();
  const sunday = useApi<SundaySummary>(period ? `/periods/${period.id}/sunday-summary` : null);
  const [sheet, setSheet] = useState<Emp | null>(null);
  const [saving, setSaving] = useState(false); const [sheetErr, setSheetErr] = useState("");
  const periodDays = period ? Math.round((Date.parse(period.end_date) - Date.parse(period.start_date)) / 86_400_000) + 1 : 31;
  const [sel, setSel] = useState<Emp | null>(null);
  const [q, setQ] = useState("");
  const canContract = me.permissions.includes("contracts.write");
  const has = (id: string) => contracts.data?.some((c) => c.employee_id === id);
  const num = (f: FormData, k: string) => { const v = f.get(k); return v === null || v === "" ? null : Number(v); };
  const rows = (emps.data ?? []).filter((e) => !q || e.name.toLowerCase().includes(q.toLowerCase()));

  async function saveSheet(e: SheetEmployee, d: RulesDraft) {
    const cur = emps.data?.find((x) => x.id === e.id); if (!cur) return;
    setSaving(true); setSheetErr("");
    try {
      const body = { code: cur.code, name: cur.name, brands: cur.brands, allocation_weight: cur.allocation_weight, active: cur.active, ...d };
      const saved = await api<Emp>(`/employees/${e.id}`, { method: "PUT", json: body });
      emps.mutate((emps.data ?? []).map((x) => (x.id === saved.id ? { ...x, ...saved } : x))); // mise à jour immédiate, sans rechargement
      sunday.reload();
      toast.push(`Fiche de ${cur.name} enregistrée.`, "ok"); setSheet(null);
    } catch (err: any) { setSheetErr(err.status === 403 ? "Votre rôle ne permet pas de modifier cette fiche." : `Enregistrement impossible : ${String(err.message)}. Les valeurs précédentes sont conservées.`); }
    finally { setSaving(false); }
  }
  const counter = sunday.data && emps.data ? computeCounter(sunday.data, emps.data.map((x) => ({ code: x.code, sunday_quota: x.sunday_quota, sunday_mode: x.sunday_mode }))) : null;

  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); const f = new FormData(e.currentTarget);
    try {
      await api("/contracts", { method: "POST", json: {
        employee_id: sel!.id, start_date: f.get("start") || null, end_date: f.get("end") || null,
        activity_rate: num(f, "rate") === null ? null : num(f, "rate")! / 100,
        weekly_minutes: num(f, "weekly") === null ? null : num(f, "weekly")! * 60,
        monthly_min_minutes: num(f, "min") === null ? null : num(f, "min")! * 60,
        monthly_max_minutes: num(f, "max") === null ? null : num(f, "max")! * 60,
        overtime_allowed: f.get("ot") === "on" } });
      toast.push(`Contrat enregistré pour ${sel!.name}.`, "ok"); setSel(null); contracts.reload();
    } catch (err: any) { toast.push(String(err.message), "bad"); }
  }
  const missing = (emps.data ?? []).filter((e) => !has(e.id)).length;
  return (
    <>
      <PageHead eyebrow={`${emps.data?.length ?? 0} collaborateurs`} title={t("nav.employees")} />
      {counter && sunday.data && sunday.data.total > 0 && <SundayCounter counter={counter} summary={sunday.data} />}
      {emps.error ? <ErrorState message={emps.error} onRetry={emps.reload} /> : emps.loading && !emps.data ? <SkeletonCard lines={6} /> : (
        <Card title="Collaborateurs et contrats" actions={<div className="row">{missing > 0 && <Badge tone="warn" icon="alert">{missing} contrat(s) à renseigner</Badge>}<div style={{ width: "14rem" }}><SearchInput aria-label="Rechercher un collaborateur" placeholder="Rechercher…" value={q} onChange={(e) => setQ(e.target.value)} /></div></div>}>
          {!rows.length ? <EmptyState icon="users" title="Aucun collaborateur">Ajoutez des collaborateurs via l&apos;import (onglet Import / Export) ou l&apos;API.</EmptyState> : (
            <div className="table-wrap"><table className="table table-cards">
              <thead><tr><th>Nom</th><th>Marques</th><th>Limites et préférences</th><th>Poids</th><th>Contrat</th><th><span className="sr-only">Actions</span></th></tr></thead>
              <tbody>{rows.map((e) => (
                <tr key={e.id}><td className="cell-main nowrap"><strong>{e.name}</strong></td>
                  <td data-label="Marques"><div className="row">{Object.entries(e.brands).map(([b, l]) => <Badge key={b} tone={l === "priority" ? "accent" : "neutral"}><i className="dot" style={{ ["--c" as string]: brandColor(b) }} />{b}{l === "priority" ? "" : " · renfort"}</Badge>)}</div></td>
                  <td data-label="Limites"><div className="row">{summarize(e).length ? summarize(e).map((t) => <Badge key={t} tone="accent">{t}</Badge>) : <span className="faint">Pas de préférence</span>}</div></td>
                  <td className="num" data-label="Poids">{e.allocation_weight}</td>
                  <td data-label="Contrat">{has(e.id) ? <Badge tone="ok" icon="check">Saisi</Badge> : <Badge tone="warn" icon="alert">{t("to_fill")}</Badge>}</td>
                  <td><div className="row" style={{ flexWrap: "nowrap" }}><Button size="sm" className="nowrap" onClick={() => { setSheetErr(""); setSheet(e); }}>Fiche</Button><Button size="sm" className="nowrap" onClick={() => setSel(e)}>Contrat</Button></div></td></tr>
              ))}</tbody>
            </table></div>
          )}
        </Card>
      )}
      <EmployeeSheet emp={sheet} all={emps.data ?? []} summary={sunday.data} periodDays={periodDays} saving={saving} error={sheetErr} onClose={() => setSheet(null)} onSave={saveSheet} />
      <Modal open={!!sel} onClose={() => setSel(null)} title={`Contrat — ${sel?.name ?? ""}`} description="Laissez vide ce qui n'est pas connu : aucune valeur n'est supposée.">
        <form onSubmit={save} className="stack">
          <div className="grid-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(10rem, 1fr))" }}>
            <Field label="Date de début">{(p) => <Input {...p} name="start" type="date" />}</Field>
            <Field label="Date de fin">{(p) => <Input {...p} name="end" type="date" />}</Field>
            <Field label="Taux d'activité (%)" help="Ex. 80">{(p) => <Input {...p} name="rate" type="number" min={1} max={100} step="any" />}</Field>
            <Field label="Heures hebdomadaires">{(p) => <Input {...p} name="weekly" type="number" min={0} step="any" />}</Field>
            <Field label="Minimum mensuel (h)">{(p) => <Input {...p} name="min" type="number" min={0} step="any" />}</Field>
            <Field label="Maximum mensuel (h)">{(p) => <Input {...p} name="max" type="number" min={0} step="any" />}</Field>
          </div>
          <label className="row"><input name="ot" type="checkbox" /> Heures supplémentaires autorisées</label>
          <div className="row"><Button type="submit" variant="primary" disabled={!canContract}>Enregistrer</Button><Button onClick={() => setSel(null)}>Annuler</Button>{!canContract && <span className="help">Votre rôle ne permet pas de saisir un contrat.</span>}</div>
        </form>
      </Modal>
    </>
  );
}
