from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from decimal import Decimal

from .cli import encode, event_to_dict, signal_to_dict
from .config import StrategyConfig
from .data import MarketEvent
from .engine import ReplayEngine
from .moex import MoexIssAccessError, MoexIssClient, MoexIssError
from .models import AggressorSide, Trade


def main() -> int:
    parser = argparse.ArgumentParser(description="Run continuous Antarctica signal monitoring.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--engine", default="stock")
    parser.add_argument("--market", default="shares")
    parser.add_argument("--board", default="TQBR")
    parser.add_argument("--interval-sec", default=1.0, type=float)
    parser.add_argument("--trades-limit", default=50, type=int)
    parser.add_argument("--top-of-book", action="store_true")
    parser.add_argument("--dump-events", action="store_true")
    parser.add_argument("--status-every", default=10, type=int)
    parser.add_argument("--max-polls", type=int, help="Stop after N polls. Useful for tests and smoke checks.")
    parser.add_argument("--wall-ratio", default=Decimal("3"), type=Decimal)
    args = parser.parse_args()

    client = MoexIssClient()
    try:
        info = client.security_info(args.symbol, args.engine, args.market, args.board)
    except MoexIssError as exc:
        parser.error(str(exc))

    engine = ReplayEngine(info.instrument, StrategyConfig(wall_ratio=args.wall_ratio))
    seen_trades: set[tuple[int, Decimal, Decimal, AggressorSide]] = set()
    print(
        json.dumps(
            {
                "kind": "status",
                "message": "started",
                "symbol": info.instrument.symbol,
                "board": info.board,
                "tick_size": info.instrument.tick_size,
                "lot_size": info.instrument.lot_size,
                "top_of_book": args.top_of_book,
            },
            ensure_ascii=False,
            default=encode,
        ),
        flush=True,
    )

    poll = 0
    try:
        while args.max_polls is None or poll < args.max_polls:
            poll += 1
            try:
                events = fetch_once(client, args, seen_trades)
            except MoexIssAccessError as exc:
                parser.error(f"{exc} Restart with --top-of-book for public best bid/offer data.")
            except MoexIssError as exc:
                print(json.dumps({"kind": "error", "message": str(exc)}, ensure_ascii=False), flush=True)
                time.sleep(args.interval_sec)
                continue

            signal_count = 0
            for event in events:
                if args.dump_events:
                    print(json.dumps(event_to_dict(event), ensure_ascii=False, default=encode), flush=True)
                for signal in engine.process(event):
                    signal_count += 1
                    payload = signal_to_dict(signal)
                    payload["kind"] = "signal"
                    print(json.dumps(payload, ensure_ascii=False, default=encode), flush=True)

            if args.status_every > 0 and poll % args.status_every == 0:
                print(
                    json.dumps(
                        {
                            "kind": "status",
                            "message": "running",
                            "poll": poll,
                            "events": len(events),
                            "signals": signal_count,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            time.sleep(args.interval_sec)
    except KeyboardInterrupt:
        print(json.dumps({"kind": "status", "message": "stopped", "poll": poll}, ensure_ascii=False), flush=True)
    return 0


def fetch_once(
    client: MoexIssClient,
    args: argparse.Namespace,
    seen_trades: set[tuple[int, Decimal, Decimal, AggressorSide]],
) -> tuple[MarketEvent, ...]:
    snapshot = (
        client.top_of_book_snapshot(args.symbol, args.engine, args.market, args.board)
        if args.top_of_book
        else client.orderbook_snapshot(args.symbol, args.engine, args.market, args.board)
    )
    events = [MarketEvent(snapshot.timestamp_ms, snapshot=snapshot)]
    for trade in client.trades(args.symbol, args.engine, args.market, args.board, args.trades_limit):
        key = trade_key(trade)
        if key in seen_trades:
            continue
        seen_trades.add(key)
        events.append(MarketEvent(trade.timestamp_ms, trade=trade))
    return tuple(sorted(events, key=lambda item: item.timestamp_ms))


def trade_key(trade: Trade) -> tuple[int, Decimal, Decimal, AggressorSide]:
    return (trade.timestamp_ms, trade.price, trade.size, trade.aggressor)


if __name__ == "__main__":
    raise SystemExit(main())
