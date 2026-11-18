"use client";
import { useApi, usePeriod } from "@/components/hooks";
import { Badge, Card, EmptyState, ErrorState, PageHead, Progress, SkeletonCard } from "@/components/ui/primitives";
import { Ring } from "@/components/ui/Charts";
import { brandColor } from "@/lib/brand";
import { budgetProgress, plannedByBrand, type BudgetRow } from "@/lib/metrics";
import { fmtHM, type Assignment } from "@/lib/schedule";
import { t } from "@/lib/i18n";
import { MonthSwitcher } from "@/components/MonthSwitcher";
import { Button } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/Toast";
import { copyPreviousBudgets } from "@/lib/budgetCopy";
import { invalidate } from "@/lib/invalidate";
import { monthLabel } from "@/lib/months";

export default function Budgets() {
  const { period, month, setMonth } = usePeriod(); const toast = useToast();
  const b = useApi<(BudgetRow & { id: string; strict?: boolean })[]>("/budgets");
  const s = useApi<{ assignments: Assignment[] }>(period ? `/periods/${period.id}/schedule` : null);
  const planned = plannedByBrand(s.data?.assignments ?? []);
  const rows = (b.data ?? []).filter((x) => (x as { month?: string }).month === `${month}-01`); // budgets du mois choisi uniquement
  async function copy() {
    try { const n = await copyPreviousBudgets(month); toast.push(n ? `${n} budget(s) copié(s) depuis le mois précédent.` : "Rien à copier.", n ? "ok" : "info"); b.reload(); invalidate(); }
    catch (e: unknown) { toast.push(e instanceof Error ? e.message : "Copie impossible", "bad"); }
  }
  const total = rows.reduce((x, y) => x + y.target_minutes, 0);
  const done = rows.reduce((x, y) => x + (planned[y.brand_code] ?? 0), 0);
  return (
    <>
      <PageHead eyebrow={`Heures de travail effectif · ${monthLabel(month)}`} title={t("nav.budgets")}><MonthSwitcher month={month} onChange={setMonth} /></PageHead>
      {b.error ? <ErrorState message={b.error} onRetry={b.reload} /> : b.loading ? <SkeletonCard lines={6} /> : !rows.length ? (
        <Card><EmptyState icon="wallet" title={`Aucun budget pour ${monthLabel(month)}`} action={<Button onClick={copy}>Copier les budgets du mois précédent</Button>}>Les budgets mensuels par marque se saisissent via l&apos;API (<code>/budgets</code>) ou se copient explicitement depuis le mois précédent : aucun budget n&apos;est jamais inventé.</EmptyState></Card>
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
                return <tr key={x.id}><td className="cell-main nowrap"><span className="row" style={{ flexWrap: "nowrap" }}><i className="dot" style={{ ["--c" as string]: brandColor(x.brand_code) }} /><strong>{x.brand_code}</strong>{x.strict === false && <Badge tone="info">Souple</Badge>}</span></td>
                  <td className="num nowrap" data-label="Budget">{fmtHM(x.target_minutes)}</td><td className="num nowrap" data-label="Planifié">{fmtHM(p)}</td><td className="num nowrap" data-label="Restant">{fmtHM(x.target_minutes - p)}</td>
                  <td data-label="Avancement" style={{ minWidth: "9rem" }}><div className="row" style={{ flexWrap: "nowrap" }}><div style={{ flex: 1, minWidth: "5rem" }}><Progress value={pct} label={`${x.brand_code} : ${pct} %`} color={brandColor(x.brand_code)} /></div><span className="num">{pct} %</span></div></td>
                  <td data-label="Besoins">{x.requirements_defined ? <Badge tone="ok">Définis</Badge> : <Badge tone="warn" icon="alert">{t("to_fill")}</Badge>}</td></tr>; })}</tbody>
            </table></div>
            <p className="help" style={{ marginTop: "var(--sp-3)" }}>{rows.some((x) => !x.requirements_defined) && <>{rows.filter((x) => !x.requirements_defined).map((x) => x.brand_code).join(" et ")} : jours et horaires non définis, donc non planifiables. </>}Le co-branding impute les heures aux deux budgets sans doubler les heures du collaborateur.</p>
          </Card>
        </>
      )}
    </>
  );
}
