"""Offline bridge to pinned HKUDS Vibe-Trading; never imports an order engine."""
import argparse
import csv
from datetime import date, datetime
from decimal import Decimal as D
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RUNTIME = ROOT / "research_data" / "vibe-trading"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")


def statistics(trades):
    values = [D(t["net"]) for t in trades]
    winners = sorted((v for v in values if v > 0), reverse=True)
    total = sum(values, D(0))
    equity = peak = drawdown = D(0)
    days = {}
    for t, value in zip(trades, values):
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak-equity)
        day = t["exit_at"][:10]
        days[day] = days.get(day, D(0))+value
    return {"trades": len(trades), "net_pnl_krw": str(total),
            "net_per_trade_krw": str(total/len(trades)) if trades else None,
            "win_rate": str(D(len(winners))/len(trades)) if trades else None,
            "net_without_best_one_krw": str(total-sum(winners[:1], D(0))),
            "net_without_best_two_krw": str(total-sum(winners[:2], D(0))),
            "closed_trade_drawdown_krw": str(drawdown),
            "cost_stress_net_krw": str(sum((D(t["stress_net"]) for t in trades), D(0))),
            "daily_net_krw": {k: str(v) for k,v in days.items()},
            "exit_reasons": {r: sum(t["reason"] == r for t in trades) for r in sorted({t["reason"] for t in trades})},
            "holding_seconds": [t["hold_seconds"] for t in trades]}


def fills(trade, symbol, policy):
    q = int(trade["quantity"])
    entry, cost, net = (D(trade[k]) for k in ("entry", "entry_cost", "net"))
    sell = D(trade["exit"])*(1-D(policy["slippage_bps"])/10000)
    buy_fee = cost-entry*q
    sell_fee = sell*q-(cost+net)
    if q <= 0 or min(entry, sell) <= 0 or min(buy_fee, sell_fee) < 0:
        raise ValueError("unsupported_trade_cost_contract")
    # Exchange suffix is supplied by verified stock metadata, never guessed.
    common = {"symbol": symbol, "quantity": str(q)}
    return [{**common, "datetime": trade["opened_at"], "side": "buy", "price": str(entry), "fee": str(buy_fee)},
            {**common, "datetime": trade["exit_at"], "side": "sell", "price": str(sell), "fee": str(sell_fee)}]


def load_markets(symbols, refresh=False):
    path = RUNTIME / "symbol_markets.json"
    mapping = read(path) if path.exists() else {}
    missing = sorted(set(symbols)-set(mapping))
    if missing and refresh:
        sys.path.insert(0, str(ROOT/"src"))
        from toss_trader.cli import _client
        from toss_trader.config import Settings
        # Only a public instrument-metadata read. No credentials are exported.
        for stock in _client(Settings.from_project(ROOT)).stocks(missing):
            market = stock.get("market")
            if market in ("KOSPI", "KOSDAQ"):
                mapping[stock["symbol"]] = market
        write(path, mapping)
    if set(symbols)-set(mapping):
        raise ValueError("Missing exchange metadata; use --refresh-symbols for read-only Toss metadata")
    return mapping


