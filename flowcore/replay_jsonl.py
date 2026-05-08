from __future__ import annotations

import argparse
import json
from decimal import Decimal

from .cli import encode, signal_to_dict
from .config import InstrumentConfig, StrategyConfig
from .data import load_events_jsonl
from .engine import ReplayEngine


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay recorded Antarctica JSONL market events.")
    parser.add_argument("paths", nargs="+", help="JSONL files written by flowcore.recorder")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--tick-size", required=True, type=Decimal)
    parser.add_argument("--lot-size", default=1, type=int)
    parser.add_argument("--wall-ratio", default=Decimal("3"), type=Decimal)
    parser.add_argument("--summary", action="store_true", help="Print a summary line after replay.")
    args = parser.parse_args()

    instrument = InstrumentConfig(args.symbol, args.tick_size, args.lot_size)
    engine = ReplayEngine(instrument, StrategyConfig(wall_ratio=args.wall_ratio))
    event_count = 0
    signal_count = 0

    for path in args.paths:
        for event in load_events_jsonl(path):
            event_count += 1
            for signal in engine.process(event):
                signal_count += 1
                payload = signal_to_dict(signal)
                payload["kind"] = "signal"
                payload["source_file"] = path
                print(json.dumps(payload, ensure_ascii=False, default=encode))

    if args.summary:
        print(
            json.dumps(
                {
                    "kind": "summary",
                    "symbol": args.symbol,
                    "files": len(args.paths),
                    "events": event_count,
                    "signals": signal_count,
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
