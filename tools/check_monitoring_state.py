from __future__ import annotations

import argparse
import csv
import io
import json
import math
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = "paper_trade/state.json"
EQUITY_PATH = "paper_trade/equity.csv"
TRADES_PATH = "paper_trade/trades.csv"
DATA_PATH = "data/eth_usdt_4h.csv"


def git_text(ref: str, relative: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{ref}:{relative}"], cwd=ROOT,
        text=True, capture_output=True, check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"无法读取 {ref}:{relative}")
    return result.stdout


def csv_rows(text: str, path: str) -> list[dict[str, str]]:
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise ValueError(f"{path} 没有数据行")
    return rows


def normalized_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def evaluate(ref: str) -> list[str]:
    errors: list[str] = []
    state = json.loads(git_text(ref, STATE_PATH))
    equity_rows = csv_rows(git_text(ref, EQUITY_PATH), EQUITY_PATH)
    trade_rows = list(csv.DictReader(io.StringIO(git_text(ref, TRADES_PATH))))
    data_rows = csv_rows(git_text(ref, DATA_PATH), DATA_PATH)

    required = {"equity", "pos_side", "trade_count", "last_processed"}
    missing = sorted(required - state.keys())
    if missing:
        return [f"{STATE_PATH} 缺少字段：{', '.join(missing)}"]

    try:
        last_processed = normalized_time(str(state["last_processed"]))
        equity_time = normalized_time(equity_rows[-1]["timestamp"])
        data_time = normalized_time(data_rows[-1]["timestamp"])
        state_equity = float(state["equity"])
        recorded_equity = float(equity_rows[-1]["equity"])
        state_position = int(state["pos_side"])
        recorded_position = int(equity_rows[-1]["position"])
        trade_count = int(state["trade_count"])
    except (KeyError, TypeError, ValueError) as exc:
        return [f"监控状态字段无法解析：{exc}"]

    if last_processed != equity_time:
        errors.append(f"equity 尾时间 {equity_time} != state.last_processed {last_processed}")
    if last_processed != data_time:
        errors.append(f"行情尾时间 {data_time} != state.last_processed {last_processed}")
    if not math.isclose(state_equity, recorded_equity, rel_tol=0, abs_tol=0.0001):
        errors.append(f"equity 尾值 {recorded_equity} != state.equity {state_equity}")
    if state_position not in {-1, 0, 1}:
        errors.append(f"state.pos_side 不合法：{state_position}")
    if state_position != recorded_position:
        errors.append(f"equity 尾仓位 {recorded_position} != state.pos_side {state_position}")
    if trade_count != len(trade_rows):
        errors.append(f"trades 行数 {len(trade_rows)} != state.trade_count {trade_count}")
    if trade_rows:
        try:
            last_trade_id = int(trade_rows[-1]["trade_id"])
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"最后一笔 trade_id 无法解析：{exc}")
        else:
            if last_trade_id != trade_count:
                errors.append(f"最后 trade_id {last_trade_id} != state.trade_count {trade_count}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="检查远端 paper trade 文件的内部一致性")
    parser.add_argument("--ref", default="HEAD", help="Git ref，默认 HEAD")
    args = parser.parse_args()
    try:
        errors = evaluate(args.ref)
    except (OSError, RuntimeError, json.JSONDecodeError, ValueError) as exc:
        print(f"UNVERIFIED: 无法读取监控状态：{exc}")
        return 2
    if errors:
        print(f"FAIL: {args.ref} 的监控状态不一致")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"PASS: {args.ref} 的行情、状态、权益与交易记录一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
