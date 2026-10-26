"use client";
import { FormEvent, useState } from "react";
import { Card, Page, useMe } from "@/components/Shell";
import { useApi } from "@/components/hooks";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

type Emp = { id: string; code: string; name: string; brands: Record<string, string>; allocation_weight: number };
type Contract = { id: string; employee_id: string; activity_rate: number | null; monthly_max_minutes: number | null };

export default function Employees() {
  const me = useMe();
  const emps = useApi<Emp[]>("/employees");
  const contracts = useApi<Contract[]>("/contracts");
  const [sel, setSel] = useState<string>("");
  const [msg, setMsg] = useState("");
  const canContract = me.permissions.includes("contracts.write");
  const has = (id: string) => contracts.data?.some((c) => c.employee_id === id);
  const num = (f: FormData, k: string) => { const v = f.get(k); return v === null || v === "" ? null : Number(v); };

  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); const f = new FormData(e.currentTarget);
    try {
      await api("/contracts", { method: "POST", json: {
        employee_id: sel, start_date: f.get("start") || null, end_date: f.get("end") || null,
        activity_rate: num(f, "rate") === null ? null : num(f, "rate")! / 100,
        weekly_minutes: num(f, "weekly") === null ? null : num(f, "weekly")! * 60,
        monthly_min_minutes: num(f, "min") === null ? null : num(f, "min")! * 60,
        monthly_max_minutes: num(f, "max") === null ? null : num(f, "max")! * 60,
        overtime_allowed: f.get("ot") === "on" } });
      setMsg("Contrat enregistré"); contracts.reload();
    } catch (err: any) { setMsg(String(err.message)); }
  }
  return (
    <Page>
      <h1 className="mb-3 text-2xl font-semibold">{t("nav.employees")}</h1>
      <Card title="Collaborateurs">
        <div className="overflow-x-auto"><table className="grid"><thead><tr><th>Nom</th><th>Marques (niveau)</th><th>Poids</th><th>Contrat</th><th></th></tr></thead><tbody>
          {(emps.data ?? []).map((e) => <tr key={e.id}><td>{e.name}</td>
            <td>{Object.entries(e.brands).map(([b, l]) => `${b} (${l === "priority" ? "prioritaire" : "renfort"})`).join(", ")}</td>
            <td>{e.allocation_weight}</td>
            <td>{has(e.id) ? "saisi" : <span className="tag-warn">{t("to_fill")}</span>}</td>
            <td><button className="btn" onClick={() => setSel(e.id)}>Saisir le contrat</button></td></tr>)}
        </tbody></table></div>
      </Card>
      {sel && <Card title={`Contrat — ${emps.data?.find((e) => e.id === sel)?.name}`}>
        <p className="muted mb-2 text-sm">Laisser vide ce qui n'est pas connu : aucune valeur n'est supposée.</p>
        <form onSubmit={save} className="grid gap-2 sm:grid-cols-3">
          {[["start", "Date de début", "date"], ["end", "Date de fin", "date"], ["rate", "Taux d'activité (%)", "number"], ["weekly", "Heures hebdomadaires", "number"],
            ["min", "Minimum mensuel (h)", "number"], ["max", "Maximum mensuel (h)", "number"]].map(([n, l, ty]) =>
            <label key={n} className="text-sm">{l}<input name={n} type={ty} step="any" className="input mt-1" /></label>)}
          <label className="flex items-center gap-2 text-sm"><input name="ot" type="checkbox" /> Heures supplémentaires autorisées</label>
          <div><button className="btn btn-primary" disabled={!canContract}>Enregistrer</button> <span role="status">{msg}</span></div>
        </form>
      </Card>}
    </Page>
  );
}
