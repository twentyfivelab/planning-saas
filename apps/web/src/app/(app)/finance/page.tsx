"use client";
import { useState } from "react";
import { useMe } from "@/components/Shell";
import { useApi, usePeriod } from "@/components/hooks";
import { MonthSwitcher } from "@/components/MonthSwitcher";
import { Badge, Button, Callout, Card, EmptyState, ErrorState, PageHead, SkeletonCard } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/Toast";
import { download } from "@/lib/api";
import { monthLabel } from "@/lib/months";
import { errText, fmtCHF, fmtH } from "@/lib/wfm";

type Line = { key: string; name: string; client?: string | null; status?: string; requested_minutes: number | null; planned_minutes: number; actual_minutes: number; validated_minutes: number; remaining_minutes: number | null; overtime_minutes: number; absent_minutes: number;
  cost_planned_cents: number | null; cost_actual_cents: number | null; billable_planned_cents: number | null; billable_actual_cents: number | null; margin_planned_cents: number | null; margin_actual_cents: number | null; cost_missing_minutes: number; bill_missing_minutes: number; complete: boolean };
type Report = { month: string; see_money: boolean; by_client: Line[]; by_brand: Line[]; by_mission: Line[]; by_site: Line[] };
const TABS = [["by_client", "Clients"], ["by_brand", "Marques"], ["by_mission", "Missions"], ["by_site", "Sites"]] as const;
const money = (c: number | null) => fmtCHF(c) ?? <span className="faint">Non renseigné</span>;

/** Heures et rentabilité : tout est recalculé ; un coût ou un tarif inconnu reste « Non renseigné », jamais estimé. */
export default function Finance() {
  const me = useMe(); const toast = useToast();
  const { month, setMonth } = usePeriod();
  const r = useApi<Report>(`/reports/finance?month=${month}`);
  const [tab, setTab] = useState<(typeof TABS)[number][0]>("by_client");
  const lines = r.data?.[tab] ?? [];
  const canExport = me.permissions.includes("export.run");
  const money_ = !!r.data?.see_money;
  const missing = lines.filter((l) => l.cost_missing_minutes > 0 || l.bill_missing_minutes > 0);
  async function dl(path: string, name: string) { try { await download(path, name); } catch (e) { toast.push(errText(e), "bad"); } }
  return (
    <>
      <PageHead eyebrow={monthLabel(month)} title="Rentabilité"><MonthSwitcher month={month} onChange={setMonth} /></PageHead>
      <Card title="Heures et montants" actions={canExport ? <div className="row">
        <Button size="sm" icon="download" onClick={() => dl(`/reports/payroll.csv?month=${month}`, `paie-${month}.csv`)}>Paie</Button>
        {money_ && <Button size="sm" icon="download" onClick={() => dl(`/reports/billing.csv?month=${month}`, `facturation-${month}.csv`)}>Facturation</Button>}
        <Button size="sm" icon="download" onClick={() => dl(`/reports/coverage.csv?month=${month}`, `couverture-${month}.csv`)}>Couverture</Button></div> : undefined}>
        <div className="seg" role="tablist" aria-label="Regroupement">{TABS.map(([k, l]) => <button key={k} type="button" role="tab" aria-selected={tab === k} className="btn" onClick={() => setTab(k)}>{l}</button>)}</div>
        {r.error ? <ErrorState message={r.error} onRetry={r.reload} /> : r.loading && !r.data ? <SkeletonCard lines={5} /> : !lines.length ? <EmptyState icon="wallet" title="Aucune donnée">Aucun shift planifié pour ce regroupement ce mois-ci.</EmptyState> : (
          <div className="table-wrap" style={{ marginTop: "var(--sp-3)" }}><table className="table table-cards" aria-label="Heures et rentabilité">
            <thead><tr><th>Nom</th><th>Demandé</th><th>Planifié</th><th>Effectué</th><th>Validé</th><th>Restant</th><th>Au-delà du prévu</th>{money_ && <><th>Coût prévisionnel</th><th>Coût réel</th><th>Facturable prévu</th><th>Facturable réalisé</th><th>Marge prévue</th><th>Marge réalisée</th></>}</tr></thead>
            <tbody>{lines.map((l) => (
              <tr key={l.key}><td className="cell-main"><strong>{l.name}</strong>{l.client && tab !== "by_client" && <span className="faint"> · {l.client}</span>}</td>
                <td className="num nowrap" data-label="Demandé">{l.requested_minutes === null ? <span className="faint">Non renseigné</span> : fmtH(l.requested_minutes)}</td>
                <td className="num nowrap" data-label="Planifié">{fmtH(l.planned_minutes)}</td><td className="num nowrap" data-label="Effectué">{fmtH(l.actual_minutes)}</td><td className="num nowrap" data-label="Validé">{fmtH(l.validated_minutes)}</td>
                <td className="num nowrap" data-label="Restant">{l.remaining_minutes === null ? "—" : fmtH(l.remaining_minutes)}</td><td className="num nowrap" data-label="Au-delà du prévu">{fmtH(l.overtime_minutes)}</td>
                {money_ && <><td className="num nowrap" data-label="Coût prévisionnel">{money(l.cost_planned_cents)}</td><td className="num nowrap" data-label="Coût réel">{money(l.cost_actual_cents)}</td><td className="num nowrap" data-label="Facturable prévu">{money(l.billable_planned_cents)}</td><td className="num nowrap" data-label="Facturable réalisé">{money(l.billable_actual_cents)}</td><td className="num nowrap" data-label="Marge prévue">{money(l.margin_planned_cents)}</td><td className="num nowrap" data-label="Marge réalisée">{money(l.margin_actual_cents)}</td></>}
              </tr>))}</tbody>
          </table></div>
        )}
        {!money_ && <p className="help" style={{ marginTop: "var(--sp-3)" }}>Votre rôle donne accès aux heures, pas aux montants.</p>}
      </Card>
      {money_ && missing.length > 0 && (
        <Callout kind="info" title="Données financières incomplètes">
          <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>{missing.slice(0, 8).map((l) => <li key={l.key}><strong>{l.name}</strong> : {l.cost_missing_minutes > 0 && `${fmtH(l.cost_missing_minutes)} sans coût horaire (contrat)`}{l.cost_missing_minutes > 0 && l.bill_missing_minutes > 0 && " · "}{l.bill_missing_minutes > 0 && `${fmtH(l.bill_missing_minutes)} sans tarif (client, marque ou mission)`}</li>)}</ul>
          <p className="help" style={{ margin: "var(--sp-2) 0 0" }}>Les marges ne portent que sur les heures dont le coût et le tarif sont connus. <Badge>Aucun montant n&apos;est supposé</Badge></p>
        </Callout>)}
    </>
  );
}
