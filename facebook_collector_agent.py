import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = HERE / "facebook_collector_agent.log"
POLL_SECONDS = 1800
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


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
    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            log("FACEBOOK_COLLECTOR_AGENT_STOPPED")
            return 0
        except Exception as exc:
            log("FACEBOOK_COLLECTOR_WARNING " + str(exc))
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
