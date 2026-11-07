"use client";
import { FormEvent, useState } from "react";
import { useMe } from "@/components/Shell";
import { useApi, usePeriod } from "@/components/hooks";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, PageHead, SearchInput, SkeletonCard } from "@/components/ui/primitives";
import { SundayCounter } from "@/components/planning/EmployeeSheet";
import { useMonthSheet, type SheetEmp as Emp } from "@/components/planning/useMonthSheet";
import { MonthSwitcher } from "@/components/MonthSwitcher";
import { summarize } from "@/lib/employeeRules";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { brandColor } from "@/lib/brand";
import { t } from "@/lib/i18n";
import { errText, parseRate, rateInput } from "@/lib/wfm";

type Contract = { id: string; employee_id: string; start_date: string | null; end_date: string | null; activity_rate: number | null; weekly_minutes: number | null; monthly_min_minutes: number | null; monthly_target_minutes: number | null; monthly_max_minutes: number | null; weekly_max_minutes: number | null; overtime_allowed: boolean; contract_type: string | null; hourly_cost_cents: number | null; legal_regime: string | null };

export default function Employees() {
  const me = useMe(); const toast = useToast();
  const contracts = useApi<Contract[]>("/contracts");
  const { month, setMonth } = usePeriod();
  const sheetCtl = useMonthSheet(month);
  const { emps, empsM, summary, counter } = sheetCtl;
  const [sel, setSel] = useState<Emp | null>(null);
  const [q, setQ] = useState("");
  const canContract = me.permissions.includes("contracts.write");
  const has = (id: string) => contracts.data?.some((c) => c.employee_id === id);
  const num = (f: FormData, k: string) => { const v = f.get(k); return v === null || v === "" ? null : Number(v); };
  const rows = empsM.filter((e) => !q || e.name.toLowerCase().includes(q.toLowerCase()));

  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); const f = new FormData(e.currentTarget);
    try {
      const hours = (k: string) => (num(f, k) === null ? null : Math.round(num(f, k)! * 60));
      const body = {
        employee_id: sel!.id, start_date: f.get("start") || null, end_date: f.get("end") || null,
        activity_rate: num(f, "rate") === null ? null : num(f, "rate")! / 100,
        weekly_minutes: hours("weekly"), monthly_min_minutes: hours("min"), monthly_target_minutes: hours("target"), monthly_max_minutes: hours("max"), weekly_max_minutes: hours("wmax"),
        contract_type: String(f.get("ctype") || "") || null, legal_regime: String(f.get("regime") || "") || null, hourly_cost_cents: parseRate(f.get("cost")),
        overtime_allowed: f.get("ot") === "on" };
      const cur = contracts.data?.find((c) => c.employee_id === sel!.id);
      if (cur) await api(`/contracts/${cur.id}`, { method: "PUT", json: body }); else await api("/contracts", { method: "POST", json: body });
      toast.push(`Contrat enregistré pour ${sel!.name}.`, "ok"); setSel(null); contracts.reload();
    } catch (err: unknown) { toast.push(errText(err), "bad"); }
  }
  const missing = (emps.data ?? []).filter((e) => !has(e.id)).length;
  const cur = sel ? contracts.data?.find((c) => c.employee_id === sel.id) : undefined;
  const h = (m: number | null | undefined) => (m === null || m === undefined ? "" : m / 60);
  return (
    <>
      <PageHead eyebrow={`${emps.data?.length ?? 0} collaborateurs`} title={t("nav.employees")}><MonthSwitcher month={month} onChange={setMonth} /></PageHead>
      {counter && summary && summary.total > 0 && <SundayCounter counter={counter} summary={summary} />}
      {emps.error ? <ErrorState message={emps.error} onRetry={emps.reload} /> : emps.loading && !emps.data ? <SkeletonCard lines={6} /> : (
        <Card title="Collaborateurs et contrats" actions={<div className="row">{missing > 0 && <Badge tone="warn" icon="alert">{missing} contrat(s) à renseigner</Badge>}<div style={{ width: "14rem" }}><SearchInput aria-label="Rechercher un collaborateur" placeholder="Rechercher…" value={q} onChange={(e) => setQ(e.target.value)} /></div></div>}>
          {!rows.length ? <EmptyState icon="users" title="Aucun collaborateur">Ajoutez des collaborateurs via l&apos;import (onglet Import / Export) ou l&apos;API.</EmptyState> : (
            <div className="table-wrap"><table className="table table-cards">
              <thead><tr><th>Nom</th><th>Marques</th><th>Limites et préférences</th><th>Poids</th><th>Contrat</th><th><span className="sr-only">Actions</span></th></tr></thead>
              <tbody>{rows.map((e) => (
                <tr key={e.id}><td className="cell-main nowrap"><strong>{e.name}</strong></td>
                  <td data-label="Marques"><div className="row">{Object.entries(e.brands).map(([b, l]) => <Badge key={b} tone={l === "priority" ? "accent" : "neutral"}><i className="dot" style={{ ["--c" as string]: brandColor(b) }} />{b}{l === "priority" ? "" : " · renfort"}</Badge>)}</div></td>
                  <td data-label="Limites"><div className="row">{summarize(sheetCtl.effective(e)).length ? summarize(sheetCtl.effective(e)).map((t) => <Badge key={t} tone="accent">{t}</Badge>) : <span className="faint">Pas de préférence</span>}</div></td>
                  <td className="num" data-label="Poids">{e.allocation_weight}</td>
                  <td data-label="Contrat">{has(e.id) ? <Badge tone="ok" icon="check">Saisi</Badge> : <Badge tone="warn" icon="alert">{t("to_fill")}</Badge>}</td>
                  <td><div className="row" style={{ flexWrap: "nowrap" }}><Button size="sm" className="nowrap" disabled={!sheetCtl.ready} onClick={() => sheetCtl.open(e)}>Fiche</Button><Button size="sm" className="nowrap" onClick={() => setSel(e)}>Contrat</Button></div></td></tr>
              ))}</tbody>
            </table></div>
          )}
        </Card>
      )}
      {sheetCtl.element}
      <Modal open={!!sel} onClose={() => setSel(null)} title={`Contrat — ${sel?.name ?? ""}`} description="Laissez vide ce qui n'est pas connu : aucune valeur n'est supposée.">
        <form key={sel?.id ?? "none"} onSubmit={save} className="stack">
          <div className="grid-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(10rem, 1fr))" }}>
            <Field label="Type de contrat" help="Ex. CDI, CDD, mission">{(p) => <Input {...p} name="ctype" maxLength={32} defaultValue={cur?.contract_type ?? ""} />}</Field>
            <Field label="Date de début">{(p) => <Input {...p} name="start" type="date" defaultValue={cur?.start_date ?? ""} />}</Field>
            <Field label="Date de fin">{(p) => <Input {...p} name="end" type="date" defaultValue={cur?.end_date ?? ""} />}</Field>
            <Field label="Taux d'activité (%)" help="Ex. 80">{(p) => <Input {...p} name="rate" type="number" min={1} max={100} step="any" defaultValue={cur?.activity_rate != null ? cur.activity_rate * 100 : ""} />}</Field>
            <Field label="Heures hebdomadaires">{(p) => <Input {...p} name="weekly" type="number" min={0} step="any" defaultValue={h(cur?.weekly_minutes)} />}</Field>
            <Field label="Maximum hebdomadaire (h)" help="Plafond du contrat">{(p) => <Input {...p} name="wmax" type="number" min={0} step="any" defaultValue={h(cur?.weekly_max_minutes)} />}</Field>
            <Field label="Minimum mensuel (h)">{(p) => <Input {...p} name="min" type="number" min={0} step="any" defaultValue={h(cur?.monthly_min_minutes)} />}</Field>
            <Field label="Objectif mensuel (h)" help="Sert à l'équité du moteur">{(p) => <Input {...p} name="target" type="number" min={0} step="any" defaultValue={h(cur?.monthly_target_minutes)} />}</Field>
            <Field label="Maximum mensuel (h)">{(p) => <Input {...p} name="max" type="number" min={0} step="any" defaultValue={h(cur?.monthly_max_minutes)} />}</Field>
            <Field label="Coût horaire (CHF)" help="Coût employeur, si connu">{(p) => <Input {...p} name="cost" inputMode="decimal" defaultValue={rateInput(cur?.hourly_cost_cents)} />}</Field>
            <Field label="Régime légal" help="Ex. LTr-45, voir Règles">{(p) => <Input {...p} name="regime" maxLength={64} defaultValue={cur?.legal_regime ?? ""} />}</Field>
          </div>
          <label className="row"><input name="ot" type="checkbox" defaultChecked={cur?.overtime_allowed ?? false} /> Heures supplémentaires autorisées</label>
          <div className="row"><Button type="submit" variant="primary" disabled={!canContract}>Enregistrer</Button><Button onClick={() => setSel(null)}>Annuler</Button>{!canContract && <span className="help">Votre rôle ne permet pas de saisir un contrat.</span>}</div>
        </form>
      </Modal>
    </>
  );
}
