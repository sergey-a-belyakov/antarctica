from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

from .models import AggressorSide, BookSnapshot, Trade


@dataclass(frozen=True)
class MarketEvent:
    timestamp_ms: int
    snapshot: BookSnapshot | None = None
    trade: Trade | None = None

    @property
    def kind(self) -> str:
        return "book" if self.snapshot is not None else "trade"


def parse_decimal(value: str) -> Decimal:
    return Decimal(value.strip().replace(",", "."))


def load_book_csv(path: str | Path) -> Iterator[BookSnapshot]:
    """Load snapshots from a wide CSV: ts,bid_px_1,bid_sz_1,ask_px_1,ask_sz_1..."""

    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            timestamp_ms = int(row["timestamp_ms"])
            bids: list[tuple[Decimal, Decimal]] = []
            asks: list[tuple[Decimal, Decimal]] = []
            level = 1
            while f"bid_px_{level}" in row:
                bid_px = row.get(f"bid_px_{level}", "")
                bid_sz = row.get(f"bid_sz_{level}", "")
                ask_px = row.get(f"ask_px_{level}", "")
                ask_sz = row.get(f"ask_sz_{level}", "")
                if bid_px and bid_sz:
                    bids.append((parse_decimal(bid_px), parse_decimal(bid_sz)))
                if ask_px and ask_sz:
                    asks.append((parse_decimal(ask_px), parse_decimal(ask_sz)))
                level += 1
            yield BookSnapshot.from_dicts(timestamp_ms, bids, asks)


def load_trades_csv(path: str | Path) -> Iterator[Trade]:
    """Load trades from CSV: timestamp_ms,price,size,aggressor."""

    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield Trade(
                timestamp_ms=int(row["timestamp_ms"]),
                price=parse_decimal(row["price"]),
                size=parse_decimal(row["size"]),
                aggressor=AggressorSide(row.get("aggressor", "unknown").strip().lower()),
            )


def load_events_jsonl(path: str | Path) -> Iterator[MarketEvent]:
    """Load recorder JSONL rows into replayable market events."""

    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSONL row") from exc
            yield event_from_json_row(row, path, line_number)


def event_from_json_row(row: dict[str, Any], path: str | Path = "<memory>", line_number: int = 0) -> MarketEvent:
    kind = row.get("kind")
    timestamp_ms = int(row["timestamp_ms"])
    if kind == "book":
        bids = [_price_size(level) for level in row.get("bids", [])]
        asks = [_price_size(level) for level in row.get("asks", [])]
        snapshot = BookSnapshot.from_dicts(timestamp_ms, bids, asks)
        return MarketEvent(timestamp_ms=timestamp_ms, snapshot=snapshot)
    if kind == "trade":
        trade = Trade(
            timestamp_ms=timestamp_ms,
            price=parse_decimal(str(row["price"])),
            size=parse_decimal(str(row["size"])),
            aggressor=AggressorSide(str(row.get("aggressor", "unknown")).lower()),
        )
        return MarketEvent(timestamp_ms=timestamp_ms, trade=trade)
    location = f"{path}:{line_number}" if line_number else str(path)
    raise ValueError(f"{location}: unsupported event kind {kind!r}")


def _price_size(level: dict[str, Any]) -> tuple[Decimal, Decimal]:
    return parse_decimal(str(level["price"])), parse_decimal(str(level["size"]))


def merge_events(
    snapshots: Iterator[BookSnapshot],
    trades: Iterator[Trade],
) -> Iterator[MarketEvent]:
    book_iter = iter(snapshots)
    trade_iter = iter(trades)
    next_book = next(book_iter, None)
    next_trade = next(trade_iter, None)

    while next_book is not None or next_trade is not None:
        if next_trade is None or (
            next_book is not None and next_book.timestamp_ms <= next_trade.timestamp_ms
        ):
            yield MarketEvent(timestamp_ms=next_book.timestamp_ms, snapshot=next_book)
            next_book = next(book_iter, None)
        else:
            yield MarketEvent(timestamp_ms=next_trade.timestamp_ms, trade=next_trade)
            next_trade = next(trade_iter, None)
