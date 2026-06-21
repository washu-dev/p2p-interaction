// Typed API client. Auth is a server-side session cookie (BFF) — sent
// automatically on same-origin requests; on 401 we bounce to the backend login.
//
// VITE_API_BASE_URL: optional env var injected at build time.
//   Unset (dev)  → all /api/* calls are relative, proxied by Vite to localhost:8000.
//   Set  (prod)  → prepended to every /api/* call so the browser targets the
//                  real backend (e.g. https://d5j3l1rgzmla.cloudfront.net).
const _BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

/** Build a full URL for /api/<path> — safe for both fetch() and href/src. */
export const apiUrl = (path: string) => `${_BASE}/api${path}`;

export interface Stage {
  key: string;
  label: string;
  status: string;
  error?: string | null;
}

export interface JobSettings {
  binder_name: string;
  chains: string;
  target_hotspot_residues: string;
  length_min: number;
  length_max: number;
  number_of_final_designs: number;
  filters_preset: string;
  advanced_preset: string;
  targets: string[];
}

export interface Job {
  id: string;
  name: string;
  status: string;
  input_type: "fasta" | "pdb";
  target_name: string;
  settings: JobSettings;
  stages: Stage[];
  error?: string | null;
  created_at: number;
  updated_at: number;
}

export interface AppConfig {
  mode: string;
  filters: string[];
  advanced: string[];
  kinases: string[];
}

let authEnabled = false;
export function setAuthEnabled(v: boolean) {
  authEnabled = v;
}

export async function api<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  const r = await fetch(apiUrl(path), { credentials: "include", ...opts });
  if (r.status === 401 && authEnabled) {
    window.location.href = apiUrl("/auth/login");
    return new Promise<T>(() => {}); // halt; navigation underway
  }
  if (!r.ok) {
    const detail = await r.json().catch(() => ({} as any));
    throw new Error(detail.detail || r.statusText);
  }
  return r.json() as Promise<T>;
}
