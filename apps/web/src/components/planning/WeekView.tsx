"use client";
import type { ComponentProps } from "react";
import { Badge, Button, EmptyState } from "@/components/ui/primitives";
import { ShiftCard } from "@/components/ui/ShiftCard";
import { dayLabel, fmtHM, type Assignment } from "@/lib/schedule";

type CardProps = (a: Assignment, size?: "sm" | "lg", showEmployee?: boolean) => ComponentProps<typeof ShiftCard>;
const DOW = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];

function addDays(iso: string, n: number) { const d = new Date(`${iso}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); }
function monday(iso: string) { const wd = (new Date(`${iso}T12:00:00Z`).getUTCDay() + 6) % 7; return addDays(iso, -wd); }

/** Vue semaine : du lundi au dimanche, tous les shifts de chaque jour regroupés par site (filtres du planning appliqués). */
export function WeekView({ anchor, days, list, cardProps, onAnchor }: { anchor: string; days: string[]; list: Assignment[]; cardProps: CardProps; onAnchor: (d: string) => void }) {
  if (!days.length) return null;
  const start = monday(anchor || days[0]);
  const week = Array.from({ length: 7 }, (_, i) => addDays(start, i));
  const inPeriod = new Set(days);
  const first = days[0], last = days[days.length - 1];
  const total = list.filter((a) => week.includes(a.day));
  return (
    <div className="stack" data-testid="week-view">
      <div className="spread">
        <div className="row" role="group" aria-label="Navigation entre les semaines">
          <Button iconOnly icon="chevL" label="Semaine précédente" disabled={start <= first} onClick={() => onAnchor(addDays(start, -7) < first ? first : addDays(start, -7))} />
          <strong className="num" data-testid="week-label">{dayLabel(week[0])} – {dayLabel(week[6])}</strong>
          <Button iconOnly icon="chevR" label="Semaine suivante" disabled={addDays(start, 7) > last} onClick={() => onAnchor(addDays(start, 7))} />
        </div>
        <div className="row"><Badge tone="accent">{total.length} shifts</Badge><Badge>{fmtHM(total.reduce((s, a) => s + a.effective_minutes, 0))}</Badge></div>
      </div>
      {total.length === 0 ? <EmptyState icon="calendar" title="Aucun shift cette semaine">Aucune affectation ne correspond à cette semaine et à ces filtres.</EmptyState> : (
        <div className="cal-scroll"><div className="week-grid" role="grid" aria-label={`Semaine du ${dayLabel(week[0])}`}>
          {week.map((d, i) => {
            const items = list.filter((a) => a.day === d).sort((a, b) => (a.site + a.start).localeCompare(b.site + b.start));
            const sites = [...new Set(items.map((a) => a.site_name ?? a.site))];
            return (
              <div key={d} className="week-col" role="gridcell" data-day={d} data-count={items.length} data-outside={!inPeriod.has(d) || undefined} aria-label={`${dayLabel(d)}, ${items.length} shift(s)`}>
                <div className="week-head"><span>{DOW[i]}</span><span className="num">{Number(d.slice(8))}</span><span className="faint num">{items.length}</span></div>
                {!inPeriod.has(d) ? <p className="faint" style={{ margin: 0 }}>Autre mois</p> : sites.map((s) => (
                  <section key={s} className="week-site" aria-label={s}>
                    <p className="week-site-name">{s}</p>
                    {items.filter((a) => (a.site_name ?? a.site) === s).map((a) => <ShiftCard key={a.assignment_id} {...cardProps(a, "sm", true)} />)}
                  </section>))}
              </div>
            );
          })}
        </div></div>
      )}
    </div>
  );
}
