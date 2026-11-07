"use client";
import { useState } from "react";
import { Button } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/Icon";
import { DOW_SHORT, dayLabel } from "@/lib/schedule";
import { addRange, isBlockedByRule, monthOf, shiftMonth, toggleDate } from "@/lib/calendar";

/** Calendrier interactif : un clic bascule l'indisponibilité d'un jour, Maj + clic sélectionne une plage. Enregistrement automatique (parent). */
export function UnavailabilityCalendar({ dates, anchor, weekdays, leaves, status, onChange }: {
  dates: string[]; anchor: string; weekdays: number[]; leaves: { start: string; end: string }[]; status: "idle" | "saving" | "saved" | "error";
  onChange: (next: string[]) => void;
}) {
  const [cursor, setCursor] = useState(anchor);
  const [last, setLast] = useState<string | null>(null);
  const month = monthOf(cursor);
  const set = new Set(dates);
  const inMonth = dates.filter((d) => d.startsWith(month.key));
  const click = (iso: string, shift: boolean) => {
    onChange(shift && last ? addRange(dates, last, iso) : toggleDate(dates, iso));
    setLast(iso);
  };
  return (
    <div className="cal-unav">
      <div className="spread">
        <div className="row">
          <Button size="sm" iconOnly icon="chevL" label="Mois précédent" onClick={() => setCursor(shiftMonth(cursor, -1))} />
          <strong aria-live="polite" style={{ minWidth: "9rem", textAlign: "center" }}>{month.label}</strong>
          <Button size="sm" iconOnly icon="chevR" label="Mois suivant" onClick={() => setCursor(shiftMonth(cursor, 1))} />
        </div>
        <span className="help" role="status" aria-live="polite">
          {status === "saving" ? "Enregistrement…" : status === "saved" ? <><Icon name="check" size={12} style={{ verticalAlign: "-2px" }} /> Enregistré automatiquement</> : status === "error" ? "Échec de l'enregistrement" : "Cliquez sur un jour pour le bloquer"}
        </span>
      </div>
      <table className="unav-grid" role="grid" aria-label={`Jours d'indisponibilité, ${month.label}`}>
        <thead><tr>{DOW_SHORT.map((d) => <th key={d} scope="col">{d}</th>)}</tr></thead>
        <tbody>
          {month.weeks.map((w, i) => (
            <tr key={i}>{w.map((c, j) => {
              if (!c) return <td key={j} />;
              const on = set.has(c.iso), rule = isBlockedByRule(c.iso, weekdays, leaves);
              return (
                <td key={j}>
                  <button type="button" className="unav-day" aria-pressed={on} data-rule={rule || undefined}
                    aria-label={`${dayLabel(c.iso)} ${c.iso.slice(0, 4)}${on ? ", indisponible" : ""}${rule ? ", déjà bloqué par une règle récurrente ou un congé" : ""}`}
                    title={rule ? "Déjà indisponible (règle récurrente ou congé)" : undefined}
                    onClick={(e) => click(c.iso, e.shiftKey)}>
                    {c.day}{on && <Icon name="x" size={11} />}
                  </button>
                </td>
              );
            })}</tr>
          ))}
        </tbody>
      </table>
      <div className="spread">
        <p className="help"><b>{dates.length}</b> jour{dates.length > 1 ? "s" : ""} indisponible{dates.length > 1 ? "s" : ""} au total{inMonth.length ? ` · ${inMonth.map((d) => Number(d.slice(8))).join(", ")} ${month.label.split(" ")[0].toLowerCase()}` : ""}. Maj + clic : plage.</p>
        {dates.length > 0 && <Button size="sm" variant="ghost" icon="x" onClick={() => onChange([])}>Tout effacer</Button>}
      </div>
    </div>
  );
}
