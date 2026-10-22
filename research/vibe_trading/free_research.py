"""Offline pinned Vibe calculations; descriptive evidence, never trading signals."""
import argparse
from collections import defaultdict
from decimal import Decimal
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = ROOT/'research_data/vibe-trading/upstream'


def finite(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def select_events(ledger, through, cutoff):
    seen, selected = set(), []
    for event in ledger['outcomes']:
        # Only current code/policy period and mature checkpoints; never fill missing returns.
        if event['at'] < cutoff or event['at'][:10] > through or event['id'] in seen:
            continue
        if finite(event.get('returns', {}).get('30')) is not None:
            seen.add(event['id'])
            selected.append(event)
    return selected


def join_features(events, decisions):
    wanted = {(e['id'], e['at']): e for e in events}
    rows = []
    with decisions.open(encoding='utf-8') as stream:
        for line in stream:
            frame = json.loads(line)
            for item in frame['decisions']:
                key = (item.get('event_id'), frame['at'])
                event = wanted.pop(key, None)
                if event is None:
                    continue
                context = item.get('market_context', {})
                relative = context.get('relative_returns', {})
                rs = [finite(relative.get(k)) for k in ('KOSPI', 'KOSDAQ')]
                rows.append({'id': event['id'], 'at': event['at'], 'symbol': event['symbol'],
                    'strategy': event['strategy'], 'reasons': event['reasons'],
                    'return_30m': finite(event['returns']['30']),
                    'relative_volume': finite(item.get('metrics', {}).get('relative_volume')),
                    'relative_strength': min(rs) if all(v is not None for v in rs) else None})
    return rows, len(wanted)


def cohorts(rows):
    groups = defaultdict(list)
    for row in rows:
        reasons = row['reasons']
        label = 'eligible' if not reasons else 'only:'+reasons[0] if len(reasons) == 1 else 'multiple_blocks'
        groups[row['strategy']+'/'+label].append(row)
    result = {}
    for name, sample in groups.items():
        values = sorted(r['return_30m'] for r in sample)
        days = sorted({r['at'][:10] for r in sample})
        result[name] = {'episodes': len(sample), 'days': days,
            'mean_net_return_30m': sum(values)/len(values),
            'median_net_return_30m': (values[(len(values)-1)//2]+values[len(values)//2])/2,
            'mean_without_best_one': sum(values[:-1])/len(values[:-1]) if len(values)>1 else None,
            'status': 'exploratory_only' if len(sample)>=20 and len(days)>=5 else 'insufficient_sample'}
    return result


def analyze(source, through, output):
    import pandas as pd
    pin = json.loads((ROOT/'research/vibe_trading/upstream.json').read_text())['commit']
    if subprocess.check_output(['git','-C',str(UPSTREAM),'rev-parse','HEAD'],text=True).strip() != pin:
        raise ValueError('upstream_revision_mismatch')
    if subprocess.check_output(['git','-C',str(UPSTREAM),'status','--porcelain'],text=True).strip():
        raise ValueError('upstream_modified')
    # Pure math imports only, with provider credentials removed from this process.
    basics = {'SYSTEMROOT','WINDIR','SYSTEMDRIVE','COMSPEC','PATH','PATHEXT','TEMP','TMP'}
    for key in list(os.environ):
        if key.upper() not in basics:
            del os.environ[key]
    sys.path.insert(0, str(UPSTREAM/'agent'))
    from backtest.validation import monte_carlo_test
    spec = importlib.util.spec_from_file_location('vibe_factor_math', UPSTREAM/'agent/src/factors/factor_analysis_core.py')
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    raw = (source/'ledger.json').read_bytes()
    ledger = json.loads(raw)
    transitions = ledger.get('policy_transitions', [])
    cutoff = max((p['at'] for p in transitions if p['at'][:10]<=through), default='0000')
    events = select_events(ledger, through, cutoff)
    rows, missing = join_features(events, source/'decisions.jsonl')
    factors = {}
    for strategy in sorted({r['strategy'] for r in rows}):
        for feature in ('relative_volume', 'relative_strength'):
            sample = [r for r in rows if r['strategy']==strategy and r[feature] is not None]
            if not sample:
                factors[strategy+'/'+feature] = {'status':'insufficient_sample','snapshots':0}
                continue
            table = pd.DataFrame(sample)
            # Exact observation time, no broad buckets that mix future observations.
            x = table.pivot(index='at', columns='symbol', values=feature)
            y = table.pivot(index='at', columns='symbol', values='return_30m')
            ic = core.compute_ic_series(x, y)
            factors[strategy+'/'+feature] = {
                'status':'exploratory_only' if len(ic)>=20 and len({str(t)[:10] for t in ic.index})>=5 else 'insufficient_sample',
                'snapshots':len(ic), 'mean_rank_ic':float(ic.mean()) if len(ic) else None,
                'per_snapshot':{str(k):float(v) for k,v in ic.items()},
                'minimum_symbols_per_snapshot':5}
    paths = {}
    for account, state in ledger['accounts'].items():
        history = sorted((t for t in state['trades'] if t['exit_at'][:10]<=through),key=lambda t:t['exit_at'])
        chosen = [t for t in history if t['opened_at']>=cutoff]
        capital = Decimal(state['initial']) + sum((Decimal(t['net']) for t in history if t['exit_at']<cutoff),Decimal(0))
        # Crossing trades prevent a clean flat start; do not silently omit their exposure.
        if any(t['opened_at']<cutoff<=t['exit_at'] for t in history) or capital<=0:
            paths[account]={'status':'invalid_starting_capital_or_crossing_trade'}
        elif len(chosen)<3:
            paths[account]={'status':'insufficient_sample','trades':len(chosen)}
        else:
            result = monte_carlo_test([SimpleNamespace(pnl=float(t['net'])) for t in chosen],float(capital),n_simulations=1000,seed=42,bars_per_year=1)
            # Suppress Sharpe/p-values: a trade-order permutation is not a profitability test.
            paths[account]={'status':'path_stress_only','trades':len(chosen),
                'initial_realized_capital_krw':str(capital),
                'actual_closed_trade_max_drawdown_rate':result['actual_max_dd'],
                'equity_paths':result.get('equity_paths'), 'simulations':1000,'seed':42}
    result = {'schema':1,'through':through,'cutoff':cutoff,'upstream_commit':pin,
        'source_ledger_sha256':hashlib.sha256(raw).hexdigest(),
        'mature_events':len(events),'matched_events':len(rows),'missing_exact_decision':missing,
        'condition_cohorts':cohorts(rows),'factor_rank_ic':factors,'trade_order_stress':paths,
        'automatic_policy_change':False,'llm_calls':False,
        'limitations':['30m bid/ask follow-ups are NOT portfolio returns or executable alternative trades.',
            'Only recorded structural episodes with mature observations; missing outcomes may bias the sample.',
            'Overlapping outcomes and cross-strategy signals are dependent; no IID significance claim.',
            'Permutation preserves total profit; it measures realized path sensitivity, not future profitability.',
            'Drawdown excludes unrealized losses; bootstrap Sharpe and walk-forward optimization are not enabled.']}
    if output.exists():
        raise ValueError('output_already_exists')
    output.mkdir(parents=True)
    (output/'episodes.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    (output/'analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    lines=['# 무료 연구 기능 분석', '', f'기준일: {through}; 동일 정책/코드 기간 시작: {cutoff}',
        f'30분 결과가 있는 에피소드 {len(events)}개, 최초 관측과 정확히 연결된 에피소드 {len(rows)}개.', '',
        '## 조건별 관측 결과', '', '|전략/조건|에피소드|30분 평균 순수익률|최고 1건 제외 평균|판정|','|---|---:|---:|---:|---|']
    for name,c in result['condition_cohorts'].items():
        trimmed = f"{c['mean_without_best_one']:.3%}" if c['mean_without_best_one'] is not None else 'N/A'
        lines.append(f"|{name}|{c['episodes']}|{c['mean_net_return_30m']:.3%}|{trimmed}|{c['status']}|")
    lines += ['', '## 해석 제한', '', *['- '+s for s in result['limitations']], '',
        '상세 순위 상관과 거래 순서별 자산 경로는 analysis.json에 있다. 표본 부족은 0점이나 효과 없음으로 해석하지 않는다.']
    (output/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return {'path':str(output/'analysis.json'),'report':str(output/'REPORT.md'),
            'mature_events':len(events),'matched_events':len(rows),'schema':1,'llm_calls':False}


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--through',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--source',type=Path,default=ROOT/'reports/paper_lab_v3')
    args=parser.parse_args()
    from datetime import date
    date.fromisoformat(args.through)
    print(json.dumps(analyze(args.source,args.through,args.output)))
