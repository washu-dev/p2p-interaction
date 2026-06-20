"""Pluggable pipeline runners.

All runners share one interface, operating on a job's *stages*:

    submit(job, job_dir) -> stages
    poll(job, job_dir)   -> (overall, stages, error)
    cancel(job, job_dir)

  * MockRunner        — simulate the chain on any laptop (dev).
  * SlurmRunner       — backend runs ON the login node; local sbatch/squeue.
  * RemoteSlurmRunner — backend runs OFF-cluster (AWS); drives the login node
                        over Paramiko SSH (whiteboard's RSA-key design).
"""
import posixpath
import shutil
import subprocess
import time
from pathlib import Path

import config
from stages import overall_status

_ARTIFACT = {"fold": "target.pdb", "design": "top_binder.pdb", "profile": "result.png"}


# ---------------------------------------------------------------------------
# Shared: render one stage's sbatch from its template + a path map P
# ---------------------------------------------------------------------------
def render_stage(stage, job, P) -> str:
    settings = job.get("settings", {})
    fp = settings.get("filters_preset", "default_filters")
    ap = settings.get("advanced_preset", "default_4stage_multimer")
    tmpl = (config.PIPELINE_DIR / stage["template"]).read_text()
    repl = {
        "__JOBNAME__": f"{job['id'][:6]}-{stage['key']}",
        "__PARTITION__": config.SLURM_PARTITION,
        "__ACCOUNT__": config.SLURM_ACCOUNT,
        "__JOBDIR__": P["jobdir"],
        "__BINDCRAFT_DIR__": P["bindcraft"],
        "__PIPELINE_DIR__": P["pipeline"],
        "__COLABFOLD_BIN__": P["colabfold"],
        "__MAMBA_ENV__": P["mamba_env"],
        "__MAMBA_ROOT__": P["mamba_root"],
        "__TARGET_FASTA_DIR__": P["target_fasta"],
        "__FILTERS_PATH__": P["filters_dir"] + "/" + fp + ".json",
        "__ADVANCED_PATH__": P["advanced_dir"] + "/" + ap + ".json",
    }
    for k, v in repl.items():
        tmpl = tmpl.replace(k, v)
    return tmpl


def _classify(squeue_out, sacct_out, artifact_exists):
    """Map SLURM output to one of our stage states."""
    live = squeue_out.strip().splitlines()
    if live:
        st = live[0].strip()
        if st in ("PENDING", "CONFIGURING"):
            return "PENDING"
        if st == "CANCELLED":
            return "CANCELLED"
        if st in ("FAILED", "TIMEOUT", "NODE_FAIL", "OUT_OF_MEMORY"):
            return "FAILED"
        return "RUNNING"
    states = [x.strip() for x in (sacct_out or "").splitlines() if x.strip()]
    final = states[0] if states else ""
    if final.startswith("COMPLETED"):
        return "COMPLETED" if artifact_exists else "FAILED"
    if final.startswith("CANCELLED"):
        return "CANCELLED"
    if final:
        return "FAILED"
    return "COMPLETED" if artifact_exists else "RUNNING"


# ---------------------------------------------------------------------------
# Mock
# ---------------------------------------------------------------------------
class MockRunner:
    def submit(self, job, job_dir: Path):
        stages = job["stages"]
        now = time.time()
        for i, s in enumerate(stages):
            s["scheduler_id"] = f"mock-{s['key']}"
            s["_finish_at"] = now + config.MOCK_STAGE_SEC * (i + 1)
            s["status"] = "PENDING"
        (job_dir / "pipeline.log").write_text(
            f"[mock] submitted {[s['key'] for s in stages]} for target={job['target_name']}\n"
        )
        return stages

    def poll(self, job, job_dir: Path):
        stages = job["stages"]
        now = time.time()
        prev_done = True
        for s in stages:
            if s["status"] in ("CANCELLED", "FAILED"):
                prev_done = False
                continue
            if not prev_done:
                s["status"] = "PENDING"
                continue
            if now >= s.get("_finish_at", now):
                if s["status"] != "COMPLETED":
                    s["status"] = "COMPLETED"
                    self._produce(s["key"], job_dir)
            else:
                s["status"] = "RUNNING"
                prev_done = False
        return overall_status(stages), stages, None

    def _produce(self, key, job_dir: Path):
        with (job_dir / "pipeline.log").open("a") as log:
            if key == "fold":
                if config.MOCK_TARGET_PDB.exists():
                    shutil.copyfile(config.MOCK_TARGET_PDB, job_dir / "target.pdb")
                else:
                    (job_dir / "target.pdb").write_text("MOCK PDB\n")
                log.write("[mock] fold done -> target.pdb\n")
            elif key == "design":
                (job_dir / "top_binder.pdb").write_text("MOCK top-ranked binder PDB\n")
                log.write("[mock] design done -> top_binder.pdb\n")
            elif key == "profile":
                if config.MOCK_RESULT_PNG.exists():
                    shutil.copyfile(config.MOCK_RESULT_PNG, job_dir / "result.png")
                log.write("[mock] profile done -> result.png\n")

    def cancel(self, job, job_dir: Path):
        for s in job["stages"]:
            if s["status"] in ("PENDING", "RUNNING"):
                s["status"] = "CANCELLED"
        return job["stages"]


