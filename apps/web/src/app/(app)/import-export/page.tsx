"use client";
import { FormEvent, useState } from "react";
import { Card, Page } from "@/components/Shell";
import { useApi, usePeriod } from "@/components/hooks";
import { api, download } from "@/lib/api";
import { t } from "@/lib/i18n";

export default function ImportExport() {
  const { period } = usePeriod();
  const emps = useApi<{ id: string; name: string }[]>("/employees");
  const [emp, setEmp] = useState(""); const [site, setSite] = useState(""); const [brand, setBrand] = useState("");
  const [file, setFile] = useState<File | null>(null); const [prev, setPrev] = useState<any>(null); const [msg, setMsg] = useState("");
  const qs = new URLSearchParams(Object.entries({ employee_id: emp, site, brand }).filter(([, v]) => v)).toString();
  const exp = (ext: string, extra = "") => download(`/periods/${period!.id}/export.${ext}?${qs}${extra}`, `planning.${ext}`).catch((e) => setMsg(String(e.message)));
  async function send(commit: boolean) {
    if (!file) return; const fd = new FormData(); fd.append("file", file);
    try { setPrev(await api(`/imports/employees?commit=${commit}`, { method: "POST", body: fd })); setMsg(commit ? "Import effectué" : "Aperçu (rien n'est enregistré)"); }
    catch (e: any) { setMsg(String(e.message)); setPrev(e.detail?.report ? { report: e.detail.report } : null); }
  }
  return (
    <Page>
      <h1 className="mb-3 text-2xl font-semibold">{t("nav.io")}</h1>
      <Card title="Exports (filtres actifs appliqués)">
        <div className="mb-3 grid gap-2 sm:grid-cols-3">
          <select aria-label="Collaborateur" className="input" value={emp} onChange={(e) => setEmp(e.target.value)}><option value="">Tous les collaborateurs</option>{emps.data?.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</select>
          <input aria-label="Site" placeholder="Site (ex. GVA3)" className="input" value={site} onChange={(e) => setSite(e.target.value)} />
          <input aria-label="Marque" placeholder="Marque (ex. Cartier)" className="input" value={brand} onChange={(e) => setBrand(e.target.value)} /></div>
        <div className="flex flex-wrap gap-2">
          <button className="btn" onClick={() => exp("pdf")}>PDF</button><button className="btn" onClick={() => exp("xlsx")}>Excel</button><button className="btn" onClick={() => exp("csv")}>CSV</button>
          <button className="btn" disabled={!emp} title="Choisir un collaborateur" onClick={() => exp("ics")}>Calendrier ICS</button></div>
      </Card>
      <Card title="Import collaborateurs (CSV ou Excel)">
        <p className="muted mb-2 text-sm">Colonnes : code, name, brands (ex. « Ploom GVA3:priority;Cartier:reinforce »), weight, unavailable_weekdays (0 = lundi). Taille max 2 Mo.</p>
        <form onSubmit={(e: FormEvent) => { e.preventDefault(); send(false); }} className="flex flex-wrap items-center gap-2">
          <input aria-label="Fichier" type="file" accept=".csv,.xlsx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <button className="btn">Aperçu et validation</button><button type="button" className="btn btn-primary" disabled={!prev || prev.errors > 0} onClick={() => send(true)}>Importer</button></form>
        <p role="status" className="mt-2 text-sm">{msg}</p>
        {prev?.report && <table className="grid mt-2"><thead><tr><th>Ligne</th><th>Code</th><th>Erreurs</th></tr></thead><tbody>{prev.report.map((r: any) => <tr key={r.line}><td>{r.line}</td><td>{r.code}</td><td className={r.errors.length ? "tag-bad" : "tag-ok"}>{r.errors.join(", ") || "OK"}</td></tr>)}</tbody></table>}
      </Card>
    </Page>
  );
}
