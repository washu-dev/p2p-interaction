# 07 — Simple mode: new-user testing checklist

Manual exploratory checklist for the **Simple** landing screen (search →
select species → Run Pipeline → result), written from the point of view of a
first-time, non-technical user. This is *not* the automated test plan (see
[06-test-plan.md](06-test-plan.md)) — it's a walkthrough script for a human to
run before/after changes to `pageSimple()` in `web/src/App.tsx`.

Items marked **⚠️ Known risk** are things read directly out of the current
code, not hypotheticals — worth verifying (and likely fixing) before relying
on this checklist as a "still fine" signal.

## How to run this

1. Start the app in `mock` backend mode (no cluster needed) — `run_dev.ps1` /
   `uvicorn main:app --reload --app-dir backend` + `npm run dev`.
2. Sign in, land on Simple mode (the default screen).
3. Work through each section below, checking off what behaves as expected and
   writing down anything that doesn't.

---

## 1. Search box input

- [ ] Lowercase gene name (`lats1`) returns the same candidates as `LATS1`
- [ ] Mixed case / extra whitespace (`  Lats1  `) behaves the same as trimmed
- [ ] Misspelled name (`LTAS1`, `LAST1`) → shows the
  `No UniProt results for "..."` message, not a blank table or a crash
- [ ] Nonexistent name (`XYZABC123`) → same graceful "no results" message
- [ ] Full protein name instead of gene symbol (`Serine/threonine-protein
  kinase LATS1`) → check the results are still relevant, not empty/garbage
- [ ] A UniProt accession typed directly (`O95835`) → confirm whether it
  resolves to something sensible
- [ ] Gene names with special characters (`PD-L1`, `HER2/neu`) → confirm the
  results still make sense (not a crash — these are URL-encoded before
  hitting UniProt, so the risk here is "no/wrong results," not breakage)
- [ ] A generic English word (`kinase`) → note what a confused user would see
  (likely a long list of unrelated "reviewed" hits with no obvious guidance)
- [ ] Very long pasted text, emoji, non-Latin script, `<script>alert(1)</script>` →
  confirm no crash and nothing renders as executable/unescaped HTML (React
  escapes text by default — this is a sanity check, not expected to fail)
- [ ] Empty box + Enter → no request fires, nothing changes
- [ ] Enter key and the Search button behave identically
- [ ] **⚠️ Known risk** — type a query, hit search, then immediately change
  the text and search again before the first response returns. There's no
  request-cancellation/staleness guard in `searchUniprot()`, so if the first
  (stale) response resolves *after* the second, the table can end up showing
  results for the query the user no longer has typed in the box.

## 2. Picking a candidate

- [ ] A search with exactly one result renders fine (table doesn't look broken
  with a single row)
- [ ] A search with many results (10+) stays readable — no obvious overflow/
  cutoff
- [ ] Long protein-name strings wrap instead of breaking the layout
- [ ] Picking a non-"Human" organism by mistake, then using **Change target**
  to fix it — confirm the flow back to searching is obvious, not a dead end
- [ ] **⚠️ Known risk — ambiguous gene symbols.** Search `PDL1`: the results
  include both *PD-L1 (Programmed cell death 1 ligand 1)* — the immune
  checkpoint most users mean — **and** *PDZ and LIM domain protein 1*, an
  unrelated protein that also happens to be abbreviated PDL1. Both are tagged
  "reviewed." A first-time user who doesn't read the full protein name
  carefully can silently pick the wrong target. Worth a mitigation (e.g.
  warn when a query string doesn't appear in the matched gene name at all).
- [ ] **⚠️ Known risk — selection race.** Click "Use this" on candidate A,
  then quickly click "Use this" on candidate B before A's download finishes.
  Whichever request resolves *last* wins, which may not be B (the user's
  actual last click) if A's request happens to be slower.

## 3. Run Pipeline behavior

- [ ] Run Pipeline stays disabled until a target has finished downloading
  (not just "clicked")
- [ ] **⚠️ Known risk — duplicate submission.** Click Run Pipeline twice in
  quick succession. The button is only gated on `!file`, not on "a submission
  is already in flight," and the server's dedup (`params_key` cache-hit) only
  catches an identical run that's already **COMPLETED** — two rapid clicks
  before the first job finishes can create two separate PENDING jobs for the
  same target/settings.
- [ ] After a job is running, search for and select a *different* target —
  confirm what the user sees. Today the progress panel keeps tracking the
  original job; picking a new target only stages it for the *next* Run
  Pipeline click. Verify this isn't confusing in practice (e.g. does the UI
  make it clear the running job is unaffected by the new selection?).
