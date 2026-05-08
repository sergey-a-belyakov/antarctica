from __future__ import annotations

import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flowcore.config import InstrumentConfig, StrategyConfig
from flowcore.data import MarketEvent
from flowcore.engine import ReplayEngine
from flowcore.models import AggressorSide, BookSnapshot, Trade


@dataclass(frozen=True)
class DemoInstrument:
    symbol: str
    tick_size: Decimal
    lot_size: int
    base_price: Decimal


INSTRUMENTS = (
    DemoInstrument("SBER", Decimal("0.01"), 10, Decimal("300.00")),
    DemoInstrument("GAZP", Decimal("0.01"), 10, Decimal("170.00")),
    DemoInstrument("LKOH", Decimal("0.5"), 1, Decimal("7600.0")),
    DemoInstrument("VTBR", Decimal("0.000005"), 10000, Decimal("0.090000")),
)


def build_bid_wall_events(spec: DemoInstrument) -> list[MarketEvent]:
    wall_price = spec.base_price - spec.tick_size
    ask_price = spec.base_price
    events = [
        MarketEvent(0, snapshot=build_snapshot(0, spec, wall_size=Decimal("600"))),
        MarketEvent(100, snapshot=build_snapshot(100, spec, wall_size=Decimal("600"))),
        MarketEvent(
            200,
            trade=Trade(200, wall_price, Decimal("20"), AggressorSide.SELL),
        ),
        MarketEvent(
            300,
            trade=Trade(300, wall_price, Decimal("20"), AggressorSide.SELL),
        ),
        MarketEvent(
            400,
            trade=Trade(400, wall_price, Decimal("20"), AggressorSide.SELL),
        ),
        MarketEvent(3000, snapshot=build_snapshot(3000, spec, wall_size=Decimal("580"))),
    ]
    assert ask_price > wall_price
    return events


def build_snapshot(timestamp_ms: int, spec: DemoInstrument, wall_size: Decimal) -> BookSnapshot:
    tick = spec.tick_size
    base = spec.base_price
    return BookSnapshot.from_dicts(
        timestamp_ms,
        bids=[
            (base - tick, wall_size),
            (base - tick * 2, Decimal("80")),
            (base - tick * 3, Decimal("70")),
            (base - tick * 4, Decimal("60")),
        ],
        asks=[
            (base, Decimal("100")),
            (base + tick, Decimal("90")),
            (base + tick * 2, Decimal("90")),
            (base + tick * 3, Decimal("90")),
        ],
    )


def main() -> int:
    config = StrategyConfig()
    for spec in INSTRUMENTS:
        instrument = InstrumentConfig(spec.symbol, spec.tick_size, spec.lot_size)
        signals = ReplayEngine(instrument, config).run(build_bid_wall_events(spec))
        if not signals:
            print(f"{spec.symbol}: no signal")
            continue
        signal = signals[0]
        print(
            f"{spec.symbol}: {signal.type.value} {signal.side.value} "
            f"entry={signal.entry_price} stop={signal.stop_price} tp={signal.take_profit_price}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
