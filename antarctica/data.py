from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterator

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
