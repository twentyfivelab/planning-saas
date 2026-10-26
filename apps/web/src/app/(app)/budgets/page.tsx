"use client";
import { useApi, usePeriod } from "@/components/hooks";
import { Badge, Card, EmptyState, ErrorState, PageHead, Progress, SkeletonCard } from "@/components/ui/primitives";
import { Ring } from "@/components/ui/Charts";
import { brandColor } from "@/lib/brand";
import { budgetProgress, plannedByBrand, type BudgetRow } from "@/lib/metrics";
import { fmtHM, type Assignment } from "@/lib/schedule";
import { t } from "@/lib/i18n";

export default function Budgets() {
  const { period } = usePeriod();
  const b = useApi<(BudgetRow & { id: string })[]>("/budgets");
  const s = useApi<{ assignments: Assignment[] }>(period ? `/periods/${period.id}/schedule` : null);
  const planned = plannedByBrand(s.data?.assignments ?? []);
  const rows = b.data ?? [];
  const total = rows.reduce((x, y) => x + y.target_minutes, 0);
  const done = rows.reduce((x, y) => x + (planned[y.brand_code] ?? 0), 0);
  return (
    <>
      <PageHead eyebrow="Heures de travail effectif" title={t("nav.budgets")} />
      {b.error ? <ErrorState message={b.error} onRetry={b.reload} /> : b.loading ? <SkeletonCard lines={6} /> : !rows.length ? (
        <Card><EmptyState icon="wallet" title="Aucun budget saisi">Les budgets mensuels par marque se saisissent via l&apos;API (<code>/budgets</code>).</EmptyState></Card>
      ) : (
        <>
          <Card lift><div className="row" style={{ gap: "var(--sp-5)" }}>
            <Ring value={budgetProgress(done, total)} label="Budget total planifié" size={120}><span className="kpi-value num" style={{ fontSize: "var(--text-xl)" }}>{budgetProgress(done, total)} %</span></Ring>
            <div><p className="eyebrow">Total</p><p className="kpi-value">{fmtHM(done)} <span className="muted" style={{ fontSize: "var(--text-md)" }}>/ {fmtHM(total)}</span></p><p className="kpi-sub">Restant : {fmtHM(total - done)}</p></div>
          </div></Card>
          <Card title="Budgets par marque">
            <div className="table-wrap"><table className="table table-cards">
              <thead><tr><th>Marque</th><th>Budget</th><th>Planifié</th><th>Restant</th><th style={{ minWidth: "10rem" }}>Avancement</th><th>Besoins</th></tr></thead>
              <tbody>{rows.map((x) => { const p = planned[x.brand_code] ?? 0; const pct = budgetProgress(p, x.target_minutes);
                return <tr key={x.id}><td className="cell-main nowrap"><span className="row" style={{ flexWrap: "nowrap" }}><i className="dot" style={{ ["--c" as string]: brandColor(x.brand_code) }} /><strong>{x.brand_code}</strong></span></td>
                  <td className="num nowrap" data-label="Budget">{fmtHM(x.target_minutes)}</td><td className="num nowrap" data-label="Planifié">{fmtHM(p)}</td><td className="num nowrap" data-label="Restant">{fmtHM(x.target_minutes - p)}</td>
                  <td data-label="Avancement" style={{ minWidth: "9rem" }}><div className="row" style={{ flexWrap: "nowrap" }}><div style={{ flex: 1, minWidth: "5rem" }}><Progress value={pct} label={`${x.brand_code} : ${pct} %`} color={brandColor(x.brand_code)} /></div><span className="num">{pct} %</span></div></td>
                  <td data-label="Besoins">{x.requirements_defined ? <Badge tone="ok">Définis</Badge> : <Badge tone="warn" icon="alert">{t("to_fill")}</Badge>}</td></tr>; })}</tbody>
            </table></div>
            <p className="help" style={{ marginTop: "var(--sp-3)" }}>Lindt et Toblerone : jours et horaires non définis, donc non planifiables. Le co-branding impute les heures aux deux budgets sans doubler les heures du collaborateur.</p>
          </Card>
        </>
      )}
    </>
  );
}
