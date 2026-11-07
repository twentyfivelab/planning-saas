"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { invalidate, onInvalidate } from "@/lib/invalidate";
import { defaultMonthKey, isMonthKey, parseMonthKey, shiftMonthKey } from "@/lib/months";

export type Period = { id: string; name: string; start_date: string; end_date: string; status?: import("@/lib/periods").PeriodStatus; status_label?: string; assignments?: number; wizard_step?: number | null; archived_at?: string | null; changed_since?: boolean };

export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(!!path);
  const seq = useRef(0); // seule la réponse de la DERNIÈRE requête est appliquée (changement de mois / de collaborateur en cours de chargement)
  const reload = useCallback(() => {
    if (!path) { setLoading(false); return; }
    const mine = ++seq.current;
    setLoading(true);
    api<T>(path).then((d) => { if (mine === seq.current) { setData(d); setError(null); } }).catch((e) => { if (mine === seq.current) setError(String(e.message ?? e)); }).finally(() => { if (mine === seq.current) setLoading(false); });
  }, [path]);
  const prev = useRef(path);
  useEffect(() => { if (prev.current !== path) { prev.current = path; seq.current++; setData(null); setError(null); } reload(); }, [path, reload]); // nouvelle adresse (autre mois, autre collaborateur) : jamais de données de l'ancienne
  // rechargement silencieux (sans squelette) quand des paramètres changent ailleurs
  useEffect(() => onInvalidate(() => { if (path) { const mine = ++seq.current; api<T>(path).then((d) => { if (mine === seq.current) { setData(d); setError(null); setLoading(false); } }).catch(() => {}); } }), [path]);
  return { data, error, loading, reload, mutate: setData };
}

const MONTH_EVENT = "planning:month-changed";
const MONTH_STORE = "planning:month";
const readMonth = (): string | null => { try { const v = localStorage.getItem(MONTH_STORE); return isMonthKey(v) ? v : null; } catch { return null; } };

/** Mois sélectionné, partagé par toutes les pages (planning général, planning individuel, génération…) et conservé entre les visites. */
export function useMonthState(): [string | null, (m: string) => void] {
  const [m, setM] = useState<string | null>(null);
  useEffect(() => {
    setM(readMonth());
    const fn = () => setM(readMonth());
    window.addEventListener(MONTH_EVENT, fn); window.addEventListener("storage", fn);
    return () => { window.removeEventListener(MONTH_EVENT, fn); window.removeEventListener("storage", fn); };
  }, []);
  const set = useCallback((next: string) => { try { localStorage.setItem(MONTH_STORE, next); } catch {} setM(next); window.dispatchEvent(new Event(MONTH_EVENT)); }, []);
  return [m, set];
}

/**
 * Période du mois sélectionné. Chaque mois a son propre planning ; `period` est null tant que le planning du mois n'existe pas
 * (voir `ensureMonth`). La sélection de mois est partagée entre toutes les pages.
 */
export function usePeriod() {
  const { data: periods, loading, reload } = useApi<Period[]>("/periods");
  const [stored, setMonth] = useMonthState();
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);
  const month = stored ?? defaultMonthKey(periods);
  const period = periods?.find((p) => p.start_date.slice(0, 7) === month && p.start_date.endsWith("-01")) ?? null;
  const shift = useCallback((delta: number) => setMonth(shiftMonthKey(month, delta)), [month, setMonth]);
  const ensure = useCallback(async (): Promise<Period> => {
    const { y, m } = parseMonthKey(month);
    const p = await api<Period>("/periods/ensure", { method: "POST", json: { year: y, month: m } });
    reload(); invalidate();
    return p;
  }, [month, reload]);
  return { periods: periods ?? [], period, month, setMonth, shift, ensure, loading: loading || !ready, reloadPeriods: reload };
}