# ---------------------------------------------------------------------------
# SLURM (local — backend runs ON the login node)
# ---------------------------------------------------------------------------
class SlurmRunner:
    def _paths(self, job_dir: Path):
        return {
            "jobdir": str(job_dir),
            "bindcraft": str(config.BINDCRAFT_DIR),
            "pipeline": str(config.PIPELINE_DIR),
            "colabfold": config.COLABFOLD_BIN_DIR,
            "mamba_env": config.MICROMAMBA_ENV,
            "mamba_root": config.MAMBA_ROOT,
            "target_fasta": config.TARGET_FASTA_DIR,
            "filters_dir": str(config.SETTINGS_FILTERS_DIR),
            "advanced_dir": str(config.SETTINGS_ADVANCED_DIR),
        }

    def submit(self, job, job_dir: Path):
        stages = job["stages"]
        P = self._paths(job_dir)
        dep = None
        for s in stages:
            script = job_dir / f"{s['key']}.sbatch"
            script.write_text(render_stage(s, job, P))
            cmd = ["sbatch", "--parsable"]
            if dep:
                cmd.append(f"--dependency=afterok:{dep}")
            cmd.append(str(script))
            try:
                out = subprocess.check_output(cmd, cwd=str(job_dir), text=True)
                sid = out.strip().split(";")[0]
            except subprocess.CalledProcessError as e:
                s["status"] = "FAILED"
                s["error"] = f"sbatch failed: {e.output or e}"
                break
            s["scheduler_id"] = sid
            s["status"] = "PENDING"
            dep = sid
        return stages

    def poll(self, job, job_dir: Path):
        for s in job["stages"]:
            if s["status"] in ("COMPLETED", "FAILED", "CANCELLED") or not s.get("scheduler_id"):
                continue
            sid = s["scheduler_id"]
            q = subprocess.run(["squeue", "-j", sid, "-h", "-o", "%T"], capture_output=True, text=True)
            a = subprocess.run(["sacct", "-j", sid, "-n", "-P", "-o", "State"], capture_output=True, text=True)
            artifact = (job_dir / _ARTIFACT.get(s["key"], "")).exists()
            s["status"] = _classify(q.stdout, a.stdout, artifact)
        return overall_status(job["stages"]), job["stages"], None

    def cancel(self, job, job_dir: Path):
        for s in job["stages"]:
            if s.get("scheduler_id") and s["status"] in ("PENDING", "RUNNING"):
                subprocess.run(["scancel", s["scheduler_id"]], check=False)
                s["status"] = "CANCELLED"
        return job["stages"]


