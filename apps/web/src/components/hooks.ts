"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

export type Period = { id: string; name: string; start_date: string; end_date: string };

export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => {
    if (!path) return;
    api<T>(path).then((d) => { setData(d); setError(null); }).catch((e) => setError(String(e.message ?? e)));
  }, [path]);
  useEffect(reload, [reload]);
  return { data, error, reload };
}

export function usePeriod() {
  const { data: periods } = useApi<Period[]>("/periods");
  const [id, setId] = useState<string | null>(null);
  useEffect(() => { if (periods?.length && !id) setId(periods[periods.length - 1].id); }, [periods, id]);
  return { periods: periods ?? [], period: periods?.find((p) => p.id === id) ?? null, setId };
}
