import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { useIsAuthenticated, useMsal } from "@azure/msal-react";
import { InteractionStatus } from "@azure/msal-browser";
import { loginRequest, API_SCOPE } from "./auth/msalConfig";
import { api, apiUrl, type AppConfig, type Job, type UniprotCandidate, type LibraryTarget } from "./api";

const STEPS = [
  "Home", "Upload", "Structure Prediction", "Binder Design",
  "Selectivity Screening", "Visualization", "Download",
];

type Validation = { ok: boolean; msg: string } | null;

const DEFAULT_SETTINGS = {
  name: "", binder_name: "", chains: "A", target_hotspot_residues: "",
  length_min: 65, length_max: 150, number_of_final_designs: 100,
  filters_preset: "", advanced_preset: "", make_public: false,
};

function validateFasta(text: string): { ok: boolean; msg: string } {
  if (!text.trim()) return { ok: false, msg: "File is empty." };
  if (!text.includes(">")) return { ok: false, msg: "No FASTA header (line starting with '>') found." };
  let records = 0, residues = 0, bad = false;
  for (const line of text.split(/\r?\n/)) {
    if (line.startsWith(">")) records++;
    else if (line.trim()) {
      residues += line.trim().length;
      if (/[^A-Za-z:*\-\s]/.test(line.trim())) bad = true;
    }
  }
  if (records === 0) return { ok: false, msg: "No sequence records found." };
  if (bad) return { ok: false, msg: "Sequence contains unexpected characters." };
  return { ok: true, msg: `Valid FASTA · ${records} record(s) · ${residues} residues.` };
}