- [ ] Cancel button on a running job actually stops progress in the UI
- [ ] Completed job shows plot + all three downloads (plot / logs /
  binder.zip), and each one actually downloads something valid

## 4. Error handling (a real user is not always on campus VPN / always logged in)

- [ ] Stop the backend, click Search → note the exact message shown. Today
  it's the raw `fetch` error (e.g. "Failed to fetch"), not something a
  non-technical user would understand. Decide if this needs a friendlier
  message.
- [ ] Same check for clicking Run Pipeline with the backend down
- [ ] Let the MSAL session/token expire mid-session, then click any action —
  confirm the failure is at least not a silent no-op, and consider whether it
  should redirect to login instead of showing an error

## 5. Scope gap

- [ ] **⚠️ Known gap** — Simple mode has no direct FASTA/PDB upload option;
  that only exists in Advanced mode's "Upload file" tab. A user who already
  has their own sequence/structure file has to go into Advanced to use it.
  Decide whether Simple mode should also offer a lightweight upload path.

## 6. Comprehension (no-CS-background persona)

- [ ] Is it clear to a first-time user what the "reviewed" badge means, and
  why it should be preferred?
- [ ] Is it clear why one search can return multiple rows (different species /
  different genes with similar names) rather than looking like duplicates?
- [ ] Is it obvious, without reading the fine print, that clicking "Use this"
  both downloads *and* commits to that target?

## 7. Email notification on completion / failure

Not Simple-mode-specific — this applies to any job, submitted from Simple or
Advanced, since both go through the same backend job lifecycle. Included here
because it's the direct answer to "the run takes ~3 hours, nobody sits and
watches it."

**Requirement**
- On **COMPLETED**: email the submitting user that their run finished, with
  the target name and the **number of accepted designs**.
- On **FAILED**: email which stage failed, with a pointer back to the app/logs.
- Must arrive even if nobody has the app open for the whole run.
- Must not resend on every later poll of an already-terminal job (send once).

**What's missing today to build this**
- `backend/pipeline/select_top_binder.py` only writes the *top* binder into
  `design_result.json` (`binder_name`, `binder_sequence`, `composite_score`,
  `design_metrics`) — it does **not** currently record how many designs were
  accepted overall (`len(scored)` from `final_design_stats.csv`, or the count
  of `Accepted/*.pdb` files). That needs a small addition before the email
  can report a real count; `MockRunner` needs an equivalent fake count for
  mock-mode testing.
- No background poller exists — job status only advances when a browser polls
  `/api/jobs`. Without one, an email that depends on "job just became
  COMPLETED" only fires whenever someone next happens to have the app open.
- Idempotency: reuse the same pattern as `_maybe_publish()` in `main.py` (a
  `notified.flag` file per job dir) so the email doesn't resend on repeat polls.
- Recipient = `job["settings"]["submitted_by"]` — already populated from the
  signed-in WashU identity, no new field needed.
- Sending mechanism: AWS SES via `boto3` (already a dependency) is the
  natural choice given this deploys to AWS already — needs a verified sender
  identity / production access in SES (an AWS-console step, not code).

**Testing checklist (once implemented)**
- [ ] A COMPLETED job in mock mode sends exactly one email, with the correct
  accepted-design count for that run
- [ ] A FAILED job (cancel mid-run, or force a stage to fail in mock mode)
  sends exactly one email describing which stage failed
- [ ] Leaving the app fully closed for the whole run still results in an
  email (proves the background poller works, not just frontend-poll-driven)
- [ ] Re-opening the app after completion and re-polling does **not** send a
  second email for the same job
- [ ] Two different users' jobs each notify the correct recipient, never
  cross-notify
- [ ] The email is readable in a plain-text client (no raw HTML tags visible,
  links actually resolve to the app)
- [ ] A simulated SES failure (bad recipient, throttling) logs an error but
  does not break `/api/jobs` polling for anyone else
