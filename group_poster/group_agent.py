import base64
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
QUEUE = HERE / 'group_queue.json'
STATE = HERE / 'agent_state.json'
LOG = HERE / 'agent.log'
POLL_SECONDS = 30
ASSET_MANIFEST_DIR = REPO / 'facebook_assets_b64'
ASSET_OUT_DIR = HERE / 'temp_assets'
LEGACY_ASSET_OUT_DIR = Path.home() / '.hong-cung-toi' / 'temp_assets'
CREATE_NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0
GROUP_AGENT_MUTEX = "Global\\HongCungToiGroupAgent"
_SINGLE_INSTANCE_HANDLE = None

def acquire_single_instance():
    global _SINGLE_INSTANCE_HANDLE
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, GROUP_AGENT_MUTEX)
        if not handle:
            raise RuntimeError("Could not create Group Agent mutex")
        ERROR_ALREADY_EXISTS = 183
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        _SINGLE_INSTANCE_HANDLE = handle
        return True

    lock_path = Path.home() / ".hong-cung-toi" / "group_agent.instance.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("ascii"))
        _SINGLE_INSTANCE_HANDLE = (fd, lock_path)
        return True
    except FileExistsError:
        return False

GIT_LOCK = Path.home() / '.hong-cung-toi' / 'repo_git.lock'

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


def log(msg):
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    with LOG.open('a', encoding='utf-8') as f:
        f.write(line + '\n')

def load_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8-sig'))

def save_json(path, data):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)

def sync_binary_assets():
    """Rebuild binary assets committed as base64 text chunks.

    This lets ChatGPT place generated images into GitHub using text-safe writes,
    while the Windows agent reconstructs the exact bytes locally after git pull.
    """
    if not ASSET_MANIFEST_DIR.exists():
        return
    ASSET_OUT_DIR.mkdir(parents=True, exist_ok=True)
    for manifest_path in ASSET_MANIFEST_DIR.glob("*.manifest.json"):
        spec = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        output_name = str(spec.get("output_name") or "").strip()
        chunks = spec.get("chunks") or []
        if not output_name or not chunks:
            continue
        out_path = ASSET_OUT_DIR / output_name
        b64 = "".join((ASSET_MANIFEST_DIR / name).read_text(encoding="ascii").strip() for name in chunks)
        raw = base64.b64decode(b64, validate=True)
        if not (out_path.exists() and out_path.read_bytes() == raw):
            out_path.write_bytes(raw)
            log(f"ASSET_SYNCED {output_name} bytes={len(raw)}")
        # Compatibility mirror: some Group Poster revisions resolve the temp
        # folder as .hong-cung-toi while the agent historically used .hong-cung-toi.
        LEGACY_ASSET_OUT_DIR.mkdir(parents=True, exist_ok=True)
        legacy_path = LEGACY_ASSET_OUT_DIR / output_name
        if not (legacy_path.exists() and legacy_path.read_bytes() == raw):
            legacy_path.write_bytes(raw)
            log(f"ASSET_MIRRORED {output_name} bytes={len(raw)}")


def publish_status_to_repo():
    """Commit lightweight agent status/report so ChatGPT can observe local runs."""
    targets = [STATE]
    report = HERE / "output" / "group_batch_report.json"
    verify_report = HERE / "output" / "group_verify_report.json"
    if report.exists():
        targets.append(report)
    if verify_report.exists():
        targets.append(verify_report)
    rels = [str(p.relative_to(REPO)) for p in targets if p.exists()]
    if not rels:
        return
    # Repo-local identity only; avoids global Git configuration changes on the user's PC.
    with GitLock():
        subprocess.run(["git","-C",str(REPO),"config","user.name","HCT Group Agent"], capture_output=True, text=True, timeout=15, creationflags=CREATE_NO_WINDOW)
        subprocess.run(["git","-C",str(REPO),"config","user.email","hct-group-agent@local"], capture_output=True, text=True, timeout=15, creationflags=CREATE_NO_WINDOW)
        subprocess.run(["git","-C",str(REPO),"add","-f",*rels], capture_output=True, text=True, timeout=30, creationflags=CREATE_NO_WINDOW)
        diff = subprocess.run(["git","-C",str(REPO),"diff","--cached","--quiet"], capture_output=True, text=True, timeout=30, creationflags=CREATE_NO_WINDOW)
        if diff.returncode == 0:
            return
        msg = f"Agent status {datetime.now().isoformat(timespec='seconds')}"
        c = subprocess.run(["git","-C",str(REPO),"commit","-m",msg], capture_output=True, text=True, timeout=60, creationflags=CREATE_NO_WINDOW)
        if c.returncode != 0:
            log(f"STATUS_COMMIT_WARNING {(c.stderr or c.stdout).strip()}")
            return
        # Rebase lightweight local status commits onto the latest remote main before pushing.
        # This prevents queue/package commits made remotely from making the agent branch diverge.
        r = subprocess.run(["git","-C",str(REPO),"pull","--rebase","--autostash","origin","main"], capture_output=True, text=True, timeout=90, creationflags=CREATE_NO_WINDOW)
        if r.returncode != 0:
            log(f"STATUS_REBASE_WARNING {(r.stderr or r.stdout).strip()}")
            return
        p = subprocess.run(["git","-C",str(REPO),"push","origin","HEAD:main"], capture_output=True, text=True, timeout=90, creationflags=CREATE_NO_WINDOW)
        if p.returncode != 0:
            log(f"STATUS_PUSH_WARNING {(p.stderr or p.stdout).strip()}")
        else:
            log("STATUS_PUSHED")


