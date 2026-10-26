"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

export type Period = { id: string; name: string; start_date: string; end_date: string };

export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(!!path);
  const reload = useCallback(() => {
    if (!path) { setLoading(false); return; }
    setLoading(true);
    api<T>(path).then((d) => { setData(d); setError(null); }).catch((e) => setError(String(e.message ?? e))).finally(() => setLoading(false));
  }, [path]);
  useEffect(reload, [reload]);
  return { data, error, loading, reload };
}

export function usePeriod() {
  const { data: periods, loading } = useApi<Period[]>("/periods");
  const [id, setId] = useState<string | null>(null);
  useEffect(() => { if (periods?.length && !id) setId(periods[periods.length - 1].id); }, [periods, id]);
  return { periods: periods ?? [], period: periods?.find((p) => p.id === id) ?? null, setId, loading };
}
