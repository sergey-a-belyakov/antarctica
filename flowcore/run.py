from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from decimal import Decimal

from .cli import encode, event_to_dict, signal_to_dict
from .config import StrategyConfig
from .engine import ReplayEngine
from .live import fetch_once
from .moex import MoexIssAccessError, MoexIssClient, MoexIssError
from .models import AggressorSide
from .recorder import JsonlRecorder


@dataclass(frozen=True)
class RunStats:
    polls: int = 0
    events: int = 0
    signals: int = 0
    errors: int = 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live market pipeline: fetch, record, detect, write signals.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--engine", default="stock")
    parser.add_argument("--market", default="shares")
    parser.add_argument("--board", default="TQBR")
    parser.add_argument("--interval-sec", default=1.0, type=float)
    parser.add_argument("--trades-limit", default=50, type=int)
    parser.add_argument("--top-of-book", action="store_true")
    parser.add_argument("--dump-events", action="store_true")
    parser.add_argument("--record-raw", action="store_true")
    parser.add_argument("--record-signals", action="store_true")
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--signals-dir", default="data/signals")
    parser.add_argument("--status-every", default=10, type=int)
    parser.add_argument("--max-polls", type=int, help="Stop after N polls. Useful for smoke checks.")
    parser.add_argument("--wall-ratio", default=Decimal("3"), type=Decimal)
    args = parser.parse_args()

    client = MoexIssClient()
    try:
        info = client.security_info(args.symbol, args.engine, args.market, args.board)
    except MoexIssError as exc:
        parser.error(str(exc))

    engine = ReplayEngine(info.instrument, StrategyConfig(wall_ratio=args.wall_ratio))
    seen_trades: set[tuple[int, Decimal, Decimal, AggressorSide]] = set()
    seen_books: set[tuple[object, ...]] = set()
    source = "moex_iss_top_of_book" if args.top_of_book else "moex_iss_orderbook"
    stats = RunStats()
    print(
        json.dumps(
            {
                "kind": "status",
                "message": "pipeline_started",
                "symbol": info.instrument.symbol,
                "board": info.board,
                "tick_size": info.instrument.tick_size,
                "lot_size": info.instrument.lot_size,
                "top_of_book": args.top_of_book,
                "record_raw": args.record_raw,
                "record_signals": args.record_signals,
                "raw_dir": args.raw_dir,
                "signals_dir": args.signals_dir,
            },
            ensure_ascii=False,
            default=encode,
        ),
        flush=True,
    )

    raw_recorder = JsonlRecorder(args.raw_dir, info.instrument.symbol, info.board) if args.record_raw else None
    signal_recorder = (
        JsonlRecorder(args.signals_dir, info.instrument.symbol, info.board) if args.record_signals else None
    )
    try:
        while args.max_polls is None or stats.polls < args.max_polls:
            try:
                events = fetch_once(client, args, seen_trades, seen_books)
            except MoexIssAccessError as exc:
                parser.error(f"{exc} Restart with --top-of-book for public best bid/offer data.")
            except MoexIssError as exc:
                stats = RunStats(stats.polls + 1, stats.events, stats.signals, stats.errors + 1)
                print(json.dumps({"kind": "error", "message": str(exc)}, ensure_ascii=False), flush=True)
                time.sleep(args.interval_sec)
                continue

            poll_signals = 0
            for event in events:
                event_payload = enrich_event(event_to_dict(event), info.instrument.symbol, info.board, source)
                if raw_recorder is not None:
                    raw_recorder.write(event_payload, event.timestamp_ms)
                if args.dump_events:
                    print(json.dumps(event_payload, ensure_ascii=False, default=encode), flush=True)

                for signal in engine.process(event):
                    poll_signals += 1
                    signal_payload = signal_to_dict(signal)
                    signal_payload["kind"] = "signal"
                    signal_payload["board"] = info.board
                    signal_payload["source"] = source
                    if signal_recorder is not None:
                        signal_recorder.write(signal_payload, signal.timestamp_ms)
                    print(json.dumps(signal_payload, ensure_ascii=False, default=encode), flush=True)

            stats = RunStats(
                polls=stats.polls + 1,
                events=stats.events + len(events),
                signals=stats.signals + poll_signals,
                errors=stats.errors,
            )
            if args.status_every > 0 and stats.polls % args.status_every == 0:
                print(
                    json.dumps(
                        {
                            "kind": "status",
                            "message": "pipeline_running",
                            "polls": stats.polls,
                            "events": stats.events,
                            "signals": stats.signals,
                            "errors": stats.errors,
                            "raw_path": str(raw_recorder.current_path) if raw_recorder is not None else None,
                            "signals_path": recorder_path(signal_recorder),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            time.sleep(args.interval_sec)
    except KeyboardInterrupt:
        print(
            json.dumps(
                {
                    "kind": "status",
                    "message": "pipeline_stopped",
                    "polls": stats.polls,
                    "events": stats.events,
                    "signals": stats.signals,
                    "errors": stats.errors,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    finally:
        if raw_recorder is not None:
            raw_recorder.close()
        if signal_recorder is not None:
            signal_recorder.close()
    return 0


def enrich_event(
    payload: dict[str, object],
    symbol: str,
    board: str,
    source: str,
) -> dict[str, object]:
    payload["symbol"] = symbol
    payload["board"] = board
    payload["source"] = source
    return payload


def recorder_path(recorder: JsonlRecorder | None) -> str | None:
    if recorder is None or recorder.current_path is None:
        return None
    return str(recorder.current_path)


if __name__ == "__main__":
    raise SystemExit(main())