export default function App() {
  const { instance, accounts, inProgress } = useMsal();
  const isAuthenticated = useIsAuthenticated();

  const [mode, setMode] = useState<"simple" | "advanced">("simple");
  const [step, setStep] = useState("Home");
  const [cfg, setCfg] = useState<AppConfig>({ mode: "…", filters: [], advanced: [], kinases: [] });
  const [file, setFile] = useState<File | null>(null);
  const [fileText, setFileText] = useState<string | null>(null);
  const [inputType, setInputType] = useState<"fasta" | "pdb" | null>(null);
  const [validation, setValidation] = useState<Validation>(null);
  const [settings, setSettings] = useState({ ...DEFAULT_SETTINGS });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [cached, setCached] = useState<Job | null>(null);
  const [runErr, setRunErr] = useState("");
  const [logText, setLogText] = useState<string | null>(null);
  const [library, setLibrary] = useState<any[]>([]);
  const [libQ, setLibQ] = useState("");
  const [libKinase, setLibKinase] = useState("");

  // ---- kinase search / shared target library (Upload step) ----
  const [uploadTab, setUploadTab] = useState<"search" | "library" | "file">("search");
  const [kinaseQuery, setKinaseQuery] = useState("");
  const [organism, setOrganism] = useState("Homo sapiens");
  const [searching, setSearching] = useState(false);
  const [searchErr, setSearchErr] = useState("");
  const [candidates, setCandidates] = useState<UniprotCandidate[]>([]);
  const [fetchingAcc, setFetchingAcc] = useState<string | null>(null);
  const [targetLibrary, setTargetLibrary] = useState<LibraryTarget[]>([]);
  const [targetLibQ, setTargetLibQ] = useState("");
  const [libLoading, setLibLoading] = useState(false);
  const [usingTargetId, setUsingTargetId] = useState<string | null>(null);
  const [uploadNote, setUploadNote] = useState<string | null>(null);
  // Which candidate/library entry is the currently-selected target (for highlighting + the organism label).
  const [targetMeta, setTargetMeta] = useState<{ accession?: string; organism?: string } | null>(null);

  const fileInput = useRef<HTMLInputElement>(null);
  const pdbInput = useRef<HTMLInputElement>(null);

  const account = accounts[0] ?? null;
  const userName = account?.name || account?.username || "signed in";

  const getToken = useCallback(async (): Promise<string> => {
    if (!account) throw new Error("not signed in");
    const result = await instance.acquireTokenSilent({ scopes: [API_SCOPE], account });
    return result.accessToken;
  }, [instance, account]);

  // ---- bootstrap + polling ----
  useEffect(() => {
    if (!isAuthenticated) return;
    loadConfig();
    const t = setInterval(refreshJobs, 3000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated]);

  async function loadConfig() {
    try {
      const token = await getToken();
      const c = await api<AppConfig>("/config", token);
      setApiError(null);
      setCfg(c);
      setSelected(new Set(c.kinases));
      setSettings((s) => ({
        ...s,
        filters_preset: s.filters_preset || c.filters[0] || "default_filters",
        advanced_preset: s.advanced_preset || c.advanced.find((a) => a.includes("default")) || c.advanced[0] || "default_4stage_multimer",
      }));
      refreshJobs();
    } catch (e: any) {
      setApiError(e.message || "unreachable");
    }
  }

  async function refreshJobs() {
    try {
      const token = await getToken();
      const { jobs } = await api<{ jobs: Job[] }>("/jobs", token);
      setApiError((prev) => (prev ? null : prev));
      setJobs(jobs);
    } catch { /* ignore transient poll errors */ }
  }

  async function loadLibrary() {
    try {
      const token = await getToken();
      const r = await api<{ results: any[] }>(
        `/library?q=${encodeURIComponent(libQ)}&kinase=${encodeURIComponent(libKinase)}`,
        token,
      );
      setLibrary(r.results || []);
    } catch { /* ignore */ }
  }
  function openLibrary() { setStep("Library"); loadLibrary(); }

  const job = useMemo(() => jobs.find((j) => j.id === jobId) || null, [jobs, jobId]);
  const idx = STEPS.indexOf(step);
  const panelCount = selected.size;
  const lenBad = settings.length_min > settings.length_max;

  // ---- handlers ----
  function setField(k: string, v: any) { setSettings((s) => ({ ...s, [k]: v })); }
  function toggleKinase(k: string, on: boolean) {
    setSelected((prev) => { const n = new Set(prev); if (on) { n.add(k); } else { n.delete(k); } return n; });
  }
  function onFile(f: File | null) {
    if (!f) return;
    setFile(f);
    const ext = (f.name.split(".").pop() || "").toLowerCase();
    const it = ["pdb", "ent"].includes(ext) ? "pdb" : "fasta";
    setInputType(it);
    setSettings((s) => (s.binder_name ? s : { ...s, binder_name: f.name.replace(/\.[^.]+$/, "") }));
    if (it === "fasta") {
      const reader = new FileReader();
      reader.onload = () => { const t = String(reader.result); setFileText(t); setValidation(validateFasta(t)); };
      reader.readAsText(f);
    } else { setFileText(null); setValidation({ ok: true, msg: "PDB structure file accepted." }); }
  }

  // ---- kinase search (UniProt) ----
  // orgOverride lets the Simple search run with no organism filter (shows every
  // species/origin as its own row) without disturbing the Advanced tab's organism field.
  async function searchUniprot(orgOverride?: string, size = 5) {
    if (!kinaseQuery.trim()) return;
    setSearching(true); setSearchErr(""); setCandidates([]);
    try {
      const token = await getToken();
      const org = orgOverride === undefined ? organism.trim() : orgOverride;
      const r = await api<{ candidates: UniprotCandidate[] }>(
        `/uniprot/search?q=${encodeURIComponent(kinaseQuery.trim())}&organism=${encodeURIComponent(org)}&size=${size}`,
        token,
      );
      setCandidates(r.candidates || []);
      if ((r.candidates || []).length === 0) setSearchErr(`No UniProt results for "${kinaseQuery}".`);
    } catch (e: any) { setSearchErr(e.message || "search failed"); }
    finally { setSearching(false); }
  }

  async function useUniprotCandidate(c: UniprotCandidate) {
    setFetchingAcc(c.accession); setUploadNote(null);
    try {
      const token = await getToken();
      const name = kinaseQuery.trim() || c.gene_names.split(/\s+/)[0] || c.accession;
      const r = await api<{ target: LibraryTarget; fasta_text: string }>("/targets/fetch", token, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ accession: c.accession, name, organism: c.organism }),
      });
      onFile(new File([r.fasta_text], `${r.target.name}.fasta`, { type: "text/plain" }));
      setTargetMeta({ accession: c.accession, organism: c.organism });
      setUploadNote(`Downloaded ${r.target.name}.fasta (${c.accession}) and saved it to the shared library.`);
    } catch (e: any) { setSearchErr(e.message || "download failed"); }
    finally { setFetchingAcc(null); }
  }

  // ---- shared target library (browse & reuse) ----
  async function loadTargetLibrary() {
    setLibLoading(true);
    try {
      const token = await getToken();
      const r = await api<{ targets: LibraryTarget[] }>(`/targets?q=${encodeURIComponent(targetLibQ)}`, token);
      setTargetLibrary(r.targets || []);
    } catch { /* ignore */ }
    finally { setLibLoading(false); }
  }

  async function useLibraryTarget(t: LibraryTarget) {
    setUsingTargetId(t.id); setUploadNote(null);
    try {
      const token = await getToken();
      const res = await fetch(apiUrl(`/targets/${t.id}/file`), { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) throw new Error(await res.text().catch(() => res.statusText));
      const blob = await res.blob();
      onFile(new File([blob], t.file_name, { type: t.input_type === "fasta" ? "text/plain" : "chemical/x-pdb" }));
      setTargetMeta({ accession: t.accession, organism: t.organism });
      setUploadNote(`Using ${t.file_name} from the shared library (added by ${t.submitted_by}).`);
    } catch (e: any) { setUploadNote(e.message || "failed to load target"); }
    finally { setUsingTargetId(null); }
  }

  // ---- direct upload -> also saved to the shared target library ----
  async function onFileAndShare(f: File | null) {
    if (!f) return;
    onFile(f);
    setUploadNote(null);
    setTargetMeta(null);
    try {
      const token = await getToken();
      const fd = new FormData();
      fd.append("file", f);
      fd.append("name", f.name.replace(/\.[^.]+$/, ""));
      const r = await api<{ target: LibraryTarget }>("/targets/upload", token, { method: "POST", body: fd });
      setUploadNote(`Saved ${r.target.file_name} to the shared library.`);
    } catch (e: any) { setUploadNote(e.message || "could not save to shared library"); }
  }

  async function runPipeline(force: boolean) {
    setRunErr("");
    if (!file) return setRunErr("Upload a target first.");
    const fd = new FormData();
    fd.append("file", file);
    fd.append("payload", JSON.stringify({
      name: settings.name || null,
      target_name: file.name.replace(/\.[^.]+$/, ""),
      binder_name: settings.binder_name.trim(),
      chains: settings.chains.trim() || "A",
      target_hotspot_residues: settings.target_hotspot_residues.trim(),
      length_min: settings.length_min, length_max: settings.length_max,
      number_of_final_designs: settings.number_of_final_designs,
      filters_preset: settings.filters_preset, advanced_preset: settings.advanced_preset,
      targets: [...selected], make_public: settings.make_public, force,
    }));
    try {
      const token = await getToken();
      const res = await api<any>("/jobs", token, { method: "POST", body: fd });
      if (res.cache_hit) { setCached(res.job); return; }
      setJobId(res.job.id); setStep("Visualization"); refreshJobs();
    } catch (e: any) { setRunErr(e.message); }
  }

  async function showLogs(id: string) {
    setLogText("loading…");
    try {
      const token = await getToken();
      setLogText((await api<any>(`/jobs/${id}/logs`, token)).logs);
    } catch (e: any) { setLogText(e.message); }
  }
  async function cancelJob(id: string) {
    try {
      const token = await getToken();
      await api(`/jobs/${id}/cancel`, token, { method: "POST" });
    } catch { }
    refreshJobs();
  }

  function download(name: string, text: string) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    a.download = name; a.click(); URL.revokeObjectURL(a.href);
  }
  async function downloadLogs(id: string) {
    try {
      const token = await getToken();
      download(`run_logs_${id}.txt`, (await api<any>(`/jobs/${id}/logs`, token)).logs);
    } catch (e: any) { alert(e.message); }
  }
  function downloadSummary(j: Job) {
    const s = j.settings;
    download(`summary_${j.id}.txt`, [
      "BindCraft Selective Binder Platform — Run Summary", "=".repeat(50), "",
      `Run name:        ${j.name}`, `Target:          ${j.target_name} (${j.input_type})`,
      `Status:          ${j.status}`, `Binder name:     ${s.binder_name}`, `Chains:          ${s.chains}`,
      `Hotspots:        ${s.target_hotspot_residues || "(none)"}`,
      `Binder length:   ${s.length_min}-${s.length_max}`, `Final designs:   ${s.number_of_final_designs}`,
      `Filters preset:  ${s.filters_preset}`, `Advanced preset: ${s.advanced_preset}`,
      `Kinase panel:    ${(s.targets || []).join(", ")}`, "",
      `Stages:          ${(j.stages || []).map((x) => x.key + ":" + x.status).join("  ")}`,
    ].join("\n"));
  }

  function reset() {
    setFile(null); setFileText(null); setInputType(null); setValidation(null); setJobId(null); setTargetMeta(null);
    setSelected(new Set(cfg.kinases));
    setSettings((s) => ({ ...s, binder_name: "", name: "", target_hotspot_residues: "" }));
    setStep("Home");
  }

  // ---- small render helpers ----
  const Header = ({ title, desc }: { title: string; desc: string }) => (
    <>
      <span className="chip">STEP {idx + 1} OF {STEPS.length}</span>
      <h1 className="title">{title}</h1>
      <p className="sub">{desc}</p>
    </>
  );
  const Footer = ({ prev, next, ok = true, label }: { prev?: string; next?: string; ok?: boolean; label?: string }) => (
    <div className="footer-nav">
      {prev ? <button className="btn ghost" onClick={() => setStep(prev)}>← {prev}</button> : <span />}
      {next ? <button className="btn" disabled={!ok} onClick={() => setStep(next)}>{label || "Continue to " + next} →</button> : <span />}
    </div>
  );
  const Missing = ({ msg, target }: { msg: string; target: string }) => (
    <>
      <Header title={step} desc="" />
      <div className="panel"><div className="note warn">{msg}</div>
        <div style={{ marginTop: 14 }}><button className="btn" onClick={() => setStep(target)}>Go to {target}</button></div>
      </div>
    </>
  );

  // ---- landing page (unauthenticated) ----
  if (inProgress === InteractionStatus.None && !isAuthenticated) {
    return (
      <div className="layout" style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh" }}>
        <div style={{ maxWidth: 480, width: "100%", padding: "0 24px", textAlign: "center" }}>
          <h1 style={{ fontSize: "2rem", marginBottom: 8 }}>🧬 Selective Binder Platform</h1>
          <p style={{ color: "var(--muted)", marginBottom: 32 }}>
            Design kinase binders from a sequence or structure, then profile their selectivity.
            Sign in with your WashU account to continue.
          </p>
          <button
            className="btn"
            style={{ fontSize: "1rem", padding: "12px 32px" }}
            onClick={() => instance.loginRedirect(loginRequest)}
          >
            Login with WashU SSO
          </button>
        </div>
      </div>
    );
  }

  // ---- auth in progress ----
  if (inProgress !== InteractionStatus.None || !isAuthenticated) {
    return (
      <div className="layout" style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh" }}>
        <div style={{ textAlign: "center", color: "var(--muted)" }}>Signing in…</div>
      </div>
    );
  }

  // ---- Simple mode: one screen — search, run, watch, download ----
  function changeTarget() {
    setFile(null); setFileText(null); setInputType(null); setValidation(null);
    setCandidates([]); setUploadNote(null); setJobId(null); setTargetMeta(null);
  }

  function pageSimple() {
    const stages = job?.stages || [];
    return (
      <div className="simple-shell">
        <div className="simple-topbar">
          <div className="row" style={{ gap: 8 }}><span style={{ fontSize: 22 }}>🧬</span><b>Selective Binder Platform</b></div>
          <div className="row">
            <span className="small" style={{ color: "var(--muted)" }}>👤 {userName}</span>
            <button className="btn ghost" onClick={() => setMode("advanced")}>⚙️ Advanced</button>
            <button className="btn ghost" onClick={() => instance.logoutRedirect()}>Sign out</button>
          </div>
        </div>

        <div className="simple-wrap">
          <div className="hero" style={{ textAlign: "center" }}>
            <h1>Find a kinase, then design a binder</h1>
            <p>Type a kinase name, pick the right species, and click Run — no setup needed.</p>
          </div>

          {apiError && <div className="note err" style={{ marginBottom: 16 }}>
            <b>Can't reach the backend.</b> {apiError}
          </div>}

          <div className="panel">
            <div className="row" style={{ gap: 10 }}>
              <input type="text" placeholder="e.g. LATS1, NDR1, PDL1" value={kinaseQuery}
                onChange={(e) => setKinaseQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && searchUniprot("", 10)}
                style={{ fontSize: 16, padding: "12px 14px", flex: 1 }} />
              <button className="btn" disabled={!kinaseQuery.trim() || searching} onClick={() => searchUniprot("", 10)}>
                {searching ? "Searching…" : "🔍 Search"}
              </button>
              <button className="btn run" disabled={!file} onClick={() => runPipeline(false)}>🚀 Run Pipeline</button>
            </div>

            {searchErr && <div className="note err" style={{ marginTop: 12 }}>{searchErr}</div>}

            {candidates.length > 0 && (
              <div style={{ marginTop: 14 }}>
                <div className="small" style={{ color: "var(--muted)", marginBottom: 8 }}>Pick the species/entry you want:</div>
                <table>
                  <thead><tr><th>Accession</th><th>Protein</th><th>Organism</th><th /></tr></thead>
                  <tbody>
                    {candidates.map((c) => {
                      const isSelected = targetMeta?.accession === c.accession;
                      return (
                        <tr key={c.accession + c.organism}>
                          <td><b>{c.accession}</b>{c.reviewed && <span className="badge b-COMPLETED" style={{ marginLeft: 6 }}>reviewed</span>}</td>
                          <td className="small">{c.protein_name}</td>
                          <td className="small">{c.organism}</td>
                          <td>
                            <button className={"btn" + (isSelected ? "" : " ghost")} disabled={fetchingAcc === c.accession}
                              onClick={() => useUniprotCandidate(c)}>
                              {fetchingAcc === c.accession ? "Downloading…" : isSelected ? "✓ Selected" : "Use this"}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {file && (
              <div className="note ok" style={{ marginTop: 14, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
                <span>✅ Target ready: <b>{file.name.replace(/\.[^.]+$/, "")}</b>
                  {targetMeta?.organism && <b> ({targetMeta.organism})</b>} ({inputType?.toUpperCase()}) — click <b>Run Pipeline</b> above.</span>
                <button className="btn ghost" onClick={changeTarget}>Change target</button>
              </div>
            )}
            {uploadNote && <div className="note info" style={{ marginTop: 10 }}>{uploadNote}</div>}
            {runErr && <div className="note err" style={{ marginTop: 12 }}>{runErr}</div>}
          </div>

          {job && (
            <div className="panel">
              <div className="row" style={{ marginBottom: 10 }}>
                <span className={"badge b-" + job.status}>{job.status}</span>
                <span className="small" style={{ color: "var(--muted)" }}>{job.target_name} · {stages.length} stages</span>
                <span className="spacer" />
                {(job.status === "PENDING" || job.status === "RUNNING") && <button className="btn ghost" onClick={() => cancelJob(job.id)}>Cancel</button>}
              </div>
              <div className="stages">
                {stages.map((s, i) => (
                  <div className="stage" key={s.key}>
                    <div className="col">
                      <span className={"dot " + s.status} />
                      {i < stages.length - 1 && <span className={"line" + (s.status === "COMPLETED" ? " done" : "")} />}
                    </div>
                    <div className="body"><div className="lbl">{s.label}</div><span className={"badge b-" + s.status}>{s.status}</span></div>
                  </div>
                ))}
              </div>
              {job.status === "COMPLETED" && (
                <div style={{ marginTop: 14 }}>
                  <h3 style={{ color: "var(--ink)" }}>Selectivity result</h3>
                  <img className="result" src={apiUrl(`/jobs/${job.id}/result.png?t=${job.updated_at}`)} alt="ipTM vs kinase plot" />
                  <div className="row" style={{ marginTop: 14 }}>
                    <a className="btn" href={apiUrl(`/jobs/${job.id}/result.png`)} download={`iptm_${job.target_name}.png`}>Download plot</a>
                    <button className="btn ghost" onClick={() => downloadLogs(job.id)}>Download logs</button>
                    <button className="btn ghost" onClick={() => downloadSummary(job)}>Download summary</button>
                  </div>
                </div>
              )}
              {job.status === "FAILED" && <div className="note err" style={{ marginTop: 12 }}>{job.error || "A stage failed."}</div>}
              {(job.status === "PENDING" || job.status === "RUNNING") && <div className="note info" style={{ marginTop: 12 }}><span className="spinner" /> Running automatically — this updates on its own.</div>}
            </div>
          )}

          <div className="row" style={{ justifyContent: "center", marginTop: 6 }}>
            <button className="btn ghost" onClick={() => setMode("advanced")}>Need more control? Open Advanced settings →</button>
          </div>
        </div>

        {cached && (
          <div className="modal-bg">
            <div className="modal">
              <h3>Identical run already exists</h3>
              <p><b>{cached.name}</b> was already run with this exact target file and settings on
                {" " + new Date(cached.created_at * 1000).toLocaleString()}. Reuse that result, or run it again?</p>
              <div className="row" style={{ marginTop: 18 }}>
                <button className="btn" onClick={() => { setJobId(cached.id); setCached(null); }}>Use existing result</button>
                <button className="btn ghost" onClick={() => { setCached(null); runPipeline(true); }}>Run again</button>
                <span className="spacer" />
                <button className="btn ghost" onClick={() => setCached(null)}>Cancel</button>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  // ---- pages ----
  function pageHome() {
    const tiles = [
      ["01", "FASTA / PDB Upload", "Provide a target sequence or structure."],
      ["02", "Structure Prediction", "Fold a FASTA target into a PDB (ColabFold)."],
      ["03", "Binder Design", "Generate candidate binders with BindCraft."],
      ["04", "Selectivity Screening", "Profile the top binder across a kinase panel."],
      ["05", "Visualization", "Watch progress and inspect the ipTM plot."],
      ["06", "Download", "Export the plot, logs, and a run summary."],
    ];
    return (
      <>
        <div className="hero">
          <h1>Sequence-to-Selective-Binder Platform</h1>
          <p>Design kinase binders from a sequence or structure, then profile their selectivity.</p>
        </div>
        <div className="panel">
          <div className="note info">Backend mode: <b>{cfg.mode}</b>. Each run is submitted to the cluster as a
            staged pipeline; identical re-runs are served from the result cache.</div>
          <h3 style={{ color: "var(--ink)" }}>From target to ranked selectivity plot</h3>
          <div className="cards">
            {tiles.map(([n, t, d]) => (
              <div className="card" key={n}><span className="chip">{n}</span><h4>{t}</h4><div className="small">{d}</div></div>
            ))}
          </div>
          <div className="row" style={{ marginTop: 18 }}><button className="btn" onClick={() => setStep("Upload")}>Start a new design →</button></div>
        </div>
      </>
    );
  }

  function pageUpload() {
    const ok = !!file && (inputType === "pdb" || (validation?.ok ?? false));
    const tabs: [typeof uploadTab, string][] = [
      ["search", "🔍 Search kinase (UniProt)"],
      ["library", "📚 Shared library"],
      ["file", "📄 Upload file"],
    ];
    return (
      <>
        <Header title="Choose a Target" desc="Search a kinase by name, reuse a target someone already added, or upload your own FASTA/PDB." />
        <div className="panel">
          <div className="row" style={{ marginBottom: 16, gap: 6 }}>
            {tabs.map(([key, label]) => (
              <button key={key} className={"btn" + (uploadTab === key ? "" : " ghost")}
                onClick={() => { setUploadTab(key); if (key === "library") loadTargetLibrary(); }}>
                {label}
              </button>
            ))}
          </div>

          {uploadTab === "search" && (
            <div>
              <div className="grid2">
                <div>
                  <label>Kinase / protein name</label>
                  <input type="text" value={kinaseQuery} placeholder="e.g. LATS1, NDR1"
                    onChange={(e) => setKinaseQuery(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && searchUniprot()} />
                </div>
                <div>
                  <label>Organism</label>
                  <input type="text" value={organism} onChange={(e) => setOrganism(e.target.value)} />
                </div>
              </div>
              <div className="row" style={{ marginTop: 12 }}>
                <button className="btn" disabled={!kinaseQuery.trim() || searching} onClick={() => searchUniprot()}>
                  {searching ? "Searching…" : "Search UniProt"}
                </button>
                <span className="small" style={{ color: "var(--muted)" }}>Looks up UniProtKB and prefers reviewed (Swiss-Prot) entries.</span>
              </div>
              {searchErr && <div className="note err" style={{ marginTop: 12 }}>{searchErr}</div>}
              {candidates.length > 0 && (
                <table style={{ marginTop: 14 }}>
                  <thead><tr><th>Accession</th><th>Protein</th><th>Genes</th><th>Organism</th><th>Length</th><th /></tr></thead>
                  <tbody>
                    {candidates.map((c) => {
                      const isSelected = targetMeta?.accession === c.accession;
                      return (
                        <tr key={c.accession}>
                          <td><b>{c.accession}</b>{c.reviewed && <span className="badge b-COMPLETED" style={{ marginLeft: 6 }}>reviewed</span>}</td>
                          <td className="small">{c.protein_name}</td>
                          <td className="small">{c.gene_names}</td>
                          <td className="small">{c.organism}</td>
                          <td className="small">{c.length} aa</td>
                          <td>
                            <button className={"btn" + (isSelected ? "" : " ghost")} disabled={fetchingAcc === c.accession}
                              onClick={() => useUniprotCandidate(c)}>
                              {fetchingAcc === c.accession ? "Downloading…" : isSelected ? "✓ Selected" : "Download"}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {uploadTab === "library" && (
            <div>
              <div className="row" style={{ marginBottom: 12 }}>
                <input type="text" placeholder="Filter by name or accession…" value={targetLibQ}
                  onChange={(e) => setTargetLibQ(e.target.value)} style={{ maxWidth: 280 }}
                  onKeyDown={(e) => e.key === "Enter" && loadTargetLibrary()} />
                <button className="btn ghost" onClick={loadTargetLibrary}>{libLoading ? "Loading…" : "Refresh"}</button>
              </div>
              {targetLibrary.length === 0 ? (
                <div className="empty" style={{ color: "var(--muted)" }}>
                  {libLoading ? "Loading…" : "No shared targets yet — search a kinase or upload a file to add one."}
                </div>
              ) : (
                <table>
                  <thead><tr><th>Name</th><th>Type</th><th>Source</th><th>Added by</th><th /></tr></thead>
                  <tbody>
                    {targetLibrary.map((t) => (
                      <tr key={t.id}>
                        <td><b>{t.name}</b>{t.accession && <span className="small" style={{ color: "var(--muted)" }}> · {t.accession}</span>}</td>
                        <td><span className="badge b-SKIPPED">{t.input_type.toUpperCase()}</span></td>
                        <td className="small">{t.source === "uniprot" ? "UniProt" : "Upload"}</td>
                        <td className="small" style={{ color: "var(--muted)" }}>{t.submitted_by}</td>
                        <td>
                          <button className="btn ghost" disabled={usingTargetId === t.id} onClick={() => useLibraryTarget(t)}>
                            {usingTargetId === t.id ? "Loading…" : "Use this"}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {uploadTab === "file" && (
            <div className="grid2">
              <div>
                <label>Upload a FASTA sequence</label>
                <div className={"drop" + (file && inputType === "fasta" ? " has" : "")} onClick={() => fileInput.current?.click()}>
                  {file && inputType === "fasta" ? <>📄 <b>{file.name}</b> &nbsp;·&nbsp; click to replace</> : <>Click to choose a <b>.fasta</b> file</>}
                </div>
                <input ref={fileInput} type="file" accept=".fasta,.fa,.faa,.seq" style={{ display: "none" }}
                  onChange={(e) => onFileAndShare(e.target.files?.[0] || null)} />
              </div>
              <div>
                <label>Upload a PDB structure</label>
                <div className={"drop" + (file && inputType === "pdb" ? " has" : "")} onClick={() => pdbInput.current?.click()}>
                  {file && inputType === "pdb" ? <>📄 <b>{file.name}</b> &nbsp;·&nbsp; click to replace</> : <>Click to choose a <b>.pdb</b> file</>}
                </div>
                <input ref={pdbInput} type="file" accept=".pdb,.ent" style={{ display: "none" }}
                  onChange={(e) => onFileAndShare(e.target.files?.[0] || null)} />
              </div>
            </div>
          )}

          {uploadNote && <div className="note ok" style={{ marginTop: 14 }}>{uploadNote}</div>}
          {file && (
            <div style={{ marginTop: 14 }}>
              <div className="note info">Selected: <b>{file.name}</b>{targetMeta?.organism && <> (<b>{targetMeta.organism}</b>)</>} ({inputType?.toUpperCase()})</div>
              {validation && <div className={"note " + (validation.ok ? "ok" : "err")} style={{ marginTop: 8 }}>{validation.msg}</div>}
              {fileText && <pre className="code">{fileText.slice(0, 1200)}{fileText.length > 1200 ? "\n… [preview truncated]" : ""}</pre>}
            </div>
          )}
          <div className="note info" style={{ marginTop: 14 }}>A <b>FASTA</b> target is folded to a PDB first via AlphaFold/ColabFold (adds a
            structure-prediction stage). A <b>PDB</b> target skips that stage and goes straight to BindCraft design.</div>
        </div>
        <Footer prev="Home" next="Structure Prediction" ok={ok} />
      </>
    );
  }

  function pageStructure() {
    if (!file) return <Missing msg="Upload a target first." target="Upload" />;
    const isFasta = inputType === "fasta";
    return (
      <>
        <Header title="Structure Prediction" desc="ColabFold / AlphaFold2 folds a FASTA target into a PDB." />
        <div className="panel">
          <div className="row">
            <span className={"badge " + (isFasta ? "b-PENDING" : "b-SKIPPED")}>{isFasta ? "WILL RUN" : "SKIPPED"}</span>
            <span>{isFasta
              ? "Your target is a sequence — stage 1 runs ColabFold to produce target.pdb before design."
              : "Your target is already a structure — folding is skipped and the PDB is used directly."}</span>
          </div>
          <table style={{ marginTop: 14 }}>
            <tbody>
              <tr><th>Target file</th><td>{file.name}</td></tr>
              <tr><th>Detected type</th><td>{inputType?.toUpperCase()}</td></tr>
              <tr><th>Stage 1 (fold)</th><td>{isFasta ? "ColabFold (5 models, rank-1 → target.pdb)" : "not needed"}</td></tr>
            </tbody>
          </table>
          <div className="note info" style={{ marginTop: 14 }}>This stage runs automatically on the cluster after you launch the pipeline.</div>
        </div>
        <Footer prev="Upload" next="Binder Design" />
      </>
    );
  }

  function pageDesign() {
    if (!file) return <Missing msg="Upload a target first." target="Upload" />;
    const s = settings;
    return (
      <>
        <Header title="Binder Design" desc="Configure BindCraft. These values are written to a per-run settings JSON." />
        <div className="panel">
          <div className="grid2">
            <div><label>Run name (optional)</label><input type="text" value={s.name} onChange={(e) => setField("name", e.target.value)} placeholder="e.g. PDL1 binders run 1" /></div>
            <div><label>Binder name</label><input type="text" value={s.binder_name} onChange={(e) => setField("binder_name", e.target.value)} placeholder="PDL1" /></div>
          </div>
          <div className="grid2">
            <div><label>Target chains</label><input type="text" value={s.chains} onChange={(e) => setField("chains", e.target.value)} /></div>
            <div><label>Hotspot residues (optional)</label><input type="text" value={s.target_hotspot_residues} onChange={(e) => setField("target_hotspot_residues", e.target.value)} placeholder="e.g. 56 or 56,58,121" /></div>
          </div>
          <div className="grid2">
            <div><label>Binder length min</label><input type="number" value={s.length_min} onChange={(e) => setField("length_min", +e.target.value)} /></div>
            <div><label>Binder length max</label><input type="number" value={s.length_max} onChange={(e) => setField("length_max", +e.target.value)} /></div>
          </div>
          {lenBad && <div className="note err" style={{ marginTop: 10 }}>Minimum length must not exceed maximum.</div>}
          <div className="grid2">
            <div><label>Number of final designs</label><input type="number" value={s.number_of_final_designs} onChange={(e) => setField("number_of_final_designs", +e.target.value)} /></div>
            <div />
          </div>
          <div className="grid2">
            <div><label>Filters preset</label><select value={s.filters_preset} onChange={(e) => setField("filters_preset", e.target.value)}>{cfg.filters.map((f) => <option key={f}>{f}</option>)}</select></div>
            <div><label>Advanced preset</label><select value={s.advanced_preset} onChange={(e) => setField("advanced_preset", e.target.value)}>{cfg.advanced.map((a) => <option key={a}>{a}</option>)}</select></div>
          </div>
        </div>
        <Footer prev="Structure Prediction" next="Selectivity Screening" ok={!lenBad} />
      </>
    );
  }

  function pageScreening() {
    if (!file) return <Missing msg="Upload a target first." target="Upload" />;
    const canRun = panelCount > 0 && !lenBad && !!settings.binder_name.trim();
    return (
      <>
        <Header title="Selectivity Screening" desc="Pick the kinase panel the top binder is profiled against (ipTM per kinase)." />
        <div className="panel">
          <div className="row" style={{ marginBottom: 8 }}>
            <button className="btn ghost" onClick={() => setSelected(new Set(cfg.kinases))}>Select all</button>
            <button className="btn ghost" onClick={() => setSelected(new Set())}>Clear</button>
            <span className="spacer" /><span className="small" style={{ color: "var(--muted)" }}>{panelCount} selected</span>
          </div>
          <div className="kinases">
            {cfg.kinases.map((k) => (
              <label key={k}><input type="checkbox" checked={selected.has(k)} onChange={(e) => toggleKinase(k, e.target.checked)} />{k}</label>
            ))}
          </div>
          {!settings.binder_name.trim() && <div className="note warn" style={{ marginTop: 12 }}>Set a <b>Binder name</b> on the Binder Design step before running.</div>}
          <label className="note info" style={{ marginTop: 14, display: "flex", gap: 10, alignItems: "flex-start", cursor: "pointer" }}>
            <input type="checkbox" checked={settings.make_public} onChange={(e) => setField("make_public", e.target.checked)} style={{ marginTop: 3 }} />
            <span>Contribute these results to the <b>shared binder library</b>. Your binder <b>sequence</b>, target,
              and per-kinase ipTM metrics will be visible to other signed-in users. Leave unchecked to keep this run private.</span>
          </label>
          <div className="row" style={{ marginTop: 18 }}>
            <button className="btn" disabled={!canRun} onClick={() => runPipeline(false)}>🚀 Run pipeline</button>
            <span className="small" style={{ color: "var(--muted)" }}>Submits fold → design → profile to the cluster.</span>
          </div>
          {runErr && <div className="note err" style={{ marginTop: 12 }}>{runErr}</div>}
        </div>
        <Footer prev="Binder Design" />
      </>
    );
  }

  function pageViz() {
    if (!job) return <Missing msg="Run the pipeline (or pick a recent run) to see progress." target="Selectivity Screening" />;
    const stages = job.stages || [];
    return (
      <>
        <Header title="Visualization" desc="Live pipeline progress and the ipTM-vs-kinase selectivity plot." />
        <div className="panel">
          <div className="row" style={{ marginBottom: 10 }}>
            <span className={"badge b-" + job.status}>{job.status}</span>
            <span className="small" style={{ color: "var(--muted)" }}>{job.name} · target {job.target_name} ({job.input_type}) · {stages.length} stages</span>
            <span className="spacer" />
            {(job.status === "PENDING" || job.status === "RUNNING") && <button className="btn ghost" onClick={() => cancelJob(job.id)}>Cancel run</button>}
            <button className="btn ghost" onClick={() => showLogs(job.id)}>View logs</button>
          </div>
          <div className="stages">
            {stages.map((s, i) => (
              <div className="stage" key={s.key}>
                <div className="col">
                  <span className={"dot " + s.status} />
                  {i < stages.length - 1 && <span className={"line" + (s.status === "COMPLETED" ? " done" : "")} />}
                </div>
                <div className="body"><div className="lbl">{s.label}</div><span className={"badge b-" + s.status}>{s.status}</span></div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 14 }}>
            {job.status === "COMPLETED" && <><h3 style={{ color: "var(--ink)" }}>ipTM vs kinase</h3>
              <img className="result" src={apiUrl(`/jobs/${job.id}/result.png?t=${job.updated_at}`)} alt="ipTM vs kinase plot" /></>}
            {job.status === "FAILED" && <div className="note err">{job.error || "A stage failed — see logs."}</div>}
            {(job.status === "PENDING" || job.status === "RUNNING") && <div className="note info"><span className="spinner" /> Running on the cluster — refreshes automatically.</div>}
          </div>
          {logText !== null && <pre className="code" style={{ marginTop: 14 }}>{logText}</pre>}
        </div>
        <Footer prev="Selectivity Screening" next="Download" />
      </>
    );
  }

  function pageDownload() {
    if (!job) return <Missing msg="No run selected." target="Visualization" />;
    if (job.status !== "COMPLETED") return (
      <>
        <Header title="Download Results" desc="Export the plot, logs, and a run summary." />
        <div className="panel"><div className="note warn">Run is <b>{job.status}</b>. Downloads unlock when it completes.</div></div>
        <Footer prev="Visualization" />
      </>
    );
    return (
      <>
        <Header title="Download Results" desc="Export the selectivity plot, logs, and a run summary." />
        <div className="panel">
          <div className="cards">
            <div className="card"><h4>iptm_plot.png</h4><div className="small">The ipTM-vs-kinase selectivity plot.</div>
              <div style={{ marginTop: 10 }}><a className="btn" href={apiUrl(`/jobs/${job.id}/result.png`)} download={`iptm_${job.target_name}.png`}>Download plot</a></div></div>
            <div className="card"><h4>run_logs.txt</h4><div className="small">Per-stage cluster logs.</div>
              <div style={{ marginTop: 10 }}><button className="btn" onClick={() => downloadLogs(job.id)}>Download logs</button></div></div>
            <div className="card"><h4>summary.txt</h4><div className="small">Run configuration and target panel.</div>
              <div style={{ marginTop: 10 }}><button className="btn" onClick={() => downloadSummary(job)}>Download summary</button></div></div>
          </div>
          <img className="result" style={{ marginTop: 18 }} src={apiUrl(`/jobs/${job.id}/result.png?t=${job.updated_at}`)} alt="result" />
        </div>
        <Footer prev="Visualization" />
      </>
    );
  }

  function pageLibrary() {
    return (
      <>
        <span className="chip">SHARED LIBRARY</span>
        <h1 className="title">Binder Library</h1>
        <p className="sub">Binders that other users chose to share, with their per-kinase selectivity.</p>
        <div className="panel">
          <div className="row" style={{ marginBottom: 12 }}>
            <input type="text" placeholder="Search binder / sequence…" value={libQ}
              onChange={(e) => setLibQ(e.target.value)} style={{ maxWidth: 280 }} />
            <input type="text" placeholder="Filter by kinase…" value={libKinase}
              onChange={(e) => setLibKinase(e.target.value)} style={{ maxWidth: 200 }} />
            <button className="btn" onClick={loadLibrary}>Search</button>
          </div>
          {library.length === 0 ? <div className="empty" style={{ color: "var(--muted)" }}>No shared results yet.</div> : (
            <table>
              <thead><tr><th>Binder</th><th>Target</th><th>Score</th><th>Selectivity (kinase: best ipTM)</th><th>By</th></tr></thead>
              <tbody>
                {library.map((b) => (
                  <tr key={b.id}>
                    <td><b>{b.binder_name}</b></td>
                    <td>{b.target_name}</td>
                    <td>{b.composite_score ?? "—"}</td>
                    <td className="small">{(b.selectivity || []).map((s: any) => `${s.kinase}: ${s.best_iptm}`).join("  ·  ")}</td>
                    <td className="small" style={{ color: "var(--muted)" }}>{b.submitted_by}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="footer-nav"><button className="btn ghost" onClick={() => setStep("Home")}>← Home</button><span /></div>
      </>
    );
  }

  const pages: Record<string, () => JSX.Element> = {
    "Home": pageHome, "Upload": pageUpload, "Structure Prediction": pageStructure,
    "Binder Design": pageDesign, "Selectivity Screening": pageScreening,
    "Visualization": pageViz, "Download": pageDownload, "Library": pageLibrary,
  };

  if (mode === "simple") return pageSimple();

  return (
    <div className="layout">
      <aside>
        <h2>🧬 Selective Binder</h2>
        <div className="tag">BindCraft design workspace</div>
        <span className="mode">mode: {cfg.mode}</span>
        <hr />
        <button className="navbtn" onClick={() => setMode("simple")}>
          <span className="n">🔎</span><span>Simple search</span>
        </button>
        <hr />
        {STEPS.map((s, i) => (
          <button key={s} className={"navbtn" + (s === step ? " active" : "") + (i < idx ? " done" : "")} onClick={() => setStep(s)}>
            <span className="n">{i === 0 ? "🏠" : i}</span><span>{i === 0 ? "Home" : s}</span>
          </button>
        ))}
        <hr />
        <div className="status">Workspace</div>
        <div className="status">Target: <b>{file ? file.name : "—"}</b></div>
        <div className="status">Input: <b>{inputType ? inputType.toUpperCase() : "—"}</b></div>
        <div className="status">Panel: <b>{panelCount}</b> kinases</div>
        <div className="status">Run: <b>{job ? job.status : "—"}</b></div>
        <hr />
        <div className="status">Recent runs</div>
        {jobs.length === 0 ? <div className="status">No runs yet.</div> : jobs.slice(0, 6).map((j) => (
          <div className="runrow" key={j.id} onClick={() => { setJobId(j.id); setStep("Visualization"); }}>
            <span>{j.name}</span><span className={"badge b-" + j.status}>{j.status}</span>
          </div>
        ))}
        <hr />
        <button className={"navbtn" + (step === "Library" ? " active" : "")} onClick={openLibrary}>
          <span className="n">📚</span><span>Shared Library</span>
        </button>
        <hr />
        <div className="status">👤 <b>{userName}</b></div>
        <button className="ghostlite" style={{ marginBottom: 8 }} onClick={() => instance.logoutRedirect()}>Sign out</button>
        <button className="ghostlite" onClick={reset}>Reset workspace</button>
      </aside>

      <main>
        {apiError && <div className="note err" style={{ marginBottom: 16 }}>
          <b>Can't reach the backend.</b> {apiError}. Open the app through the server URL (over your SSH tunnel /
          deployed origin), and make sure the API is running.
        </div>}
        {pages[step]()}
      </main>

      {cached && (
        <div className="modal-bg">
          <div className="modal">
            <h3>Identical run already exists</h3>
            <p><b>{cached.name}</b> was already run with this exact target file and settings on
              {" " + new Date(cached.created_at * 1000).toLocaleString()}. Reuse that result, or run it again?</p>
            <div className="row" style={{ marginTop: 18 }}>
              <button className="btn" onClick={() => { setJobId(cached.id); setCached(null); setStep("Visualization"); }}>Use existing result</button>
              <button className="btn ghost" onClick={() => { setCached(null); runPipeline(true); }}>Run again</button>
              <span className="spacer" />
              <button className="btn ghost" onClick={() => setCached(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
