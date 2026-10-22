"""Idempotently register deterministic workers with a loopback Paperclip server."""
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
BASE = 'http://127.0.0.1:3100'


def api(path, payload=None, method=None):
    request = urllib.request.Request(BASE+'/api'+path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Content-Type': 'application/json', 'Origin': BASE}, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def bootstrap():
    companies = api('/companies')
    matches = [c for c in companies if c['name'] == 'Toss Paper Lab']
    if len(matches) > 1:
        raise ValueError('ambiguous_company')
    company = matches[0] if matches else api('/companies', {
        'name': 'Toss Paper Lab', 'description': 'Paper v3 operations and offline research; no live orders'})
    company_id = company['id']
    existing = {a['name']: a for a in api('/companies/'+company_id+'/agents')}
    result = {'base_url': BASE, 'company_id': company_id, 'agents': {}, 'version': '2026.1012.0'}
    for role in ['operations', 'performance', 'research', 'validation']:
        name = 'paper-'+role
        payload = {'name': name, 'role': 'general', 'title': role,
            'capabilities': 'Deterministic script worker; no LLM, no orders, no policy changes.',
            'adapterType': 'process', 'adapterConfig': {
                'command': str(ROOT/'.venv/Scripts/python.exe'),
                'args': [str(ROOT/'research/paperclip/worker.py'), role],
                'cwd': str(ROOT/'research/paperclip'), 'timeoutSec': 1500},
            'runtimeConfig': {'heartbeat': {'enabled': True, 'intervalSec': 300,
                              'wakeOnDemand': True, 'maxConcurrentRuns': 1}},
            'budgetMonthlyCents': 0}
        if name in existing:
            agent = api('/agents/'+existing[name]['id'], payload, 'PATCH')
        else:
            agent = api('/companies/'+company_id+'/agents', payload)
        result['agents'][role] = agent['id']
    target = ROOT/'state/paperclip.json'
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    bootstrap()
