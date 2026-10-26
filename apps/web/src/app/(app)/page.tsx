"use client";
import Link from "next/link";
import { useMemo } from "react";
import { useApi, usePeriod } from "@/components/hooks";
import { Badge, Callout, Card, EmptyState, ErrorState, PageHead, SkeletonCard } from "@/components/ui/primitives";
import { BarList, Ring } from "@/components/ui/Charts";
import { Icon } from "@/components/ui/Icon";
import { brandColor } from "@/lib/brand";
import { budgetProgress, coverageRate, equityIndicator, hoursByEmployee, plannedByBrand, type BudgetRow } from "@/lib/metrics";
import { issueTitle } from "@/lib/issues";
import { fmtHM, type Assignment } from "@/lib/schedule";

type Schedule = { assignments: Assignment[]; uncovered: unknown[] };
type Issue = { code: string; severity: string; message: string };
type Run = { id: string; status: string; result_status: string | null; mode: string | null; duration_s: number | null };

export default function Dashboard() {
  const { period, loading: pl } = usePeriod();
  const sched = useApi<Schedule>(period ? `/periods/${period.id}/schedule` : null);
  const conf = useApi<{ hard_violations: string[] }>(period ? `/periods/${period.id}/conflicts` : null);
  const budgets = useApi<BudgetRow[]>("/budgets");
  const runs = useApi<Run[]>("/runs");
  const last = runs.data?.find((r) => r.status === "termine") ?? runs.data?.[0];
  const diag = useApi<{ report: { missing_data: Issue[]; diagnostics: Issue[] } }>(last?.status === "termine" ? `/runs/${last.id}/diagnostic` : null);

  const a = useMemo(() => sched.data?.assignments ?? [], [sched.data]);
  const planned = useMemo(() => plannedByBrand(a), [a]);
  const emp = useMemo(() => hoursByEmployee(a), [a]);
  const totalPlanned = a.reduce((s, x) => s + x.effective_minutes, 0);
  const totalBudget = (budgets.data ?? []).reduce((s, b) => s + b.target_minutes, 0);
  const unplannable = (budgets.data ?? []).filter((b) => !b.requirements_defined);
  const unplannableMin = unplannable.reduce((s, b) => s + b.target_minutes, 0);
  const uncovered = sched.data?.uncovered.length ?? 0;
  const cover = coverageRate(a.length, uncovered);
  const eq = equityIndicator(emp.map((e) => e.minutes));
  const violations = conf.data?.hard_violations.length ?? 0;
  const issues = [...(diag.data?.report.diagnostics ?? []), ...(diag.data?.report.missing_data ?? [])];
  const important = issues.filter((i) => i.severity === "blocking" || i.severity === "warning");
  const hypotheses = issues.filter((i) => i.code === "HYPOTHESIS" || i.code === "LEGAL_REVIEW");
  const loading = pl || (sched.loading && !sched.data) || (budgets.loading && !budgets.data);

  return (
    <>
      <PageHead eyebrow={period?.name} title="Tableau de bord">
        <Link href="/generate" className="btn btn-primary"><Icon name="sparkles" size={16} />Générer le planning</Link>
        <Link href="/planning" className="btn"><Icon name="calendar" size={16} />Ouvrir le planning</Link>
      </PageHead>

      {sched.error || budgets.error ? <ErrorState message={(sched.error || budgets.error)!} onRetry={() => { sched.reload(); budgets.reload(); }} /> : loading ? (
        <div className="grid-kpi"><SkeletonCard /><SkeletonCard /><SkeletonCard /><SkeletonCard /></div>
      ) : !a.length ? (
        <Card><EmptyState icon="sparkles" title="Pas encore de planning" action={<Link href="/generate" className="btn btn-primary">Lancer une simulation</Link>}>Aucune affectation pour cette période. Une génération produit une proposition exploratoire tant que contrats et besoins sont incomplets.</EmptyState></Card>
      ) : (
        <>
          <div className="grid-kpi">
            <Card eyebrow="Budget (travail effectif)" title="Heures planifiées" lift>
              <div className="row" style={{ gap: "var(--sp-4)", flexWrap: "nowrap" }}>
                <Ring value={budgetProgress(totalPlanned, totalBudget)} label="Budget planifié" size={96} stroke={10}><span className="kpi-value num" style={{ fontSize: "var(--text-lg)" }}>{budgetProgress(totalPlanned, totalBudget)} %</span></Ring>
                <div><p className="kpi-value">{fmtHM(totalPlanned)}</p><p className="kpi-sub">sur {fmtHM(totalBudget)} de budget déclaré</p></div>
              </div>
            </Card>
            <Card eyebrow="Shifts" title="Taux de couverture" lift>
              <div className="row" style={{ gap: "var(--sp-4)", flexWrap: "nowrap" }}>
                <Ring value={(cover ?? 0) * 100} label="Taux de couverture des shifts" size={96} stroke={10} color="var(--ok)"><span className="kpi-value num" style={{ fontSize: "var(--text-lg)" }}>{cover === null ? "–" : `${Math.round(cover * 100)} %`}</span></Ring>
                <div><p className="kpi-value num">{a.length}</p><p className="kpi-sub">shifts couverts · {uncovered} non couvert{uncovered > 1 ? "s" : ""} (shifts définis)</p></div>
              </div>
            </Card>
            <Card eyebrow="Contraintes dures" title="Conflits" lift>
              <p className="kpi-value num" style={{ color: violations ? "var(--bad)" : "var(--ok)" }}><Icon name={violations ? "alert" : "check"} size={22} style={{ verticalAlign: "-3px", marginRight: 6 }} />{conf.data ? violations : "–"}</p>
              <p className="kpi-sub">{violations ? "Voir Alertes pour le détail" : "Aucune violation détectée par le vérificateur"}</p>
            </Card>
            <Card eyebrow="Dernière génération" title="Statut" lift>
              <p className="kpi-value" style={{ fontSize: "var(--text-lg)", textTransform: "capitalize" }}>{last?.result_status?.replace(/_/g, " ") ?? last?.status ?? "Aucune"}</p>
              <div className="row" style={{ marginTop: "var(--sp-2)" }}>{last?.mode === "simulation_exploratoire" && <Badge tone="warn" icon="alert">Exploratoire · non validable</Badge>}{last?.duration_s != null && <Badge>{last.duration_s} s</Badge>}</div>
            </Card>
          </div>

          {unplannable.length > 0 && (
            <Callout kind="warn" title={`${fmtHM(unplannableMin)} non planifiables : besoins non définis`}>
              {unplannable.map((b) => b.brand_code).join(" et ")} : jours et horaires à renseigner. Ces heures ne sont pas comptées comme couvertes et ne sont pas inventées.
            </Callout>
          )}

          <div className="grid-2">
            <Card title="Heures par marque" eyebrow="Planifié / budget">
              <BarList data={(budgets.data ?? []).map((b) => ({ key: b.brand_code, label: b.brand_code, value: (planned[b.brand_code] ?? 0) / 60, max: b.target_minutes / 60, color: brandColor(b.brand_code), right: `${fmtHM(planned[b.brand_code] ?? 0)} / ${fmtHM(b.target_minutes)}`, note: !b.requirements_defined ? <Badge tone="warn">À renseigner</Badge> : undefined }))} />
            </Card>
            <Card title="Heures par collaborateur" eyebrow="Travail effectif">
              <BarList data={emp.slice(0, 12).map((e) => ({ key: e.id, label: e.name, value: e.minutes / 60, max: emp[0].minutes / 60, right: fmtHM(e.minutes), note: <span className="muted">· {e.days} j</span> }))} />
              {emp.length > 12 && <p className="help" style={{ marginTop: "var(--sp-2)" }}>+ {emp.length - 12} autres collaborateurs</p>}
            </Card>
          </div>

          <div className="grid-2">
            <Card title="Équité de répartition" eyebrow="Indicateur indicatif">
              {eq ? (
                <>
                  <p className="kpi-value num">{(eq.cv * 100).toFixed(0)} %</p>
                  <p className="kpi-sub">dispersion des heures (écart-type / moyenne) · de {fmtHM(eq.min)} à {fmtHM(eq.max)} par collaborateur</p>
                  <Callout kind="info"><span>Indicatif seulement : sans contrats ni disponibilités complètes, l&apos;équité ne peut pas être évaluée relativement aux heures contractuelles. Les poids d&apos;attribution (Sahra, Mila, Abdu…) sont des préférences souples.</span></Callout>
                </>
              ) : <EmptyState icon="users" title="Pas assez de données">Au moins deux collaborateurs planifiés sont nécessaires.</EmptyState>}
            </Card>
            <Card title="Alertes importantes" eyebrow="Dernier diagnostic" actions={<Link href="/alerts" className="btn btn-sm">Tout voir</Link>}>
              {important.length === 0 && !violations ? <EmptyState icon="check" title="Aucune alerte importante">Aucun avertissement dans le dernier diagnostic.</EmptyState> : (
                <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                  {violations > 0 && <li><Badge tone="bad" icon="alert">{violations} conflit(s) dur(s)</Badge></li>}
                  {important.slice(0, 5).map((i, n) => <li key={n} className="stack" style={{ gap: "var(--sp-1)" }}><span><Badge tone={i.severity === "blocking" ? "bad" : "warn"}>{issueTitle(i.code)}</Badge></span><span className="muted">{i.message.length > 150 ? `${i.message.slice(0, 150)}…` : i.message}</span></li>)}
                </ul>
              )}
            </Card>
          </div>

          <Card title="Hypothèses et contraintes non validées" eyebrow="À lire avant toute décision">
            <ul className="stack" style={{ margin: 0, paddingLeft: "1.1rem" }}>
              {(hypotheses.length ? hypotheses : [{ code: "À renseigner", message: "Contrats individuels, disponibilités complètes, congés, besoins Lindt/Toblerone ; validation juridique des règles de repos et de durée." }] as Issue[]).map((i, n) => <li key={n} className="muted" style={{ color: "var(--fg)" }}>{i.message}</li>)}
            </ul>
          </Card>
        </>
      )}
    </>
  );
}