def git_pull():
    """Best-effort remote sync.

    Posting must never be blocked for a long time by GitHub/network trouble.
    The local queue is authoritative for immediate execution; remote sync only
    refreshes it when GitHub is reachable.
    """
    try:
        with GitLock(timeout=5):
            p = subprocess.run(
                ['git','-C',str(REPO),'pull','--rebase','--autostash','origin','main'],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=CREATE_NO_WINDOW,
            )
        if p.returncode != 0:
            log(f"GIT_PULL_WARNING {(p.stderr or p.stdout or 'git pull failed').strip()}")
            return False
        return True
    except subprocess.TimeoutExpired:
        log("GIT_PULL_WARNING timed out after 15 seconds; continuing with local queue")
        return False
    except Exception as exc:
        log(f"GIT_PULL_WARNING {exc}; continuing with local queue")
        return False

def run_command(queue):
    command_id = str(queue.get('command_id') or '').strip()
    action = str(queue.get('action') or 'IDLE').upper()
    package = str(queue.get('package') or '').strip()
    if action == 'PING':
        if not command_id:
            raise RuntimeError('PING queue requires command_id')
        log(f'PING_OK command_id={command_id}')
        return command_id
    if action == 'SCAN_GROUPS':
        if not command_id:
            raise RuntimeError('SCAN_GROUPS queue requires command_id')
        log(f'SCAN_START command_id={command_id}')
        cmd = [sys.executable, str(HERE/'group_registry_scan.py')]
        p = subprocess.run(cmd, cwd=str(HERE), text=True, capture_output=True, creationflags=CREATE_NO_WINDOW)
        if p.stdout:
            for line in p.stdout.splitlines():
                log(line)
        if p.returncode != 0:
            raise RuntimeError((p.stderr or p.stdout or f'scanner exited {p.returncode}').strip())
        log(f'SCAN_DONE command_id={command_id}')
        return command_id
    if action == 'VERIFY_GROUPS':
        if not command_id:
            raise RuntimeError('VERIFY_GROUPS queue requires command_id')
        log(f'VERIFY_START command_id={command_id}')
        cmd = [sys.executable, str(HERE/'group_registry_verify.py')]
        p = subprocess.run(cmd, cwd=str(HERE), text=True, capture_output=True, creationflags=CREATE_NO_WINDOW)
        if p.stdout:
            for line in p.stdout.splitlines():
                log(line)
        if p.returncode != 0:
            raise RuntimeError((p.stderr or p.stdout or f'verifier exited {p.returncode}').strip())
        log(f'VERIFY_DONE command_id={command_id}')
        return command_id
    if action == 'LOGIN':
        if not command_id:
            raise RuntimeError('LOGIN queue requires command_id')
        log(f'LOGIN_START command_id={command_id}')
        cmd = [sys.executable, str(HERE/'group_poster.py'), '--login']
        p = subprocess.run(cmd, cwd=str(HERE), text=True, capture_output=True, creationflags=CREATE_NO_WINDOW)
        if p.stdout:
            for line in p.stdout.splitlines():
                log(f'LOGIN_OUT {line}')
        if p.stderr:
            for line in p.stderr.splitlines():
                log(f'LOGIN_ERR {line}')
        if p.returncode != 0:
            detail = (getattr(p, 'stderr_text', '') or getattr(p, 'stdout_text', '') or '').strip().splitlines()
            tail = detail[-1] if detail else 'no detail'
            raise RuntimeError(f'Group Poster login exited with code {p.returncode}: {tail}')
        log(f'LOGIN_DONE command_id={command_id}')
        return command_id
    if action != 'PUBLISH':
        return None
    if not command_id or not package:
        raise RuntimeError('PUBLISH queue requires command_id and package')
    package_path = REPO / package
    if not package_path.exists():
        raise RuntimeError(f'Package not found: {package_path}')

    # Canonical publish rule: all remote assets must be staged locally before
    # Chromium starts. This keeps the visible browser on the Facebook-only path.
    pkg = load_json(package_path, {})
    if pkg.get('image_url') and not pkg.get('image_asset_name'):
        raise RuntimeError('PACKAGE_NOT_STAGED: remote image_url must be converted to image_asset_name before PUBLISH')
    if pkg.get('image_asset_name'):
        staged_asset = ASSET_OUT_DIR / str(pkg.get('image_asset_name'))
        if not staged_asset.exists():
            sync_binary_assets()
        if not staged_asset.exists():
            raise RuntimeError(f'PACKAGE_NOT_STAGED: local asset missing: {staged_asset}')

    cmd = [sys.executable, str(HERE/'group_poster.py'), '--package', str(package_path), '--confirm-post', '--output-dir', str(HERE/'output')]
    log(f'START command_id={command_id} package={package}')
    # Hard-stop a wedged poster so Chromium/Playwright children cannot pile up
    # across Scheduled Task restarts.  Three minutes is ample for the normal
    # single-group path; multi-group packages scale the budget conservatively.
    group_count = len(pkg.get('group_urls') or ([pkg.get('group_url')] if pkg.get('group_url') else []))
    poster_timeout = max(180, 90 + max(1, group_count) * 90)
    p = subprocess.Popen(
        cmd,
        cwd=str(HERE),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=CREATE_NO_WINDOW,
    )
    try:
        stdout, stderr = p.communicate(timeout=poster_timeout)
        p.stdout_text = stdout
        p.stderr_text = stderr
    except subprocess.TimeoutExpired:
        # Kill the whole Windows process tree, including Playwright Chromium
        # helpers, so no orphan browser survives to consume RAM/disk or hold the
        # Group Poster mutex.
        if sys.platform == 'win32':
            subprocess.run(
                ['taskkill', '/PID', str(p.pid), '/T', '/F'],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=CREATE_NO_WINDOW,
            )
        else:
            p.kill()
        p.communicate()
        raise RuntimeError(f'GROUP_POSTER_TIMEOUT after {poster_timeout}s')

    if getattr(p, 'stdout_text', ''):
        for line in p.stdout_text.splitlines():
            log(f'POSTER_OUT {line}')
    if getattr(p, 'stderr_text', ''):
        for line in p.stderr_text.splitlines():
            log(f'POSTER_ERR {line}')
    if p.returncode != 0:
        detail = (getattr(p, 'stderr_text', '') or getattr(p, 'stdout_text', '') or '').strip().splitlines()
        tail = detail[-1] if detail else 'no detail'
        raise RuntimeError(f'Group Poster exited with code {p.returncode}: {tail}')
    log(f'DONE command_id={command_id}')
    return command_id

