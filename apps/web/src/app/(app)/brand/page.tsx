"use client";
import { useApi, usePeriod } from "@/components/hooks";
import { MonthSwitcher } from "@/components/MonthSwitcher";
import { Badge, Card, EmptyState, ErrorState, PageHead, SkeletonCard } from "@/components/ui/primitives";
import { monthLabel } from "@/lib/months";
import { hourRange, longDate } from "@/lib/reassign";
import type { Assignment } from "@/lib/schedule";
import { fmtH } from "@/lib/wfm";

/** Espace d'un responsable de marque : le serveur ne renvoie que les shifts de ses marques. */
export default function BrandSpace() {
  const { period, month, setMonth } = usePeriod();
  const s = useApi<{ assignments: Assignment[] }>(period ? `/periods/${period.id}/schedule` : null);
  const rows = s.data?.assignments ?? [];
  const total = rows.reduce((x, a) => x + a.effective_minutes, 0);
  return (
    <>
      <PageHead eyebrow={monthLabel(month)} title="Mes marques"><MonthSwitcher month={month} onChange={setMonth} /></PageHead>
      <Card title="Shifts planifiés" actions={<Badge tone="accent">{fmtH(total)}</Badge>}>
        {s.error ? <ErrorState message={s.error} onRetry={s.reload} /> : s.loading && !s.data ? <SkeletonCard lines={5} /> : !rows.length ? <EmptyState icon="calendar" title="Aucun shift">Aucun shift de vos marques sur ce mois.</EmptyState> : (
          <div className="table-wrap"><table className="table table-cards">
            <caption className="sr-only">Shifts de mes marques</caption>
            <thead><tr><th>Date</th><th>Site</th><th>Marque</th><th>Horaire</th><th>Collaborateur</th><th>Travail effectif</th></tr></thead>
            <tbody>{rows.map((a) => <tr key={a.assignment_id}><td className="cell-main">{longDate(a.day)}</td><td data-label="Site">{a.site_name ?? a.site}</td><td data-label="Marque">{Object.keys(a.allocations).join(" + ")}</td><td className="num nowrap" data-label="Horaire">{hourRange(a.start, a.end)}</td><td data-label="Collaborateur">{a.employee}</td><td className="num" data-label="Travail effectif">{fmtH(a.effective_minutes)}</td></tr>)}</tbody>
          </table></div>)}
      </Card>
    </>
  );
}
