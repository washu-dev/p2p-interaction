"""Email the submitting user when their run finishes or fails, via SendGrid.

Fails soft everywhere: a broken/unconfigured mailer must never break job
polling. If `BINDGUI_SENDGRID_API_KEY` or `BINDGUI_EMAIL_SENDER` is unset, we
log what *would* have been sent instead of calling SendGrid — lets mock-mode
dev work without any SendGrid setup.
"""
from __future__ import annotations

import json
from pathlib import Path

import config
import httpx

SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"


def _read_design(job_dir: Path) -> dict:
    p = job_dir / "design_result.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}


def _app_link() -> str:
    return config.APP_URL or "the BindCraft app"


def notify_completed(job: dict, job_dir: Path, to: str) -> None:
    n = _read_design(job_dir).get("accepted_designs")
    n_text = f"{n} accepted design(s)" if isinstance(n, int) else "results"
    subject = f'[BindCraft] "{job.get("name")}" finished — {n_text}'
    body = (
        f'Your run "{job.get("name")}" against {job.get("target_name")} has completed.\n\n'
        f"{n_text.capitalize()} were generated.\n\n"
        f"Open {_app_link()} to view the selectivity plot and download results.\n"
    )
    _send(to, subject, body)


def notify_failed(job: dict, to: str) -> None:
    failed_stage = next((s["label"] for s in job.get("stages") or [] if s.get("status") == "FAILED"), None)
    subject = f'[BindCraft] "{job.get("name")}" failed'
    body = (
        f'Your run "{job.get("name")}" against {job.get("target_name")} did not finish.\n\n'
        + (f"Stage that failed: {failed_stage}\n\n" if failed_stage else "")
        + (f"Error: {job.get('error')}\n\n" if job.get("error") else "")
        + f"Open {_app_link()} to view the logs and try again.\n"
    )
    _send(to, subject, body)


def _send(to: str, subject: str, body: str) -> None:
    if not config.SENDGRID_API_KEY or not config.EMAIL_SENDER:
        print(f"[notify] SendGrid not configured — would have emailed {to}:\n  {subject}")
        return
    r = httpx.post(
        SENDGRID_URL,
        headers={"Authorization": f"Bearer {config.SENDGRID_API_KEY}"},
        json={
            "personalizations": [{"to": [{"email": to}]}],
            "from": {"email": config.EMAIL_SENDER},
            "subject": subject,
            "content": [{"type": "text/plain", "value": body}],
        },
        timeout=15,
    )
    r.raise_for_status()
