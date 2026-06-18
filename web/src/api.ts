// Typed API client. Auth is a server-side session cookie (BFF) — sent
// automatically on same-origin requests; on 401 we bounce to the backend login.

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
  const r = await fetch("/api" + path, { credentials: "same-origin", ...opts });
  if (r.status === 401 && authEnabled) {
    window.location.href = "/api/auth/login";
    return new Promise<T>(() => {}); // halt; navigation underway
  }
  if (!r.ok) {
    const detail = await r.json().catch(() => ({} as any));
    throw new Error(detail.detail || r.statusText);
  }
  return r.json() as Promise<T>;
}
