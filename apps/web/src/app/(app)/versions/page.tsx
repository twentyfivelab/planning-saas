"use client";
import { useState } from "react";
import { useMe } from "@/components/Shell";
import { useApi, usePeriod } from "@/components/hooks";
import { Badge, Button, Card, EmptyState, ErrorState, Field, PageHead, Select, SkeletonCard } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

type V = { id: string; number: number; label: string | null; published: boolean; exploratory: boolean; created_at: string; assignments: number };
type Cmp = { changed: { slot_key: string; from: string; to: string }[]; added: string[]; removed: string[]; unchanged: number };

export default function Versions() {
  const me = useMe(); const toast = useToast();
  const { period } = usePeriod();
  const v = useApi<V[]>(period ? `/periods/${period.id}/versions` : null);
  const [a, setA] = useState(""); const [b, setB] = useState(""); const [cmp, setCmp] = useState<Cmp | null>(null);
  async function publish(id: string) { try { await api(`/versions/${id}/publish`, { method: "POST" }); toast.push("Version publiée.", "ok"); v.reload(); } catch (e: any) { toast.push(String(e.message), "bad"); } }
  const fmt = (d: string) => new Date(d).toLocaleString("fr-CH", { timeZone: "Europe/Zurich", dateStyle: "short", timeStyle: "short" });
  return (
    <>
      <PageHead eyebrow={period?.name} title={t("nav.versions")}>
        {me.permissions.includes("planning.edit") && period && <Button variant="primary" icon="plus" onClick={async () => { await api(`/periods/${period.id}/versions`, { method: "POST" }); toast.push("Version créée.", "ok"); v.reload(); }}>Nouvelle version</Button>}
      </PageHead>
      {v.error ? <ErrorState message={v.error} onRetry={v.reload} /> : v.loading && !v.data ? <SkeletonCard lines={4} /> : (
        <>
          <Card title="Historique des versions">
            {!v.data?.length ? <EmptyState icon="history" title="Aucune version">Enregistrez une version depuis le planning pour conserver un état comparable.</EmptyState> : (
              <div className="table-wrap"><table className="table table-cards"><thead><tr><th>N°</th><th>Créée le</th><th>Affectations</th><th>Statut</th><th><span className="sr-only">Action</span></th></tr></thead>
                <tbody>{v.data.map((x) => (
                  <tr key={x.id}><td className="num cell-main"><strong>v{x.number}</strong></td><td className="num" data-label="Créée le">{fmt(x.created_at)}</td><td className="num" data-label="Affectations">{x.assignments}</td>
                    <td data-label="Statut">{x.published ? <Badge tone="ok" icon="check">Publiée</Badge> : x.exploratory ? <Badge tone="warn" icon="alert">Exploratoire · non publiable</Badge> : <Badge tone="info">Brouillon validable</Badge>}</td>
                    <td>{me.permissions.includes("planning.publish") && !x.published && <Button size="sm" onClick={() => publish(x.id)}>Publier</Button>}</td></tr>))}</tbody></table></div>
            )}
          </Card>
          <Card title="Comparer deux versions">
            <div className="row" style={{ alignItems: "flex-end" }}>
              <Field label="Version A">{(p) => <Select {...p} value={a} onChange={(e) => setA(e.target.value)} style={{ minWidth: "9rem" }}><option value="">Choisir…</option>{v.data?.map((x) => <option key={x.id} value={x.id}>v{x.number}</option>)}</Select>}</Field>
              <Field label="Version B">{(p) => <Select {...p} value={b} onChange={(e) => setB(e.target.value)} style={{ minWidth: "9rem" }}><option value="">Choisir…</option>{v.data?.map((x) => <option key={x.id} value={x.id}>v{x.number}</option>)}</Select>}</Field>
              <Button variant="primary" disabled={!a || !b} onClick={async () => setCmp(await api<Cmp>(`/versions/compare?a=${a}&b=${b}`))}>Comparer</Button>
            </div>
            {cmp && (
              <div className="stack" style={{ marginTop: "var(--sp-4)" }} aria-live="polite">
                <div className="row"><Badge tone="accent">{cmp.changed.length} modifiée(s)</Badge><Badge tone="ok">{cmp.added.length} ajoutée(s)</Badge><Badge tone="bad">{cmp.removed.length} retirée(s)</Badge><Badge>{cmp.unchanged} inchangée(s)</Badge></div>
                {cmp.changed.length > 0 && <div className="table-wrap"><table className="table"><thead><tr><th>Shift</th><th>Avant</th><th>Après</th></tr></thead><tbody>{cmp.changed.slice(0, 30).map((c) => <tr key={c.slot_key}><td>{c.slot_key}</td><td>{c.from}</td><td><strong>{c.to}</strong></td></tr>)}</tbody></table></div>}
              </div>
            )}
          </Card>
        </>
      )}
    </>
  );
}
