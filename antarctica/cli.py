from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from decimal import Decimal

from .config import InstrumentConfig, StrategyConfig
from .data import MarketEvent, load_book_csv, load_trades_csv, merge_events
from .engine import ReplayEngine
from .moex import MoexIssAccessError, MoexIssClient
from .models import BookSide, BookSnapshot, Trade
from .signals import Signal, SignalSide, SignalType


def encode(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (BookSide, SignalSide, SignalType)):
        return value.value
    raise TypeError(f"Cannot encode {type(value)!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay MOEX Level II data through Antarctica MVP.")
    parser.add_argument("--source", choices=("csv", "moex"), default="csv")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--tick-size", type=Decimal)
    parser.add_argument("--lot-size", default=1, type=int)
    parser.add_argument("--book", help="CSV with order book snapshots")
    parser.add_argument("--trades", help="CSV with time and sales")
    parser.add_argument("--engine", default="stock")
    parser.add_argument("--market", default="shares")
    parser.add_argument("--board", default="TQBR")
    parser.add_argument("--polls", default=3, type=int)
    parser.add_argument("--interval-sec", default=1.0, type=float)
    parser.add_argument("--trades-limit", default=50, type=int)
    parser.add_argument(
        "--top-of-book",
        action="store_true",
        help="Use public best bid/offer instead of Level II orderbook. This is not a DOM replacement.",
    )
    parser.add_argument("--dump-events", action="store_true", help="Print fetched book/trade events as JSON lines.")
    parser.add_argument("--wall-ratio", default=Decimal("3"), type=Decimal)
    args = parser.parse_args()

    client = MoexIssClient()
    try:
        if args.source == "moex":
            info = client.security_info(args.symbol, args.engine, args.market, args.board)
            instrument = info.instrument
            events = client.poll_events(
                args.symbol,
                args.engine,
                args.market,
                args.board,
                polls=args.polls,
                interval_sec=args.interval_sec,
                use_top_of_book=args.top_of_book,
                trades_limit=args.trades_limit,
            )
        else:
            if args.tick_size is None:
                parser.error("--tick-size is required with --source csv")
            if args.book is None or args.trades is None:
                parser.error("--book and --trades are required with --source csv")
            instrument = InstrumentConfig(args.symbol, args.tick_size, args.lot_size)
            events = list(merge_events(load_book_csv(args.book), load_trades_csv(args.trades)))
    except MoexIssAccessError as exc:
        parser.error(f"{exc} Try --top-of-book for public best bid/offer data.")

    if args.dump_events:
        for event in events:
            print(json.dumps(event_to_dict(event), ensure_ascii=False, default=encode))

    config = StrategyConfig(wall_ratio=args.wall_ratio)
    signals = ReplayEngine(instrument, config).run(events)
    for signal in signals:
        print(json.dumps(signal_to_dict(signal), ensure_ascii=False, default=encode))
    return 0


def signal_to_dict(signal: Signal) -> dict[str, object]:
    return asdict(signal)


def event_to_dict(event: MarketEvent) -> dict[str, object]:
    if event.snapshot is not None:
        return {"kind": "book", "timestamp_ms": event.timestamp_ms, **snapshot_to_dict(event.snapshot)}
    if event.trade is not None:
        return {"kind": "trade", "timestamp_ms": event.timestamp_ms, **trade_to_dict(event.trade)}
    return {"kind": "unknown", "timestamp_ms": event.timestamp_ms}


def snapshot_to_dict(snapshot: BookSnapshot) -> dict[str, object]:
    return {
        "bids": [{"price": level.price, "size": level.size} for level in snapshot.bids],
        "asks": [{"price": level.price, "size": level.size} for level in snapshot.asks],
    }


def trade_to_dict(trade: Trade) -> dict[str, object]:
    return {
        "price": trade.price,
        "size": trade.size,
        "aggressor": trade.aggressor.value,
    }


if __name__ == "__main__":
    raise SystemExit(main())
