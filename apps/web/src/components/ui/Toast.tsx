"use client";
import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Button } from "./primitives";
import { Icon } from "./Icon";

export type ToastKind = "info" | "ok" | "warn" | "bad";
type ToastItem = { id: number; kind: ToastKind; text: string; action?: { label: string; run: () => void } };
type Api = { push: (text: string, kind?: ToastKind, action?: ToastItem["action"]) => void };
const Ctx = createContext<Api>({ push: () => {} });
export const useToast = () => useContext(Ctx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const seq = useRef(0);
  const dismiss = useCallback((id: number) => setItems((l) => l.filter((t) => t.id !== id)), []);
  const push = useCallback<Api["push"]>((text, kind = "info", action) => {
    const id = ++seq.current;
    setItems((l) => [...l.slice(-3), { id, kind, text, action }]);
    setTimeout(() => dismiss(id), action ? 8000 : 5000);
  }, [dismiss]);
  const api = useMemo(() => ({ push }), [push]);
  return (
    <Ctx.Provider value={api}>
      {children}
      <div className="toast-region" role="region" aria-label="Notifications" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className="toast" data-kind={t.kind} role={t.kind === "bad" ? "alert" : "status"}>
            <Icon name={t.kind === "ok" ? "check" : t.kind === "info" ? "info" : "alert"} />
            <p style={{ flex: 1 }}>{t.text}</p>
            {t.action && <Button size="sm" onClick={() => { t.action!.run(); dismiss(t.id); }}>{t.action.label}</Button>}
            <Button size="sm" variant="ghost" iconOnly icon="x" label="Fermer la notification" onClick={() => dismiss(t.id)} />
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
