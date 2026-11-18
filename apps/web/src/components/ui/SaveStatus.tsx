"use client";
import { Button } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/Icon";
import type { SaveState } from "@/lib/saveQueue";

/** État réel de l'enregistrement automatique : « Enregistrement… », « Enregistré » (confirmé par le serveur) ou l'erreur, avec « Réessayer ». */
export function SaveStatus({ state, error, onRetry, confirmed = 0 }: { state: SaveState; error?: string; onRetry?: () => void; confirmed?: number }) {
  return (
    <span className="save-status row" role="status" aria-live="polite" data-save-state={state} data-save-confirmed={confirmed}>
      {state === "saving" && <span className="muted">Enregistrement…</span>}
      {state === "saved" && <span className="ok-text"><Icon name="check" size={14} /> Enregistré</span>}
      {state === "error" && <>
        <span className="bad-text">Échec de l&apos;enregistrement{error ? ` : ${error}` : ""}</span>
        {onRetry && <Button size="sm" onClick={onRetry}>Réessayer</Button>}
      </>}
    </span>
  );
}