def process_local_queue(state):
    """Execute the queue already present on disk without waiting for GitHub."""
    sync_binary_assets()
    queue = load_json(QUEUE, {'action':'IDLE'})
    command_id = str(queue.get('command_id') or '').strip()
    action = str(queue.get('action') or 'IDLE').upper()
    if action not in {'PUBLISH','PING','SCAN_GROUPS','VERIFY_GROUPS','LOGIN'}:
        return state
    if not command_id or command_id == state.get('last_command_id'):
        return state

    try:
        done_id = run_command(queue)
        state = {
            'last_command_id': done_id,
            'last_status': 'SUCCESS',
            'updated_at': datetime.now().isoformat(timespec='seconds'),
        }
        save_json(STATE, state)
        try:
            publish_status_to_repo()
        except Exception as exc:
            log(f'STATUS_PUBLISH_WARNING {exc}')
    except Exception as exc:
        state = {
            'last_command_id': command_id,
            'last_status': 'ERROR',
            'error': str(exc),
            'updated_at': datetime.now().isoformat(timespec='seconds'),
        }
        save_json(STATE, state)
        log(f'COMMAND_ERROR command_id={command_id} error={exc}')
        try:
            publish_status_to_repo()
        except Exception as status_exc:
            log(f'STATUS_PUBLISH_WARNING {status_exc}')
    return state


def main():
    if not acquire_single_instance():
        log('AGENT_ALREADY_RUNNING')
        return 0

    log('AGENT_STARTED')
    state = load_json(STATE, {'last_command_id': None, 'last_status': None})
    state['agent_status'] = 'RUNNING'
    state['agent_started_at'] = datetime.now().isoformat(timespec='seconds')
    state['agent_pid'] = os.getpid()
    state['agent_python'] = sys.executable
    save_json(STATE, state)

    # Critical path: run whatever queue is already on disk immediately.
    # Do not let startup status publishing or GitHub connectivity delay Chromium.
    try:
        state = process_local_queue(state)
    except Exception as exc:
        log(f'LOCAL_QUEUE_WARNING {exc}')

    while True:
        try:
            # Refresh from GitHub when possible, but a Git failure is non-fatal.
            # If a new queue arrives, execute it immediately in this same cycle.
            pulled = git_pull()
            if pulled:
                state = process_local_queue(state)

            # Also re-check local queue every cycle so manually/local-written
            # commands do not depend on a successful network sync.
            state = process_local_queue(state)
            time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            log('AGENT_STOPPED')
            return 0
        except Exception as exc:
            log(f'AGENT_WARNING {exc}')
            time.sleep(POLL_SECONDS)

if __name__ == '__main__':
    raise SystemExit(main())
