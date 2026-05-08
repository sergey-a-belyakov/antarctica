from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from .config import InstrumentConfig, StrategyConfig
from .models import BookSide, BookSnapshot, WallState


class SignalType(str, Enum):
    WALL_HELD = "wall_held"
    WALL_REMOVED = "wall_removed"


class SignalSide(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True)
class Signal:
    timestamp_ms: int
    symbol: str
    type: SignalType
    side: SignalSide
    wall_id: int
    wall_side: BookSide
    entry_price: Decimal
    stop_price: Decimal
    take_profit_price: Decimal
    reason: str


class SignalGenerator:
    def __init__(self, instrument: InstrumentConfig, config: StrategyConfig):
        self.instrument = instrument
        self.config = config
        self._emitted: set[tuple[int, SignalType]] = set()

    def evaluate(
        self,
        snapshot: BookSnapshot,
        active_walls: tuple[WallState, ...],
        inactive_walls: tuple[WallState, ...],
    ) -> tuple[Signal, ...]:
        signals: list[Signal] = []
        for wall in active_walls:
            signal = self._held_signal(snapshot, wall)
            if signal is not None:
                signals.append(signal)
        for wall in inactive_walls:
            signal = self._removed_signal(snapshot, wall)
            if signal is not None:
                signals.append(signal)
        return tuple(signals)

    def _held_signal(self, snapshot: BookSnapshot, wall: WallState) -> Signal | None:
        key = (wall.id, SignalType.WALL_HELD)
        if key in self._emitted or wall.touch_ms is None:
            return None
        if wall.age_ms < self.config.min_wall_lifetime_ms:
            return None
        if snapshot.timestamp_ms - wall.touch_ms < self.config.hold_window_ms:
            return None
        if wall.trades_on_touch < self.config.min_trade_count_on_touch:
            return None
        if wall.executed_fraction < self.config.min_executed_fraction_for_hold:
            return None
        if wall.removed_fraction > self.config.max_removed_fraction_for_hold:
            return None

        side = SignalSide.LONG if wall.side == BookSide.BID else SignalSide.SHORT
        self._emitted.add(key)
        return self._build_signal(snapshot.timestamp_ms, SignalType.WALL_HELD, side, wall, "wall absorbed aggressive flow")

    def _removed_signal(self, snapshot: BookSnapshot, wall: WallState) -> Signal | None:
        key = (wall.id, SignalType.WALL_REMOVED)
        if key in self._emitted:
            return None
        if wall.touch_ms is None:
            return None
        if wall.age_ms < self.config.min_wall_lifetime_ms:
            return None
        if wall.removed_fraction < self.config.min_removed_fraction_for_spoof:
            return None
        if snapshot.timestamp_ms - wall.last_seen_ms > self.config.removal_window_ms:
            return None

        if wall.side == BookSide.BID:
            if snapshot.best_bid is None or snapshot.best_bid >= wall.price:
                return None
            side = SignalSide.SHORT
        else:
            if snapshot.best_ask is None or snapshot.best_ask <= wall.price:
                return None
            side = SignalSide.LONG

        self._emitted.add(key)
        return self._build_signal(snapshot.timestamp_ms, SignalType.WALL_REMOVED, side, wall, "wall vanished and price broke through")

    def _build_signal(
        self,
        timestamp_ms: int,
        signal_type: SignalType,
        side: SignalSide,
        wall: WallState,
        reason: str,
    ) -> Signal:
        risk = self.instrument.tick_size * Decimal(self.config.stop_ticks)
        reward = risk * self.config.take_profit_r_multiple
        if side == SignalSide.LONG:
            stop = wall.price - risk
            take_profit = wall.price + reward
        else:
            stop = wall.price + risk
            take_profit = wall.price - reward
        return Signal(
            timestamp_ms=timestamp_ms,
            symbol=self.instrument.symbol,
            type=signal_type,
            side=side,
            wall_id=wall.id,
            wall_side=wall.side,
            entry_price=wall.price,
            stop_price=stop,
            take_profit_price=take_profit,
            reason=reason,
        )
