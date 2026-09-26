import os
import subprocess
import sys
import time
from datetime import datetime, timezone
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = HERE / "facebook_collector_agent.log"
POLL_SECONDS = 1800
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
STATUS_FILE = HERE / "facebook_collector_status.json"
GIT_LOCK = Path.home() / ".hong-cung-toi" / "repo_git.lock"

class GitLock:
    def __init__(self, timeout=120, stale_after=300):
        self.timeout = timeout
        self.stale_after = stale_after
        self.fd = None
    def __enter__(self):
        GIT_LOCK.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + self.timeout
        while True:
            try:
                self.fd = os.open(str(GIT_LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, f"{os.getpid()} {time.time()}".encode("ascii"))
                return self
            except FileExistsError:
                try:
                    if time.time() - GIT_LOCK.stat().st_mtime > self.stale_after:
                        GIT_LOCK.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                if time.time() >= deadline:
                    raise RuntimeError("Timed out waiting for shared Git lock")
                time.sleep(1)
    def __exit__(self, exc_type, exc, tb):
        try:
            if self.fd is not None:
                os.close(self.fd)
        finally:
            try:
                GIT_LOCK.unlink(missing_ok=True)
            except Exception:
                pass


for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass


def save_status(state, stage, message="", **extra):
    data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "stage": stage,
        "message": message,
    }
    data.update(extra)
    tmp = STATUS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATUS_FILE)


def push_status_best_effort():
    def run(args, timeout=90):
        return subprocess.run(
            args, cwd=str(HERE), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
    try:
        with GitLock():
            run(["git", "config", "user.name", "HCT Facebook Collector"])
            run(["git", "config", "user.email", "hct-fb-collector@local"])
            run(["git", "add", "-f", STATUS_FILE.name])
            if run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
                return
            if run(["git", "commit", "-m", f"Facebook collector heartbeat {datetime.now().isoformat(timespec='seconds')}"]).returncode != 0:
                return
            if run(["git", "pull", "--rebase", "--autostash", "origin", "main"]).returncode != 0:
                return
            run(["git", "push", "origin", "HEAD:main"])
    except Exception:
        pass


def log(msg):
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_once():
    cmd = [sys.executable, str(HERE / "facebook_collector_local.py"), "--headless", "--push"]
    p = subprocess.run(
        cmd,
        cwd=str(HERE),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    if p.stdout:
        for line in p.stdout.splitlines():
            log("OUT " + line)
    if p.stderr:
        for line in p.stderr.splitlines():
            log("ERR " + line)
    if p.returncode != 0:
        raise RuntimeError(f"collector exited {p.returncode}")


def main():
    log("FACEBOOK_COLLECTOR_AGENT_STARTED")
    save_status("RUNNING", "AGENT_STARTED", "Facebook collector agent is running")
    push_status_best_effort()
    while True:
        try:
            run_once()
            save_status("OK", "WAITING", "Collector run completed; waiting for next cycle", poll_seconds=POLL_SECONDS)
            push_status_best_effort()
        except KeyboardInterrupt:
            log("FACEBOOK_COLLECTOR_AGENT_STOPPED")
            save_status("STOPPED", "AGENT_STOPPED", "Facebook collector agent stopped")
            push_status_best_effort()
            return 0
        except Exception as exc:
            log("FACEBOOK_COLLECTOR_WARNING " + str(exc))
            save_status("ERROR", "COLLECTOR_FAILED", str(exc))
            push_status_best_effort()
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
