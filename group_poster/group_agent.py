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

def git_pull():
    p = subprocess.run(['git','-C',str(REPO),'pull','--ff-only'], capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or 'git pull failed').strip())

def run_command(queue):
    command_id = str(queue.get('command_id') or '').strip()
    action = str(queue.get('action') or 'IDLE').upper()
    package = str(queue.get('package') or '').strip()
    if action != 'PUBLISH':
        return None
    if not command_id or not package:
        raise RuntimeError('PUBLISH queue requires command_id and package')
    package_path = REPO / package
    if not package_path.exists():
        raise RuntimeError(f'Package not found: {package_path}')
    cmd = [sys.executable, str(HERE/'group_poster.py'), '--package', str(package_path), '--confirm-post', '--output-dir', str(HERE/'output')]
    log(f'START command_id={command_id} package={package}')
    p = subprocess.run(cmd, cwd=str(HERE), text=True)
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
            queue = load_json(QUEUE, {'action':'IDLE'})
            command_id = str(queue.get('command_id') or '').strip()
            if str(queue.get('action') or 'IDLE').upper() == 'PUBLISH' and command_id and command_id != state.get('last_command_id'):
                try:
                    done_id = run_command(queue)
                    state = {'last_command_id': done_id, 'last_status':'SUCCESS', 'updated_at':datetime.now().isoformat(timespec='seconds')}
                    save_json(STATE, state)
                except Exception as exc:
                    state = {'last_command_id': command_id, 'last_status':'ERROR', 'error':str(exc), 'updated_at':datetime.now().isoformat(timespec='seconds')}
                    save_json(STATE, state)
                    log(f'COMMAND_ERROR command_id={command_id} error={exc}')
            time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            log('AGENT_STOPPED')
            return 0
        except Exception as exc:
            log(f'AGENT_WARNING {exc}')
            time.sleep(POLL_SECONDS)

if __name__ == '__main__':
    raise SystemExit(main())
