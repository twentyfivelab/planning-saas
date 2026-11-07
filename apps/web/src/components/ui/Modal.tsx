"use client";
import { useEffect, useId, useRef } from "react";
import type { ReactNode } from "react";
import { Button } from "./primitives";


/** Fenêtre modale basée sur <dialog> : focus piégé, fermeture par Échap, arrière-plan inerte, focus rendu à la fermeture. */
export function Modal({ open, onClose, title, children, description, initialFocusRef, hideClose, variant }: { open: boolean; onClose: () => void; title: string; description?: string; children: ReactNode; initialFocusRef?: React.RefObject<HTMLElement | null>; hideClose?: boolean; variant?: "confirm" }) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  useEffect(() => {
    const d = ref.current; if (!d) return;
    if (open && !d.open) { d.showModal(); initialFocusRef?.current?.focus(); } // immédiat : un focus différé volerait le focus après une frappe de Tab
    if (!open && d.open) d.close();
  }, [open, initialFocusRef]);
  return (
    <dialog ref={ref} className={variant === "confirm" ? "modal modal-confirm" : "modal"} aria-labelledby={`${id}-t`} aria-describedby={description ? `${id}-d` : undefined}
      // une fenêtre imbriquée (ex. « Autoriser » dans « Sites et marques ») ne doit jamais fermer sa fenêtre parente :
      // les événements close/cancel remontent l'arbre React, on ne réagit qu'aux siens
      onClose={(e) => { if (e.target === e.currentTarget) onClose(); }} onCancel={(e) => { if (e.target !== e.currentTarget) return; e.preventDefault(); onClose(); }}
      onClick={(e) => { if (e.target === ref.current) onClose(); }}>
      {open && (
        <div className="modal-body">
          <div className="modal-head">
            <div><h2 id={`${id}-t`} className="h2">{title}</h2>{description && <p id={`${id}-d`} className="muted">{description}</p>}</div>
            {!hideClose && <Button variant="ghost" size="sm" iconOnly icon="x" label="Fermer" onClick={onClose} />}
          </div>
          {children}
        </div>
      )}
    </dialog>
  );
}
