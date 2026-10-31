"use client";
import { Badge, Callout, Card } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/Icon";
import type { Counter, SundaySummary } from "@/lib/sundays";

const Tile = ({ label, value, hint, tone }: { label: string; value: number; hint: string; tone?: "bad" | "ok" }) => (
  <div className="surface-2 sun-tile" style={{ padding: "var(--sp-3)" }}>
    <p className="muted" style={{ fontSize: "var(--text-xs)", fontWeight: 600 }}>{label}</p>
    <p className="kpi-value num" aria-live="polite" style={tone ? { color: tone === "bad" ? "var(--bad)" : "var(--ok)" } : undefined}>{value}</p>
    <p className="kpi-sub">{hint}</p>
  </div>
);

/** Compteur des dimanches : recalculé en direct à partir des quotas réels (voir lib/sundays.ts). */
export function SundayCounter({ counter, summary, draftNote }: { counter: Counter; summary: SundaySummary; draftNote?: string }) {
  const sites = Object.entries(summary.by_site).map(([k, v]) => `${k} ${v}`).join(" · ");
  const n = summary.sundays.length;
  return (
    <Card eyebrow={`${n} dimanche${n > 1 ? "s" : ""} · ${summary.per_sunday} shifts par dimanche`} title="Shifts du dimanche"
      actions={draftNote ? <Badge tone="accent" icon="info">{draftNote}</Badge> : undefined}>
      <div className="grid-kpi sun-grid" role="group" aria-label="Compteur des dimanches">
        <Tile label="À couvrir" value={counter.total} hint={sites} />
        <Tile label="Réservés aux collaborateurs" value={counter.reserved} hint="quotas « objectif exact »" />
        <Tile label="Réellement planifiés" value={counter.planned} hint={counter.unplanned > 0 ? `${counter.unplanned} sans collaborateur` : "tous pourvus"} tone={counter.planned > 0 && counter.unplanned === 0 ? "ok" : undefined} />
        <Tile label="Restant à attribuer" value={counter.remaining} hint="à couvrir − réservés" tone={counter.remaining > 0 ? undefined : "ok"} />
      </div>
      {counter.alerts.map((a) => <div key={a.text} style={{ marginTop: "var(--sp-3)" }}><Callout kind={a.level === "warning" ? "warn" : "info"}>{a.text}</Callout></div>)}
      <p className="help" style={{ marginTop: "var(--sp-3)" }}><Icon name="info" size={12} style={{ verticalAlign: "-2px" }} /> Ploom est la seule activité planifiée le dimanche. Un quota « maximum » plafonne sans réserver ; « objectif exact » réserve. Un collaborateur n&apos;a jamais deux shifts le même dimanche.</p>
    </Card>
  );
}

/** Version compacte (planning, tableau de bord) : mêmes chiffres, mis à jour en direct. */
export function SundayStrip({ counter, onDetails }: { counter: Counter; onDetails?: () => void }) {
  const items: [string, number][] = [["à couvrir", counter.total], ["réservés", counter.reserved], ["planifiés", counter.planned], ["restant à attribuer", counter.remaining]];
  return (
    <div className="glass" style={{ padding: "var(--sp-3) var(--sp-4)" }} role="group" aria-label="Compteur des dimanches" aria-live="polite">
      <div className="spread">
        <div className="row" style={{ gap: "var(--sp-2) var(--sp-5)" }}>
          <strong>Dimanches</strong>
          {items.map(([l, v]) => <span key={l} className="num"><b style={{ fontSize: "var(--text-lg)" }}>{v}</b> <span className="muted">{l}</span></span>)}
          {counter.alerts.some((a) => a.level === "warning") && <Badge tone="warn" icon="alert">À vérifier</Badge>}
        </div>
        {onDetails && <button type="button" className="btn btn-sm" onClick={onDetails}>Quotas par collaborateur</button>}
      </div>
    </div>
  );
}
