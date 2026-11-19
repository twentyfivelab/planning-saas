"use client";
import { NotificationsList } from "@/components/NotificationsList";
import { PageHead } from "@/components/ui/primitives";

/** Notifications des responsables du planning : couverture des marques ajoutées manuellement, révisions proposées, demandes. */
export default function NotificationsPage() {
  return (
    <>
      <PageHead eyebrow="Planning" title="Notifications" />
      <NotificationsList empty="Vous serez prévenu·e ici, par exemple lorsque tous les besoins d'une marque ajoutée manuellement sont couverts, ou s'ils cessent de l'être." />
    </>
  );
}
