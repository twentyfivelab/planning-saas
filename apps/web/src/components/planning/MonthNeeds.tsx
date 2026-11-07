"use client";
import { Badge, Callout, Card } from "@/components/ui/primitives";
import { brandColor } from "@/lib/brand";
import type { SundaySummary } from "@/lib/sundays";

export type MonthCalendar = {
  year: number; month: number; label: string; start: string; end: string; days: number; weekdays: Record<string, number>; saturdays: number; sundays: number;
  sunday_dates: string[]; shifts_total: number; mandatory_shifts: number; effective_hours: number; sunday_shifts_total: number; sunday_shifts_per_site: Record<string, number>;
  brands: { brand: string; open_days: number; shifts: number }[]; budgets: { brand: string; target_minutes: number }[]; budgets_missing: boolean;
  period_id: string | null; has_period: boolean; assignments: number; has_plan: boolean; sunday: SundaySummary;
};

/** Calendrier et besoins du mois, calculés par le serveur à partir des besoins configurés (aucune valeur propre à un mois précis). */
export function MonthNeeds({ cal, actions }: { cal: MonthCalendar; actions?: React.ReactNode }) {
  const stat = (k: string, v: React.ReactNode) => <div className="surface-2" style={{ padding: "var(--sp-3)" }}><dt className="muted" style={{ fontSize: "var(--text-xs)" }}>{k}</dt><dd className="kpi-value num" style={{ margin: 0, fontSize: "var(--text-xl)" }}>{v}</dd></div>;
  return (
    <Card title={`Calendrier de ${cal.label}`} eyebrow="Calculé automatiquement" actions={actions}>
      <div className="stack">
        <dl style={{ margin: 0, display: "grid", gap: "var(--sp-3)", gridTemplateColumns: "repeat(auto-fit, minmax(8rem, 1fr))" }}>
          {stat("Jours", cal.days)}{stat("Samedis", cal.saturdays)}{stat("Dimanches", cal.sundays)}{stat("Shifts à pourvoir", cal.shifts_total)}
          {stat("Shifts du dimanche", cal.sunday_shifts_total)}{stat("Heures effectives", `${cal.effective_hours} h`)}
        </dl>
        <p className="help" data-testid="sunday-formula">
          {cal.sundays} dimanche{cal.sundays > 1 ? "s" : ""} × {cal.sundays ? cal.sunday_shifts_total / cal.sundays : 0} shifts = <strong>{cal.sunday_shifts_total}</strong> shifts du dimanche
          {Object.keys(cal.sunday_shifts_per_site).length > 0 && <> ({Object.entries(cal.sunday_shifts_per_site).map(([s, n]) => `${s} : ${cal.sundays ? n / cal.sundays : n}/dimanche`).join(", ")})</>}.
        </p>
        <div className="row">{cal.brands.map((b) => <Badge key={b.brand}><i className="dot" style={{ ["--c" as string]: brandColor(b.brand) }} />{b.brand} · {b.open_days} j · {b.shifts} shifts</Badge>)}</div>
        {cal.budgets_missing && <Callout kind="warn" title={`Aucun budget défini pour ${cal.label}`}>Le moteur n&apos;invente jamais de budget : sans budget mensuel, les marques à shifts optionnels ne sont pas complétées et le résultat est signalé comme incomplet.</Callout>}
      </div>
    </Card>
  );
}
