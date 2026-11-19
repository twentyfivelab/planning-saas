"use client";
import { useApi } from "@/components/hooks";
import { MyRequests } from "@/components/MyRequests";
import { NotificationsList } from "@/components/NotificationsList";
import { MyOffers } from "@/components/planning/ReplacementProposal";
import { Badge, Card, EmptyState, ErrorState, PageHead, SkeletonCard } from "@/components/ui/primitives";
import { hourRange, longDate } from "@/lib/reassign";
import { fmtH } from "@/lib/wfm";

type Mine = { linked: boolean; employee?: string; periods: { period_id: string; name: string; version: number; published_at: string; minutes: number; shifts: { day: string; site: string; start: string; end: string; break_minutes: number; effective_minutes: number; allocations: Record<string, number> }[] }[] };

/** Espace du collaborateur : uniquement les plannings publiés ; un planning en préparation n'est jamais visible ici. */
export default function MyPlanning() {
  const q = useApi<Mine>("/me/planning");
  return (
    <>
      <PageHead eyebrow={q.data?.employee} title="Mon planning" />
      <MyOffers />
      <NotificationsList empty="Vous serez prévenu·e lorsqu'un planning vous concernant sera publié." />
      {q.data?.linked && <MyRequests />}
      {q.error ? <ErrorState message={q.error} onRetry={q.reload} /> : q.loading && !q.data ? <SkeletonCard lines={4} /> : !q.data?.linked ? (
        <Card><EmptyState icon="users" title="Compte non relié à une fiche">Demandez à votre responsable de relier votre compte à votre fiche collaborateur.</EmptyState></Card>
      ) : !q.data.periods.length ? <Card><EmptyState icon="calendar" title="Aucun planning publié">Votre planning apparaîtra ici dès qu&apos;il sera publié.</EmptyState></Card> : q.data.periods.map((p) => (
        <Card key={p.period_id} title={p.name} eyebrow={`Version publiée n° ${p.version}`} actions={<Badge tone="accent">{fmtH(p.minutes)}</Badge>}>
          {!p.shifts.length ? <p className="muted">Aucun shift ce mois-ci.</p> : (
            <div className="table-wrap"><table className="table table-cards">
              <caption className="sr-only">Mes shifts de {p.name}</caption>
              <thead><tr><th>Date</th><th>Site</th><th>Marque</th><th>Horaire</th><th>Pause</th><th>Travail effectif</th></tr></thead>
              <tbody>{p.shifts.map((s) => <tr key={s.day + s.start}><td className="cell-main">{longDate(s.day)}</td><td data-label="Site">{s.site}</td><td data-label="Marque">{Object.keys(s.allocations ?? {}).join(" + ")}</td><td className="num nowrap" data-label="Horaire">{hourRange(s.start, s.end)}</td><td className="num" data-label="Pause">{s.break_minutes} min</td><td className="num" data-label="Travail effectif">{fmtH(s.effective_minutes)}</td></tr>)}</tbody>
            </table></div>)}
        </Card>))}
    </>
  );
}
