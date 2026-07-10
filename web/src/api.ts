// API client — SPA auth via MSAL.js bearer tokens.
// Pass the access token acquired from MSAL on every call.
const _BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

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

export interface UniprotCandidate {
  accession: string;
  entry_id: string;
  reviewed: boolean;
  protein_name: string;
  gene_names: string;
  organism: string;
  length: string;
  domains: string;
}

export interface LibraryTarget {
  id: string;
  name: string;
  input_type: "fasta" | "pdb";
  source: "uniprot" | "upload";
  accession: string;
  organism: string;
  file_name: string;
  sequence_preview: string;
  submitted_by: string;
  created_at: number;
}

export async function api<T = any>(
  path: string,
  token: string,
  opts: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    ...(opts.headers as Record<string, string> | undefined),
  };
  const r = await fetch(apiUrl(path), { ...opts, headers });
  if (!r.ok) {
    const detail = await r.json().catch(() => ({} as any));
    throw new Error(detail.detail || r.statusText);
  }
  return r.json() as Promise<T>;
}
