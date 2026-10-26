"use client";
import { useState } from "react";
import { Card, Page, useMe } from "@/components/Shell";
import { useApi, usePeriod } from "@/components/hooks";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

type V = { id: string; number: number; label: string | null; published: boolean; exploratory: boolean; created_at: string; assignments: number };

export default function Versions() {
  const me = useMe();
  const { period } = usePeriod();
  const v = useApi<V[]>(period ? `/periods/${period.id}/versions` : null);
  const [a, setA] = useState(""); const [b, setB] = useState(""); const [cmp, setCmp] = useState<any>(null); const [msg, setMsg] = useState("");
  async function publish(id: string) { try { await api(`/versions/${id}/publish`, { method: "POST" }); setMsg("Publiée"); v.reload(); } catch (e: any) { setMsg(String(e.message)); } }
  return (
    <Page>
      <h1 className="mb-3 text-2xl font-semibold">{t("nav.versions")}</h1>
      <Card title="Historique des versions" actions={me.permissions.includes("planning.edit") && period ? <button className="btn" onClick={async () => { await api(`/periods/${period.id}/versions`, { method: "POST" }); v.reload(); }}>Nouvelle version</button> : null}>
        <table className="grid"><thead><tr><th>N°</th><th>Créée</th><th>Affectations</th><th>Statut</th><th></th></tr></thead><tbody>
          {(v.data ?? []).map((x) => <tr key={x.id}><td>{x.number}</td><td>{new Date(x.created_at).toLocaleString("fr-CH", { timeZone: "Europe/Zurich" })}</td><td>{x.assignments}</td>
            <td>{x.published ? "publiée" : x.exploratory ? <span className="tag-warn">{t("exploratory")}</span> : "brouillon validable"}</td>
            <td>{me.permissions.includes("planning.publish") && !x.published && <button className="btn" onClick={() => publish(x.id)}>Publier</button>}</td></tr>)}</tbody></table>
        <p role="status" className="mt-2 text-sm">{msg}</p>
      </Card>
      <Card title="Comparer deux versions">
        <div className="flex flex-wrap gap-2">{[[a, setA, "Version A"], [b, setB, "Version B"]].map(([val, set, l]: any) =>
          <select key={l} aria-label={l} className="input w-40" value={val} onChange={(e) => set(e.target.value)}><option value="">{l}</option>{v.data?.map((x) => <option key={x.id} value={x.id}>v{x.number}</option>)}</select>)}
          <button className="btn btn-primary" disabled={!a || !b} onClick={async () => setCmp(await api(`/versions/compare?a=${a}&b=${b}`))}>Comparer</button></div>
        {cmp && <div className="mt-3 text-sm"><p>{cmp.changed.length} modifiée(s) · {cmp.added.length} ajoutée(s) · {cmp.removed.length} retirée(s) · {cmp.unchanged} inchangée(s)</p>
          <ul className="muted">{cmp.changed.slice(0, 20).map((c: any) => <li key={c.slot_key}>{c.slot_key} : {c.from} → {c.to}</li>)}</ul></div>}
      </Card>
    </Page>
  );
}
