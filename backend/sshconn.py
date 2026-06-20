"""Thin Paramiko wrapper for driving the cluster login node from off-cluster.

Implements the "RSA key pair" auth from the whiteboard: the backend (on AWS)
holds the private key and connects to the login node, which trusts the matching
public key. One lazily-opened, auto-reconnecting connection is shared across
requests (FastAPI runs sync endpoints in a threadpool, so we guard with a lock).

paramiko is imported lazily so that mock / local-slurm modes don't require it.
"""
from __future__ import annotations

import posixpath
import threading

import config

_paramiko = None


def _pm():
    global _paramiko
    if _paramiko is None:
        import paramiko  # lazy: only needed in ssh mode
        _paramiko = paramiko
    return _paramiko


class SSHError(RuntimeError):
    pass


class SSHManager:
    def __init__(self):
        self._client = None
        self._lock = threading.Lock()

    # -- connection ---------------------------------------------------------
    def _ensure(self):
        if self._client is not None and self._client.get_transport() and self._client.get_transport().is_active():
            return self._client
        if not (config.SSH_HOST and config.SSH_USER and config.SSH_KEY):
            raise SSHError("ssh mode needs BINDGUI_SSH_HOST, BINDGUI_SSH_USER and BINDGUI_SSH_KEY")
        pm = _pm()
        client = pm.SSHClient()
        # Load known_hosts from an explicit file (BINDGUI_SSH_KNOWN_HOSTS_FILE) or
        # the system default (~/.ssh/known_hosts), then reject unrecognised keys.
        # To populate: `ssh-keyscan <host> >> ~/.ssh/known_hosts` once on the host,
        # or set BINDGUI_SSH_KNOWN_HOSTS_FILE to a pre-seeded file in the container.
        known_hosts_file = config.SSH_KNOWN_HOSTS_FILE
        if known_hosts_file:
            client.load_host_keys(known_hosts_file)
        else:
            client.load_system_host_keys()
        client.set_missing_host_key_policy(pm.RejectPolicy())
        client.connect(
            hostname=config.SSH_HOST,
            port=config.SSH_PORT,
            username=config.SSH_USER,
            key_filename=config.SSH_KEY,
            passphrase=config.SSH_KEY_PASSPHRASE,
            look_for_keys=False,
            allow_agent=False,
            timeout=20,
        )
        self._client = client
        return client

    # -- commands -----------------------------------------------------------
    def run(self, cmd: str):
        """Run a command; return (exit_code, stdout, stderr)."""
        with self._lock:
            client = self._ensure()
            stdin, stdout, stderr = client.exec_command(cmd, timeout=120)
            out = stdout.read().decode(errors="replace")
            err = stderr.read().decode(errors="replace")
            rc = stdout.channel.recv_exit_status()
        return rc, out, err

    def check(self, cmd: str) -> str:
        rc, out, err = self.run(cmd)
        if rc != 0:
            raise SSHError(f"`{cmd}` failed (rc={rc}): {err.strip() or out.strip()}")
        return out

    # -- sftp ---------------------------------------------------------------
    def _sftp(self):
        return self._ensure().open_sftp()

    def mkdirs(self, remote_dir: str):
        self.check(f"mkdir -p {sh_quote(remote_dir)}")

    def exists(self, remote_path: str) -> bool:
        rc, _, _ = self.run(f"test -e {sh_quote(remote_path)}")
        return rc == 0

    def put(self, local_path: str, remote_path: str):
        with self._lock:
            sftp = self._sftp()
            try:
                sftp.put(local_path, remote_path)
            finally:
                sftp.close()

    def get(self, remote_path: str, local_path: str):
        with self._lock:
            sftp = self._sftp()
            try:
                sftp.get(remote_path, local_path)
            finally:
                sftp.close()

    def write_text(self, remote_path: str, text: str):
        with self._lock:
            sftp = self._sftp()
            try:
                with sftp.open(remote_path, "w") as f:
                    f.write(text)
            finally:
                sftp.close()

    def put_dir(self, local_dir, remote_dir: str):
        """Upload every file in local_dir (non-recursive is enough for pipeline/)."""
        from pathlib import Path

        self.mkdirs(remote_dir)
        for p in Path(local_dir).iterdir():
            if p.is_file():
                self.put(str(p), posixpath.join(remote_dir, p.name))


def sh_quote(s: str) -> str:
    """Minimal POSIX single-quote shell quoting."""
    return "'" + str(s).replace("'", "'\\''") + "'"


_manager: SSHManager | None = None


def get_ssh() -> SSHManager:
    global _manager
    if _manager is None:
        _manager = SSHManager()
    return _manager
