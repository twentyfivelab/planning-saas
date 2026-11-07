"use client";
import { useMe } from "@/components/Shell";
import { usePeriod } from "@/components/hooks";
import { MonthSwitcher } from "@/components/MonthSwitcher";
import { SitesEditor } from "@/components/planning/SitesEditor";
import { PageHead } from "@/components/ui/primitives";
import { monthLabel } from "@/lib/months";

/** Sites et marques : points de vente, marques et animations (horaires, jours, besoins), modifiables à partir d'un mois. */
export default function Catalog() {
  const me = useMe();
  const { month, setMonth } = usePeriod();
  return (
    <>
      <PageHead eyebrow={`Configuration en vigueur · ${monthLabel(month)}`} title="Sites et marques"><MonthSwitcher month={month} onChange={setMonth} /></PageHead>
      <SitesEditor month={month} canEdit={me.permissions.includes("referential.write")} />
    </>
  );
}
