from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class InstrumentConfig:
    """Trading parameters for one MOEX instrument."""

    symbol: str
    tick_size: Decimal
    lot_size: int = 1
    commission_rate: Decimal = Decimal("0.00005")

    def ticks_between(self, a: Decimal, b: Decimal) -> int:
        return int(abs(a - b) / self.tick_size)


@dataclass(frozen=True)
class StrategyConfig:
    """Rule thresholds for the first Antarctica MVP."""

    levels_each_side: int = 10
    wall_ratio: Decimal = Decimal("3")
    wall_vs_local_avg: Decimal = Decimal("2")
    max_wall_distance_ticks: int = 8
    min_wall_lifetime_ms: int = 500
    touch_distance_ticks: int = 1
    hold_window_ms: int = 2500
    removal_window_ms: int = 700
    min_trade_count_on_touch: int = 3
    min_executed_fraction_for_hold: Decimal = Decimal("0.08")
    max_removed_fraction_for_hold: Decimal = Decimal("0.35")
    min_removed_fraction_for_spoof: Decimal = Decimal("0.70")
    stop_ticks: int = 2
    take_profit_r_multiple: Decimal = Decimal("1.5")
    timeout_ms: int = 5000