# ---------------------------------------------------------------------------
# SLURM (remote — backend runs OFF-cluster, drives login node via Paramiko)
# ---------------------------------------------------------------------------
class RemoteSlurmRunner:
    def __init__(self):
        from sshconn import get_ssh
        self.ssh = get_ssh()

    def _remote_jobdir(self, job_id):
        return posixpath.join(config.REMOTE_DIR, "jobs", job_id)

    def _paths(self, remote_jobdir):
        bc = config.BINDCRAFT_DIR.as_posix() if hasattr(config.BINDCRAFT_DIR, "as_posix") else str(config.BINDCRAFT_DIR)
        return {
            "jobdir": remote_jobdir,
            "bindcraft": bc,
            "pipeline": config.REMOTE_PIPELINE_DIR,
            "colabfold": config.COLABFOLD_BIN_DIR,
            "mamba_env": config.MICROMAMBA_ENV,
            "mamba_root": config.MAMBA_ROOT,
            "target_fasta": config.TARGET_FASTA_DIR,
            "filters_dir": bc + "/settings_filters",
            "advanced_dir": bc + "/settings_advanced",
        }

    def submit(self, job, job_dir: Path):
        stages = job["stages"]
        rjob = self._remote_jobdir(job["id"])
        self.ssh.mkdirs(rjob)

        # Deploy the pipeline scripts once (idempotent).
        if not self.ssh.exists(config.REMOTE_PIPELINE_DIR + "/select_top_binder.py"):
            self.ssh.put_dir(config.PIPELINE_DIR, config.REMOTE_PIPELINE_DIR)

        # Upload this job's inputs (written locally by main.py).
        for fname in ("target.fasta", "target.pdb", "settings_target.json", "targets.txt"):
            local = job_dir / fname
            if local.exists():
                self.ssh.put(str(local), posixpath.join(rjob, fname))

        P = self._paths(rjob)
        dep = None
        for s in stages:
            script = render_stage(s, job, P)
            (job_dir / f"{s['key']}.sbatch").write_text(script)            # local record
            self.ssh.write_text(posixpath.join(rjob, f"{s['key']}.sbatch"), script)
            dep_flag = f"--dependency=afterok:{dep} " if dep else ""
            rc, out, err = self.ssh.run(
                f"cd {q(rjob)} && sbatch --parsable {dep_flag}{q(s['key'] + '.sbatch')}"
            )
            if rc != 0:
                s["status"] = "FAILED"
                s["error"] = f"sbatch failed: {err.strip() or out.strip()}"
                break
            s["scheduler_id"] = out.strip().split(";")[0]
            s["status"] = "PENDING"
            dep = s["scheduler_id"]
        return stages

    def poll(self, job, job_dir: Path):
        rjob = self._remote_jobdir(job["id"])
        for s in job["stages"]:
            if s["status"] in ("COMPLETED", "FAILED", "CANCELLED") or not s.get("scheduler_id"):
                continue
            sid = s["scheduler_id"]
            _, q_out, _ = self.ssh.run(f"squeue -j {sid} -h -o %T")
            _, a_out, _ = self.ssh.run(f"sacct -j {sid} -n -P -o State")
            artifact = self.ssh.exists(posixpath.join(rjob, _ARTIFACT.get(s["key"], "x")))
            s["status"] = _classify(q_out, a_out, artifact)

        self._sync_back(job, job_dir, rjob)
        return overall_status(job["stages"]), job["stages"], None

    def _sync_back(self, job, job_dir: Path, rjob):
        """Pull logs (always) and result.png (when ready) to the local mirror."""
        for s in job["stages"]:
            log = posixpath.join(rjob, f"{s['key']}.log")
            if self.ssh.exists(log):
                try:
                    self.ssh.get(log, str(job_dir / f"{s['key']}.log"))
                except Exception:  # noqa: BLE001 — logs are best-effort
                    pass
        if any(s["key"] == "profile" and s["status"] == "COMPLETED" for s in job["stages"]):
            remote_png = posixpath.join(rjob, "result.png")
            if not (job_dir / "result.png").exists() and self.ssh.exists(remote_png):
                self.ssh.get(remote_png, str(job_dir / "result.png"))

    def cancel(self, job, job_dir: Path):
        for s in job["stages"]:
            if s.get("scheduler_id") and s["status"] in ("PENDING", "RUNNING"):
                self.ssh.run(f"scancel {s['scheduler_id']}")
                s["status"] = "CANCELLED"
        return job["stages"]


def q(s):
    from sshconn import sh_quote
    return sh_quote(s)


def get_runner():
    if config.BACKEND_MODE == "ssh":
        return RemoteSlurmRunner()
    if config.BACKEND_MODE == "slurm":
        return SlurmRunner()
    return MockRunner()
