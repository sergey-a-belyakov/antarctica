from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import TextIO

from .cli import encode, event_to_dict
from .live import fetch_once
from .moex import MoexIssAccessError, MoexIssClient, MoexIssError
from .models import AggressorSide


@dataclass(frozen=True)
class RecorderStats:
    polls: int = 0
    events: int = 0
    errors: int = 0


class JsonlRecorder:
    def __init__(self, output_dir: str | Path, symbol: str, board: str):
        self.output_dir = Path(output_dir)
        self.symbol = symbol.upper()
        self.board = board.upper()
        self._current_date: str | None = None
        self._handle: TextIO | None = None
        self.current_path: Path | None = None

    def write(self, payload: dict[str, object], timestamp_ms: int) -> Path:
        handle = self._open_for_timestamp(timestamp_ms)
        handle.write(json.dumps(payload, ensure_ascii=False, default=encode))
        handle.write("\n")
        handle.flush()
        return self.current_path or self.output_dir

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
            self._current_date = None

    def _open_for_timestamp(self, timestamp_ms: int) -> TextIO:
        date_key = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        if self._handle is not None and self._current_date == date_key:
            return self._handle

        self.close()
        directory = self.output_dir / self.symbol / self.board
        directory.mkdir(parents=True, exist_ok=True)
        self.current_path = directory / f"{date_key}.jsonl"
        self._handle = self.current_path.open("a", encoding="utf-8")
        self._current_date = date_key
        return self._handle

    def __enter__(self) -> "JsonlRecorder":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Record MOEX book/trade events to JSONL.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--engine", default="stock")
    parser.add_argument("--market", default="shares")
    parser.add_argument("--board", default="TQBR")
    parser.add_argument("--output-dir", default="data/raw")
    parser.add_argument("--interval-sec", default=1.0, type=float)
    parser.add_argument("--trades-limit", default=50, type=int)
    parser.add_argument("--top-of-book", action="store_true")
    parser.add_argument("--status-every", default=10, type=int)
    parser.add_argument("--max-polls", type=int, help="Stop after N polls. Useful for smoke checks.")
    args = parser.parse_args()

    client = MoexIssClient()
    try:
        info = client.security_info(args.symbol, args.engine, args.market, args.board)
    except MoexIssError as exc:
        parser.error(str(exc))

    seen_trades: set[tuple[int, Decimal, Decimal, AggressorSide]] = set()
    seen_books: set[tuple[object, ...]] = set()
    stats = RecorderStats()
    print(
        json.dumps(
            {
                "kind": "status",
                "message": "recorder_started",
                "symbol": info.instrument.symbol,
                "board": info.board,
                "tick_size": info.instrument.tick_size,
                "lot_size": info.instrument.lot_size,
                "top_of_book": args.top_of_book,
                "output_dir": args.output_dir,
            },
            ensure_ascii=False,
            default=encode,
        ),
        flush=True,
    )

    with JsonlRecorder(args.output_dir, info.instrument.symbol, info.board) as recorder:
        try:
            while args.max_polls is None or stats.polls < args.max_polls:
                try:
                    events = fetch_once(client, args, seen_trades, seen_books)
                except MoexIssAccessError as exc:
                    parser.error(f"{exc} Restart with --top-of-book for public best bid/offer data.")
                except MoexIssError as exc:
                    stats = RecorderStats(stats.polls + 1, stats.events, stats.errors + 1)
                    print(json.dumps({"kind": "error", "message": str(exc)}, ensure_ascii=False), flush=True)
                    time.sleep(args.interval_sec)
                    continue

                for event in events:
                    payload = event_to_dict(event)
                    payload["symbol"] = info.instrument.symbol
                    payload["board"] = info.board
                    payload["source"] = "moex_iss_top_of_book" if args.top_of_book else "moex_iss_orderbook"
                    path = recorder.write(payload, event.timestamp_ms)
                    stats = RecorderStats(stats.polls, stats.events + 1, stats.errors)

                stats = RecorderStats(stats.polls + 1, stats.events, stats.errors)
                if args.status_every > 0 and stats.polls % args.status_every == 0:
                    print(
                        json.dumps(
                            {
                                "kind": "status",
                                "message": "recording",
                                "polls": stats.polls,
                                "events": stats.events,
                                "errors": stats.errors,
                                "path": str(path) if events else str(recorder.current_path or args.output_dir),
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
                        "message": "recorder_stopped",
                        "polls": stats.polls,
                        "events": stats.events,
                        "errors": stats.errors,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
