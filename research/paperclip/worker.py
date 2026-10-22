"""Deterministic Paperclip workers. Read-only trading inputs, separate artifacts."""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'reports/paper_lab_v3'
OUTPUT = ROOT / 'research_output/paperclip'
KST = timezone(timedelta(hours=9))
START_DAY = '2026-10-22'


def publish(role, result, now=None):
    """Daily task per role; reconcile by exact title after a lost API response."""
    from bootstrap import api
    now = now or datetime.now(KST)
    cfg = read(ROOT/'state/paperclip.json')
    day = now.date().isoformat()
    title = day+' / '+role
    path = OUTPUT/day/(role+'-issue.json')
    failed = bool(result.get('alerts')) or result.get('status') == 'failed'
    status = 'blocked' if failed else 'done'
    description = json.dumps(result, ensure_ascii=False, indent=2)
    signature = json.dumps(result.get('alerts', [])) if role == 'operations' else description
    saved = read(path) if path.exists() else {}
    if saved.get('signature') == signature and saved.get('status') == status:
        return
    issue_id = saved.get('id')
    if not issue_id:
        issues = api('/companies/'+cfg['company_id']+'/issues')
        matches = [i for i in issues if i['title'] == title]
        if len(matches) > 1:
            raise ValueError('duplicate_daily_task')
        issue_id = matches[0]['id'] if matches else None
    payload = {'title': title, 'description': description, 'status': status,
               'assigneeAgentId': cfg['agents'][role]}
    issue = api('/issues/'+issue_id, payload, 'PATCH') if issue_id else api(
        '/companies/'+cfg['company_id']+'/issues', payload)
    write(path, {'id': issue['id'], 'signature': signature, 'status': status})


@contextmanager
def capacity():
    """Two local slots across all workers; crash-safe OS locks."""
    import msvcrt
    OUTPUT.mkdir(parents=True, exist_ok=True)
    acquired = None
    for slot in range(2):
        handle = (OUTPUT/('slot-'+str(slot)+'.lock')).open('a+b')
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            acquired = handle
            break
        except OSError:
            handle.close()
    try:
        yield acquired is not None
    finally:
        if acquired is not None:
            acquired.seek(0)
            msvcrt.locking(acquired.fileno(), msvcrt.LK_UNLCK, 1)
            acquired.close()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)


def operations(now, source=SOURCE):
    ledger = read(source/'ledger.json')
    heartbeat = datetime.fromisoformat(read(source/'heartbeat.json')['updated_at'])
    age = (now-heartbeat).total_seconds()
    in_session = now.weekday() < 5 and '09:02' <= now.strftime('%H:%M') < '15:40'
    alerts = []
    if in_session and (age > 120 or age < -2):
        alerts.append('heartbeat_stale_or_future')
    if ledger.get('entry_halt'):
        alerts.append('entry_halt')
    positions = sum(bool(a.get('position')) for a in ledger['accounts'].values())
    if now.strftime('%H:%M') >= '15:40' and positions:
        alerts.append('positions_after_close')
    return {'at': now.isoformat(), 'role': 'operations', 'alerts': alerts,
            'heartbeat_age_seconds': age, 'positions': positions,
            'last_ledger_at': ledger.get('last_at'), 'in_session': in_session}


def ready_for_close(day, source=SOURCE):
    ledger = read(source/'ledger.json')
    last = ledger.get('last_at') or ''
    if last[:10] != day or last[11:16] < '15:39':
        raise ValueError('day_not_finished_or_missing_data')
    if any(a.get('position') for a in ledger['accounts'].values()):
        raise ValueError('positions_still_open')
    if not (source/'daily'/(day+'.json')).exists():
        raise ValueError('daily_report_missing')
    return ledger


