from __future__ import annotations

from decimal import Decimal

from .config import InstrumentConfig, StrategyConfig
from .models import AggressorSide, BookSide, BookSnapshot, Trade, WallState


class WallDetector:
    def __init__(self, instrument: InstrumentConfig, config: StrategyConfig):
        self.instrument = instrument
        self.config = config
        self._next_id = 1
        self._walls: dict[tuple[BookSide, Decimal], WallState] = {}

    @property
    def active_walls(self) -> tuple[WallState, ...]:
        return tuple(wall for wall in self._walls.values() if wall.active)

    def on_snapshot(self, snapshot: BookSnapshot) -> tuple[WallState, ...]:
        candidates = self._find_candidates(snapshot)
        seen_keys = set(candidates)

        for key, size in candidates.items():
            side, price = key
            wall = self._walls.get(key)
            if wall is None or not wall.active:
                self._walls[key] = WallState(
                    id=self._next_id,
                    side=side,
                    price=price,
                    first_seen_ms=snapshot.timestamp_ms,
                    last_seen_ms=snapshot.timestamp_ms,
                    initial_size=size,
                    peak_size=size,
                    current_size=size,
                )
                self._next_id += 1
            else:
                if size > wall.peak_size:
                    wall.peak_size = size
                if size < wall.current_size:
                    wall.removed_size += wall.current_size - size
                wall.current_size = size
                wall.last_seen_ms = snapshot.timestamp_ms

        for key, wall in list(self._walls.items()):
            if not wall.active or key in seen_keys:
                continue
            current_size = snapshot.size_at(wall.side, wall.price)
            if current_size < wall.current_size:
                wall.removed_size += wall.current_size - current_size
            wall.current_size = current_size
            wall.last_seen_ms = snapshot.timestamp_ms
            if current_size <= 0:
                wall.active = False

        self._mark_touches(snapshot)
        return self.active_walls

    def on_trade(self, trade: Trade) -> None:
        for wall in self._walls.values():
            if not wall.active and wall.touch_ms is None:
                continue
            if wall.price != trade.price:
                continue
            if self._trade_hits_wall(wall, trade):
                wall.executed_size += trade.size
                if wall.touch_ms is not None:
                    wall.trades_on_touch += 1

    def recently_inactive(self, now_ms: int) -> tuple[WallState, ...]:
        horizon = self.config.removal_window_ms
        return tuple(
            wall
            for wall in self._walls.values()
            if not wall.active and now_ms - wall.last_seen_ms <= horizon
        )

    def _find_candidates(self, snapshot: BookSnapshot) -> dict[tuple[BookSide, Decimal], Decimal]:
        candidates: dict[tuple[BookSide, Decimal], Decimal] = {}
        for side in (BookSide.BID, BookSide.ASK):
            levels = snapshot.side_levels(side)[: self.config.levels_each_side]
            opposite_levels = snapshot.side_levels(side.opposite)[: self.config.levels_each_side]
            if not levels or snapshot.mid_price is None:
                continue
            local_avg = sum((level.size for level in levels), Decimal("0")) / Decimal(len(levels))
            for idx, level in enumerate(levels):
                if self.instrument.ticks_between(level.price, snapshot.mid_price) > self.config.max_wall_distance_ticks:
                    continue
                opposite_size = opposite_levels[idx].size if idx < len(opposite_levels) else Decimal("0")
                ratio_ok = opposite_size == 0 or level.size / opposite_size >= self.config.wall_ratio
                local_ok = local_avg == 0 or level.size / local_avg >= self.config.wall_vs_local_avg
                if ratio_ok and local_ok:
                    candidates[(side, level.price)] = level.size
        return candidates

    def _mark_touches(self, snapshot: BookSnapshot) -> None:
        for wall in self._walls.values():
            if not wall.active or wall.touch_ms is not None:
                continue
            reference = snapshot.best_bid if wall.side == BookSide.BID else snapshot.best_ask
            if reference is None:
                continue
            if self.instrument.ticks_between(reference, wall.price) <= self.config.touch_distance_ticks:
                wall.touch_ms = snapshot.timestamp_ms

    @staticmethod
    def _trade_hits_wall(wall: WallState, trade: Trade) -> bool:
        if wall.side == BookSide.BID:
            return trade.aggressor in (AggressorSide.SELL, AggressorSide.UNKNOWN)
        return trade.aggressor in (AggressorSide.BUY, AggressorSide.UNKNOWN)
