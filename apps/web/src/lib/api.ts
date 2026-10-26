const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

let csrf = "";
export function setCsrf(v: string) { csrf = v; try { sessionStorage.setItem("csrf", v); } catch {} }
function loadCsrf() { if (!csrf) { try { csrf = sessionStorage.getItem("csrf") ?? ""; } catch {} } return csrf; }

export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) { super(typeof detail === "string" ? detail : `HTTP ${status}`); }
}

export async function api<T = any>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  if (init.json !== undefined) headers["Content-Type"] = "application/json";
  const m = (init.method ?? "GET").toUpperCase();
  if (m !== "GET") headers["X-CSRF-Token"] = loadCsrf();
  let res: Response;
  try { res = await fetch(BASE + path, { ...init, headers, credentials: "include", body: init.json !== undefined ? JSON.stringify(init.json) : init.body }); }
  catch { throw new ApiError(0, "Le serveur est injoignable. Vérifiez votre connexion puis réessayez."); }
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") ?? "";
  const data = ct.includes("json") ? await res.json() : await res.text();
  if (!res.ok) throw new ApiError(res.status, (data as any)?.detail ?? data);
  return data as T;
}

export async function download(path: string, filename: string) {
  let res: Response;
  try { res = await fetch(BASE + path, { credentials: "include" }); } catch { throw new ApiError(0, "Le serveur est injoignable. Vérifiez votre connexion puis réessayez."); }
  if (!res.ok) throw new ApiError(res.status, "Export refusé");
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a"); a.href = url; a.download = filename; a.click(); URL.revokeObjectURL(url);
}