def research(day, source=SOURCE):
    counts, symbols = Counter(), {}
    observations = 0
    with (source/'decisions.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            frame = json.loads(line)
            if frame['at'][:10] != day:
                continue
            for item in frame['decisions']:
                observations += 1
                for reason in item.get('reasons', []):
                    key = item.get('strategy', 'universe') + ':' + item['status'] + ':' + reason
                    counts[key] += 1
                    symbols.setdefault(key, set()).add(item['symbol'])
    return {'role': 'research', 'day': day, 'observations': observations,
            'reason_observations': dict(counts.most_common()),
            'distinct_symbols_by_reason': {k: len(v) for k,v in symbols.items()},
            'interpretation': 'Repeated observations and distinct symbols, NOT independent episodes or counterfactual portfolio profit.',
            'next_experiment': 'Replay independent baseline/relative-strength/defensive portfolios before adopting filter changes.',
            'automatic_policy_change': False}


def performance(day, folder):
    # Use a fresh directory on every attempt; retain failed artifacts for diagnosis.
    bundle = folder / ('vibe-' + uuid.uuid4().hex)
    script = ROOT/'research/vibe_trading/bridge.py'
    commands = [
        [str(ROOT/'.venv/Scripts/python.exe'), str(script), 'export', '--through', day,
         '--output', str(bundle), '--refresh-symbols'],
        [str(ROOT/'research_data/vibe-trading/venv/Scripts/python.exe'), str(script), 'analyze', str(bundle)],
    ]
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=600)
        if result.returncode:
            # Never propagate provider errors/credentials into Paperclip task logs.
            raise RuntimeError('vibe_export_or_reconciliation_failed')
    return {'role': 'performance', 'day': day, 'bundle': str(bundle),
            'summary': read(bundle/'summary.json'), 'reconciliation_passed': True,
            'scope': 'Cumulative closed trades; policy periods and profiles must be separated.'}


def result_path(folder, role):
    return folder/(role + ('-v2' if role in ('research', 'validation') else '') + '.json')


def free_research(day, folder):
    bundle = folder/('free-vibe-'+uuid.uuid4().hex)
    command = [str(ROOT/'research_data/vibe-trading/venv/Scripts/python.exe'),
               str(ROOT/'research/vibe_trading/free_research.py'),
               '--through', day, '--output', str(bundle)]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=600)
    if completed.returncode:
        raise RuntimeError('free_research_failed')
    return json.loads(completed.stdout)


def validation(day, folder):
    perf, diagnostics = read(folder/'performance.json'), read(result_path(folder, 'research'))
    if perf['day'] != day or diagnostics['day'] != day or not perf['reconciliation_passed']:
        raise ValueError('invalid_analysis_dependencies')
    from decimal import Decimal
    verdicts = {}
    for name, metrics in perf['summary'].items():
        positive = all(Decimal(metrics[k]) > 0 for k in
                       ('net_pnl_krw', 'net_without_best_two_krw', 'cost_stress_net_krw'))
        verdicts[name] = 'needs_out_of_sample_replay' if positive else 'not_eligible_for_promotion'
    return {'day': day, 'role': 'validation', 'verdicts': verdicts,
            'free_research': diagnostics['free_research'],
            'automatic_policy_change': False, 'live_promotion': False,
            'limitations': ['Cumulative mixed-policy closed trades',
                           'No independent alternative-portfolio replay yet',
                           'No inference of strategy profit from rejection counts']}


def run(role, now=None):
    now = now or datetime.now(KST)
    day = now.date().isoformat()
    folder = OUTPUT/day
    folder.mkdir(parents=True, exist_ok=True)
    # OS byte-range lock is released on crash; file presence alone never blocks recovery.
    import msvcrt
    with (folder/(role+'.lock')).open('a+b') as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return {'status': 'already_running', 'role': role}
        try:
            if role == 'operations':
                result = operations(now)
            else:
                if day < START_DAY or now.weekday() >= 5 or now.strftime('%H:%M') < '15:45':
                    return {'status': 'outside_analysis_window', 'role': role}
                ready_for_close(day)
                if result_path(folder, role).exists():
                    return read(result_path(folder, role))
                if role == 'performance':
                    result = performance(day, folder)
                elif role == 'research':
                    result = research(day)
                    result['free_research'] = free_research(day, folder)
                else:
                    if not all(result_path(folder, r).exists() for r in ('performance', 'research')):
                        return {'status': 'waiting_dependencies', 'role': role}
                    result = validation(day, folder)
            write(result_path(folder, role), result)
            return result
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('role', choices=['operations', 'performance', 'research', 'validation'])
    args = parser.parse_args()
    try:
        with capacity() as available:
            result = run(args.role) if available else {'status': 'capacity_busy', 'role': args.role}
            if 'at' in result or 'day' in result:
                publish(args.role, result)
        print(json.dumps(result, ensure_ascii=True))
    except Exception as exc:
        # Class-only error to avoid leaking secrets from subprocesses/API responses.
        result = {'status': 'failed', 'role': args.role, 'error_type': type(exc).__name__}
        try:
            publish(args.role, result)
        except Exception:
            pass
        print(json.dumps(result))
        sys.exit(1)
