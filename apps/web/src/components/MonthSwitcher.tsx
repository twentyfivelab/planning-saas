"use client";
import { Button, Select } from "@/components/ui/primitives";
import { MONTHS_FR, monthKey, parseMonthKey, shiftMonthKey } from "@/lib/months";

/** Sélecteur de mois et d'année (listes déroulantes + flèches précédent / suivant). Le changement d'année est automatique. */
export function MonthSwitcher({ month, onChange }: { month: string; onChange: (m: string) => void }) {
  const { y, m } = parseMonthKey(month);
  const thisYear = new Date().getFullYear();
  const from = Math.min(thisYear - 3, y), to = Math.max(thisYear + 8, y);
  const years = Array.from({ length: to - from + 1 }, (_, i) => from + i);
  return (
    <div className="month-switch" role="group" aria-label="Choix du mois">
      <Button iconOnly icon="chevL" label="Mois précédent" onClick={() => onChange(shiftMonthKey(month, -1))} />
      <Select aria-label="Mois" value={m} onChange={(e) => onChange(monthKey(y, Number(e.target.value)))}>
        {MONTHS_FR.map((l, i) => <option key={l} value={i + 1}>{l}</option>)}
      </Select>
      <Select aria-label="Année" value={y} onChange={(e) => onChange(monthKey(Number(e.target.value), m))}>
        {years.map((v) => <option key={v} value={v}>{v}</option>)}
      </Select>
      <Button iconOnly icon="chevR" label="Mois suivant" onClick={() => onChange(shiftMonthKey(month, 1))} />
    </div>
  );
}