def export_bundle(source, through, output, refresh=False):
    date.fromisoformat(through)
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("Use a new output directory to preserve research results")
    raw = (source/"ledger.json").read_bytes()
    ledger = json.loads(raw)
    manifest = read(source/"manifest.json")
    selected = {name: sorted((t for t in a["trades"] if t["exit_at"][:10] <= through), key=lambda t: t["exit_at"])
                for name,a in ledger["accounts"].items()}
    markets = load_markets([t["symbol"] for ts in selected.values() for t in ts], refresh)
    output.mkdir(parents=True)
    summary = {}
    for name, trades in selected.items():
        account = output/name.replace("/", "__")
        account.mkdir()
        rows = []
        for t in trades:
            suffix = {"KOSPI": ".KS", "KOSDAQ": ".KQ"}[markets[t["symbol"]]]
            rows.extend(fills(t, t["symbol"]+suffix, manifest["policy"]))
        rows.sort(key=lambda r: r["datetime"])
        with (account/"journal.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["datetime", "symbol", "side", "quantity", "price", "fee"])
            writer.writeheader()
            writer.writerows(rows)
        summary[name] = statistics(trades)
        # Whitelist only the fields needed for research; omit broker identifiers.
        write(account/"trades.json", [{k: t.get(k) for k in
              ("symbol", "opened_at", "exit_at", "reason", "net", "stress_net", "hold_seconds", "market_context")} for t in trades])
    snapshot = source/"daily"/(through+".json")
    report = read(snapshot) if snapshot.exists() else None
    write(output/"summary.json", summary)
    write(output/"evidence.json", {"through": through, "ledger_sha256": hashlib.sha256(raw).hexdigest(),
          "symbol_markets": {k: markets[k] for k in sorted({t['symbol'] for ts in selected.values() for t in ts})},
          "source_hash": manifest["source_hash"], "policy": manifest["policy"],
          "policy_transitions_present": bool(ledger.get("policy_transitions")),
          "market_shadow_diagnostic": report.get("market_shadow_summary") if report else None,
          "source_note": "Cumulative closed trades; earlier policy periods remain included. No portfolio aggregation across accounts."})
    write(output/"upstream.json", read(HERE/"upstream.json"))
    write(output/"strategy_contract.json", {
        "mode": "paper_research_only", "policy": manifest["policy"],
        "strategies": {
            "opening_control": {"entry": "completed close crosses the 09:01..09:30 opening high", "stop": "opening high - 1 ATR"},
            "pullback": {"entry": "rising short/long average; 0.5..3 ATR pullback with red candle; prior high recovery", "stop": "pullback low - 0.25 ATR"},
            "range_breakout": {"entry": "prior 10-bar width <= 4 ATR; completed close crosses range high", "stop": "range low - 0.25 ATR"}},
        "exit": ["structural stop", "after 1R gain, completed-bar 2ATR trailing", "30 minutes with bid <= entry + 0.5R", "15:15 session exit", "daily loss guard"],
        "research_role": "analyze journals and propose hypotheses; deployment remains a separate action",
        "authoritative_source": "archived source_hash in evidence.json; this text is an explanation, not executable strategy"})
    (output/"RESEARCH_TASK.md").write_text(
        "# Toss paper v3 연구 요청\n\n"
        "summary.json과 계좌별 trades.json, journal.csv를 근거로 세 전략을 비교한다.\n"
        "모든 금액은 KRW이며 연구/예산 계좌를 합산하지 않는다.\n"
        "시초 돌파, 눌림목, 횡보 돌파를 거래당 순손익, 청산 사유, 보유 초,\n"
        "최대 누적 실현손실, 최대 수익 1/2건 제외, 비용 2배로 평가한다.\n"
        "상대 강도/방어형 shadow 평균은 실제 포트폴리오 손익이 아니다.\n"
        "학습기간과 검증기간을 분리하고 결측 호가/미청산 손실을 명시한다.\n"
        "청산 기간 15/30/45분 비교는 원시 tape 재현 없이는 결과를 만들지 않는다.\n"
        "개선 가설은 수치 근거와 함께 제안하되 운영 설정을 자동 변경하지 않는다.\n"
        "실현손실 곡선은 미실현 손익을 포함한 평가손실 곡선과 다르다.\n",
        encoding="utf-8")
    return summary


def analyze_bundle(bundle):
    """Runs inside the isolated dependency environment, using real upstream code."""
    basics = {"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP"}
    for key in list(os.environ):
        if key.upper() not in basics:
            del os.environ[key]
    bundle = Path(bundle).resolve()
    upstream = RUNTIME/"upstream"
    pin = read(HERE/"upstream.json")["commit"]
    actual = subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip()
    if actual != pin or subprocess.check_output(["git", "-C", str(upstream), "status", "--porcelain"], text=True).strip():
        raise ValueError("Upstream revision differs or has local edits")
    sys.path.insert(0, str(upstream/"agent"))
    os.environ["VIBE_TRADING_HOME"] = str(RUNTIME/"home")
    (RUNTIME/"home").mkdir(parents=True, exist_ok=True)
    os.environ["USERPROFILE"] = str(RUNTIME/"home")
    os.environ["VIBE_TRADING_ALLOWED_FILE_ROOTS"] = str(bundle)
    from src.tools import trade_journal_tool as journal_tool
    # Upstream's six-digit Korean regex misroutes newer alphanumeric KRX codes.
    # Bind currency only for exact instruments verified by Toss metadata.
    markets = read(bundle/"evidence.json")["symbol_markets"]
    known = {code+{"KOSPI": ".KS", "KOSDAQ": ".KQ"}[market] for code,market in markets.items()}
    original_currency = journal_tool.code_currency
    def verified_currency(code):
        return "KRW" if code in known else original_currency(code)
    journal_tool.code_currency = verified_currency
    summary = read(bundle/"summary.json")
    result = {}
    for name, canonical in summary.items():
        if not canonical["trades"]:
            result[name] = {"status": "no_trades"}
            continue
        journal = bundle/name.replace("/", "__")/"journal.csv"
        upstream_result = json.loads(journal_tool.analyze_trade_journal(str(journal), analysis_type="full"))
        if upstream_result.get("status") != "ok":
            raise ValueError("Upstream journal analysis failed: "+name)
        pnl = upstream_result["profile"]["total_pnl"]
        if isinstance(pnl, dict):
            raise ValueError("Unexpected currency aggregation")
        difference = abs(D(str(pnl))-D(canonical["net_pnl_krw"]))
        if difference > D("0.011")*canonical["trades"]:
            raise ValueError("FIFO PnL reconciliation failed: "+name)
        result[name] = {"analysis": upstream_result, "reconciliation_difference_krw": str(difference),
                        "canonical": canonical}
    write(bundle/"vibe_analysis.json", result)
    lines = ["# Toss × Vibe-Trading 분석", "", "원화 기준 비용 차감 후 실현손익. 계좌별 독립 평가.", "",
             "| 계좌 | 거래 | 순손익 | 최대 수익 1건 제외 | FIFO 대조 차이 |", "|---|---:|---:|---:|---:|"]
    for name, a in summary.items():
        diff = result[name].get("reconciliation_difference_krw", "—")
        lines.append(f"| {name} | {a['trades']} | {a['net_pnl_krw']} | {a['net_without_best_one_krw']} | {diff} |")
    lines.extend(["", "정책 변경 전후 누적 거래가 포함된다. Vibe-Trading의 일부 보유기간은 일 단위 반올림되므로 원장의 초 단위 값을 사용한다.",
                  "한국 종목의 통화는 KRW로 대조한다. upstream journal의 market 라벨은 other일 수 있다.",
                  "이 분석은 기존 거래일지 분석이며 별도 전략 백테스트·LLM 분석·자동 배포 결과가 아니다."])
    (bundle/"REPORT.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    return {name: {"trades": a["trades"], "net_pnl_krw": a["net_pnl_krw"]} for name,a in summary.items()}


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--source", type=Path, default=ROOT/"reports/paper_lab_v3")
    export.add_argument("--through", required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--refresh-symbols", action="store_true")
    analyze = commands.add_parser("analyze")
    analyze.add_argument("bundle", type=Path)
    args = parser.parse_args()
    result = (export_bundle(args.source, args.through, args.output, args.refresh_symbols)
              if args.command == "export" else analyze_bundle(args.bundle))
    if args.command == "export":
        result = {name: {k: a[k] for k in ("trades", "net_pnl_krw")} for name,a in result.items()}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
