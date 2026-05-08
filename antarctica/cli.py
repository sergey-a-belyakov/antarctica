from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from decimal import Decimal

from .config import InstrumentConfig, StrategyConfig
from .data import load_book_csv, load_trades_csv, merge_events
from .engine import ReplayEngine
from .models import BookSide
from .signals import Signal, SignalSide, SignalType


def encode(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (BookSide, SignalSide, SignalType)):
        return value.value
    raise TypeError(f"Cannot encode {type(value)!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay MOEX Level II data through Antarctica MVP.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--tick-size", required=True, type=Decimal)
    parser.add_argument("--lot-size", default=1, type=int)
    parser.add_argument("--book", required=True, help="CSV with order book snapshots")
    parser.add_argument("--trades", required=True, help="CSV with time and sales")
    parser.add_argument("--wall-ratio", default=Decimal("3"), type=Decimal)
    args = parser.parse_args()

    instrument = InstrumentConfig(args.symbol, args.tick_size, args.lot_size)
    config = StrategyConfig(wall_ratio=args.wall_ratio)
    events = list(merge_events(load_book_csv(args.book), load_trades_csv(args.trades)))
    signals = ReplayEngine(instrument, config).run(events)
    for signal in signals:
        print(json.dumps(signal_to_dict(signal), ensure_ascii=False, default=encode))
    return 0


def signal_to_dict(signal: Signal) -> dict[str, object]:
    return asdict(signal)


if __name__ == "__main__":
    raise SystemExit(main())
