import base64
import json
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
ASSET_OUT_DIR = REPO / 'facebook_assets'
CREATE_NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0

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
        if out_path.exists() and out_path.read_bytes() == raw:
            continue
        out_path.write_bytes(raw)
        log(f"ASSET_SYNCED {output_name} bytes={len(raw)}")


def publish_status_to_repo():
    """Commit lightweight agent status/report so ChatGPT can observe local runs."""
    targets = [STATE]
    report = HERE / "output" / "group_batch_report.json"
    if report.exists():
        targets.append(report)
    rels = [str(p.relative_to(REPO)) for p in targets if p.exists()]
    if not rels:
        return
    subprocess.run(["git","-C",str(REPO),"add","-f",*rels], capture_output=True, text=True, timeout=30, creationflags=CREATE_NO_WINDOW)
    diff = subprocess.run(["git","-C",str(REPO),"diff","--cached","--quiet"], capture_output=True, text=True, timeout=30, creationflags=CREATE_NO_WINDOW)
    if diff.returncode == 0:
        return
    msg = f"Agent status {datetime.now().isoformat(timespec='seconds')}"
    c = subprocess.run(["git","-C",str(REPO),"commit","-m",msg], capture_output=True, text=True, timeout=60, creationflags=CREATE_NO_WINDOW)
    if c.returncode != 0:
        log(f"STATUS_COMMIT_WARNING {(c.stderr or c.stdout).strip()}")
        return
    p = subprocess.run(["git","-C",str(REPO),"push","origin","HEAD:main"], capture_output=True, text=True, timeout=60, creationflags=CREATE_NO_WINDOW)
    if p.returncode != 0:
        log(f"STATUS_PUSH_WARNING {(p.stderr or p.stdout).strip()}")
    else:
        log("STATUS_PUSHED")


    p = subprocess.run(['git','-C',str(REPO),'pull','--ff-only'], capture_output=True, text=True, timeout=60, creationflags=CREATE_NO_WINDOW)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or 'git pull failed').strip())

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
    if action != 'PUBLISH':
        return None
    if not command_id or not package:
        raise RuntimeError('PUBLISH queue requires command_id and package')
    package_path = REPO / package
    if not package_path.exists():
        raise RuntimeError(f'Package not found: {package_path}')
    cmd = [sys.executable, str(HERE/'group_poster.py'), '--package', str(package_path), '--confirm-post', '--output-dir', str(HERE/'output')]
    log(f'START command_id={command_id} package={package}')
    p = subprocess.run(cmd, cwd=str(HERE), text=True, creationflags=CREATE_NO_WINDOW)
    if p.returncode != 0:
        raise RuntimeError(f'Group Poster exited with code {p.returncode}')
    log(f'DONE command_id={command_id}')
    return command_id

def main():
    log('AGENT_STARTED')
    state = load_json(STATE, {'last_command_id': None, 'last_status': None})
    while True:
        try:
            git_pull()
            sync_binary_assets()
            queue = load_json(QUEUE, {'action':'IDLE'})
            command_id = str(queue.get('command_id') or '').strip()
            if str(queue.get('action') or 'IDLE').upper() in {'PUBLISH','PING','SCAN_GROUPS','VERIFY_GROUPS'} and command_id and command_id != state.get('last_command_id'):
                try:
                    done_id = run_command(queue)
                    state = {'last_command_id': done_id, 'last_status':'SUCCESS', 'updated_at':datetime.now().isoformat(timespec='seconds')}
                    save_json(STATE, state)
                    publish_status_to_repo()
                except Exception as exc:
                    state = {'last_command_id': command_id, 'last_status':'ERROR', 'error':str(exc), 'updated_at':datetime.now().isoformat(timespec='seconds')}
                    save_json(STATE, state)
                    log(f'COMMAND_ERROR command_id={command_id} error={exc}')
                    publish_status_to_repo()
            time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            log('AGENT_STOPPED')
            return 0
        except Exception as exc:
            log(f'AGENT_WARNING {exc}')
            time.sleep(POLL_SECONDS)

if __name__ == '__main__':
    raise SystemExit(main())
