"use client";
import { useState } from "react";
import { useApi, usePeriod } from "@/components/hooks";
import { Badge, Button, Callout, Card, Field, Input, PageHead, Select } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/Icon";
import { useToast } from "@/components/ui/Toast";
import { api, download } from "@/lib/api";
import { t } from "@/lib/i18n";

type Report = { line: number; code: string; errors: string[] };
type Preview = { rows?: number; valid?: number; errors?: number; report?: Report[]; committed?: boolean };

export default function ImportExport() {
  const { period } = usePeriod(); const toast = useToast();
  const emps = useApi<{ id: string; name: string }[]>("/employees");
  const [emp, setEmp] = useState(""); const [site, setSite] = useState(""); const [brand, setBrand] = useState("");
  const [file, setFile] = useState<File | null>(null); const [prev, setPrev] = useState<Preview | null>(null); const [busy, setBusy] = useState(false);
  const qs = new URLSearchParams(Object.entries({ employee_id: emp, site, brand }).filter(([, v]) => v)).toString();
  const exp = (ext: string, label: string) => async () => {
    try { await download(`/periods/${period!.id}/export.${ext}?${qs}`, `planning.${ext}`); toast.push(`Export ${label} téléchargé.`, "ok"); } catch (e: any) { toast.push(String(e.message), "bad"); }
  };
  async function send(commit: boolean) {
    if (!file) return; setBusy(true); const fd = new FormData(); fd.append("file", file);
    try { const r = await api<Preview>(`/imports/employees?commit=${commit}`, { method: "POST", body: fd }); setPrev(r); toast.push(commit ? "Import effectué." : "Aperçu prêt : rien n'est enregistré.", commit ? "ok" : "info"); }
    catch (e: any) { toast.push(String(e.message), "bad"); setPrev(e.detail?.report ? { report: e.detail.report, errors: e.detail.report.filter((r: Report) => r.errors.length).length } : null); }
    finally { setBusy(false); }
  }
  return (
    <>
      <PageHead eyebrow="Fichiers et calendriers" title={t("nav.io")} />
      <Card title="Exports" eyebrow="Les filtres choisis sont appliqués côté serveur">
        <div className="toolbar">
          <Field label="Collaborateur">{(p) => <Select {...p} value={emp} onChange={(e) => setEmp(e.target.value)}><option value="">Tous</option>{emps.data?.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</Select>}</Field>
          <Field label="Site" help="Ex. GVA3">{(p) => <Input {...p} value={site} onChange={(e) => setSite(e.target.value)} />}</Field>
          <Field label="Marque" help="Ex. Cartier">{(p) => <Input {...p} value={brand} onChange={(e) => setBrand(e.target.value)} />}</Field>
        </div>
        <div className="row" style={{ marginTop: "var(--sp-4)" }}>
          <Button icon="download" disabled={!period} onClick={exp("pdf", "PDF")}>PDF</Button>
          <Button icon="download" disabled={!period} onClick={exp("xlsx", "Excel")}>Excel</Button>
          <Button icon="download" disabled={!period} onClick={exp("csv", "CSV")}>CSV</Button>
          <Button icon="calendar" disabled={!period || !emp} onClick={exp("ics", "ICS")} title={emp ? undefined : "Choisissez un collaborateur"}>Calendrier ICS</Button>
          {!emp && <span className="help">L&apos;ICS est par collaborateur.</span>}
        </div>
        <p className="help" style={{ marginTop: "var(--sp-3)" }}>L&apos;export Excel contient les feuilles Planning, Collaborateurs, Budgets, Alertes et Hypothèses.</p>
      </Card>
      <Card title="Import des collaborateurs" eyebrow="CSV ou Excel · 2 Mo max · 2 000 lignes max">
        <p className="muted">Colonnes : <code>code</code>, <code>name</code>, <code>brands</code> (ex. « Ploom GVA3:priority;Cartier:reinforce »), <code>weight</code>, <code>unavailable_weekdays</code> (0 = lundi).</p>
        <div className="row" style={{ margin: "var(--sp-3) 0" }}>
          <Field label="Fichier">{(p) => (
            <label className="file" htmlFor={p.id}>
              <input {...p} type="file" accept=".csv,.xlsx" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setPrev(null); }} />
              <span className="btn btn-sm" aria-hidden="true"><Icon name="upload" size={14} />Choisir un fichier</span>
              <span className="name">{file ? file.name : "Aucun fichier choisi (.csv ou .xlsx)"}</span>
            </label>)}</Field>
          <Button icon="search" disabled={!file || busy} onClick={() => send(false)}>Aperçu et validation</Button>
          <Button variant="primary" icon="upload" disabled={!prev || !!prev.errors || prev.committed || busy} onClick={() => send(true)}>Importer</Button>
        </div>
        {prev && (
          <div className="stack" aria-live="polite">
            <div className="row"><Badge>{prev.rows ?? prev.report?.length ?? 0} ligne(s)</Badge><Badge tone="ok">{prev.valid ?? 0} valide(s)</Badge><Badge tone={prev.errors ? "bad" : "ok"}>{prev.errors ?? 0} erreur(s)</Badge>{prev.committed && <Badge tone="ok" icon="check">Importé</Badge>}</div>
            {!!prev.errors && <Callout kind="bad">Corrigez les lignes en erreur puis relancez l&apos;aperçu : l&apos;import est bloqué tant qu&apos;il reste des erreurs.</Callout>}
            {prev.report && <div className="table-wrap"><table className="table"><thead><tr><th>Ligne</th><th>Code</th><th>Résultat</th></tr></thead><tbody>{prev.report.map((r) => <tr key={r.line}><td className="num">{r.line}</td><td>{r.code}</td><td>{r.errors.length ? <span style={{ color: "var(--bad)" }}>{r.errors.join(", ")}</span> : <Badge tone="ok" icon="check">OK</Badge>}</td></tr>)}</tbody></table></div>}
          </div>
        )}
      </Card>
    </>
  );
}
