"use client";
import Link from "next/link";
import { HistoryFeed } from "@/components/HistoryFeed";
import { Modal } from "@/components/ui/Modal";

/** Historique des modifications du planning affiché (filtré sur le collaborateur choisi dans le planning, le cas échéant). */
export function HistoryPanel({ open, periodId, employeeId, onClose }: { open: boolean; periodId: string; employeeId?: string; onClose: () => void }) {
  return (
    <Modal open={open} onClose={onClose} title="Historique des modifications" description={employeeId ? "Modifications de ce planning concernant le collaborateur filtré." : "Modifications de ce planning, de la plus récente à la plus ancienne."}>
      {open && <div className="stack">
        <HistoryFeed periodId={periodId} employeeId={employeeId} filters={false} limit={20} />
        <Link className="btn btn-sm" href={`/history?period=${periodId}${employeeId ? `&employee=${employeeId}` : ""}`}>Ouvrir l&apos;historique complet</Link>
      </div>}
    </Modal>
  );
}
