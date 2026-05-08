from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Iterable


class BookSide(str, Enum):
    BID = "bid"
    ASK = "ask"

    @property
    def opposite(self) -> "BookSide":
        return BookSide.ASK if self == BookSide.BID else BookSide.BID


class AggressorSide(str, Enum):
    BUY = "buy"
    SELL = "sell"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class BookLevel:
    price: Decimal
    size: Decimal


@dataclass(frozen=True)
class Trade:
    timestamp_ms: int
    price: Decimal
    size: Decimal
    aggressor: AggressorSide


@dataclass(frozen=True)
class BookSnapshot:
    timestamp_ms: int
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]

    @property
    def best_bid(self) -> Decimal | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Decimal | None:
        return self.asks[0].price if self.asks else None

    @property
    def mid_price(self) -> Decimal | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / Decimal("2")

    def side_levels(self, side: BookSide) -> tuple[BookLevel, ...]:
        return self.bids if side == BookSide.BID else self.asks

    def size_at(self, side: BookSide, price: Decimal) -> Decimal:
        for level in self.side_levels(side):
            if level.price == price:
                return level.size
        return Decimal("0")

    @staticmethod
    def from_dicts(
        timestamp_ms: int,
        bids: Iterable[tuple[Decimal, Decimal]],
        asks: Iterable[tuple[Decimal, Decimal]],
    ) -> "BookSnapshot":
        bid_levels = tuple(BookLevel(price, size) for price, size in sorted(bids, reverse=True))
        ask_levels = tuple(BookLevel(price, size) for price, size in sorted(asks))
        return BookSnapshot(timestamp_ms=timestamp_ms, bids=bid_levels, asks=ask_levels)


@dataclass
class WallState:
    id: int
    side: BookSide
    price: Decimal
    first_seen_ms: int
    last_seen_ms: int
    initial_size: Decimal
    peak_size: Decimal
    current_size: Decimal
    executed_size: Decimal = Decimal("0")
    removed_size: Decimal = Decimal("0")
    touch_ms: int | None = None
    trades_on_touch: int = 0
    active: bool = True
    metadata: dict[str, Decimal] = field(default_factory=dict)

    @property
    def age_ms(self) -> int:
        return self.last_seen_ms - self.first_seen_ms

    @property
    def removed_fraction(self) -> Decimal:
        if self.peak_size <= 0:
            return Decimal("0")
        return self.removed_size / self.peak_size

    @property
    def executed_fraction(self) -> Decimal:
        if self.peak_size <= 0:
            return Decimal("0")
        return self.executed_size / self.peak_size
