from decimal import Decimal

from flowcore.config import InstrumentConfig, StrategyConfig
from flowcore.data import MarketEvent
from flowcore.engine import ReplayEngine
from flowcore.models import AggressorSide, BookSnapshot, Trade
from flowcore.signals import SignalSide, SignalType
from examples.multi_symbol_demo import INSTRUMENTS, build_bid_wall_events


def snapshot(timestamp_ms: int, bid_wall: Decimal, ask_wall: Decimal = Decimal("100")) -> BookSnapshot:
    return BookSnapshot.from_dicts(
        timestamp_ms,
        bids=[
            (Decimal("99.99"), bid_wall),
            (Decimal("99.98"), Decimal("80")),
            (Decimal("99.97"), Decimal("70")),
            (Decimal("99.96"), Decimal("60")),
        ],
        asks=[
            (Decimal("100.00"), ask_wall),
            (Decimal("100.01"), Decimal("90")),
            (Decimal("100.02"), Decimal("90")),
            (Decimal("100.03"), Decimal("90")),
        ],
    )


def instrument() -> InstrumentConfig:
    return InstrumentConfig(symbol="SBER", tick_size=Decimal("0.01"), lot_size=10)


def config() -> StrategyConfig:
    return StrategyConfig(
        wall_ratio=Decimal("3"),
        wall_vs_local_avg=Decimal("2"),
        max_wall_distance_ticks=3,
        min_wall_lifetime_ms=300,
        hold_window_ms=600,
        min_trade_count_on_touch=2,
        min_executed_fraction_for_hold=Decimal("0.05"),
    )


def test_bid_wall_hold_produces_long_signal() -> None:
    events = [
        MarketEvent(0, snapshot=snapshot(0, Decimal("600"))),
        MarketEvent(100, snapshot=snapshot(100, Decimal("600"))),
        MarketEvent(200, trade=Trade(200, Decimal("99.99"), Decimal("20"), AggressorSide.SELL)),
        MarketEvent(300, trade=Trade(300, Decimal("99.99"), Decimal("20"), AggressorSide.SELL)),
        MarketEvent(900, snapshot=snapshot(900, Decimal("580"))),
    ]

    signals = ReplayEngine(instrument(), config()).run(events)

    assert len(signals) == 1
    assert signals[0].type == SignalType.WALL_HELD
    assert signals[0].side == SignalSide.LONG
    assert signals[0].entry_price == Decimal("99.99")


def test_streaming_process_matches_batch_run() -> None:
    events = [
        MarketEvent(0, snapshot=snapshot(0, Decimal("600"))),
        MarketEvent(100, snapshot=snapshot(100, Decimal("600"))),
        MarketEvent(200, trade=Trade(200, Decimal("99.99"), Decimal("20"), AggressorSide.SELL)),
        MarketEvent(300, trade=Trade(300, Decimal("99.99"), Decimal("20"), AggressorSide.SELL)),
        MarketEvent(900, snapshot=snapshot(900, Decimal("580"))),
    ]
    batch_signals = ReplayEngine(instrument(), config()).run(events)

    live_engine = ReplayEngine(instrument(), config())
    live_signals = []
    for event in events:
        live_signals.extend(live_engine.process(event))

    assert live_signals == list(batch_signals)


def test_bid_wall_removed_produces_short_signal() -> None:
    broken = BookSnapshot.from_dicts(
        500,
        bids=[
            (Decimal("99.98"), Decimal("90")),
            (Decimal("99.97"), Decimal("70")),
        ],
        asks=[
            (Decimal("99.99"), Decimal("100")),
            (Decimal("100.00"), Decimal("100")),
        ],
    )
    events = [
        MarketEvent(0, snapshot=snapshot(0, Decimal("600"))),
        MarketEvent(100, snapshot=snapshot(100, Decimal("600"))),
        MarketEvent(200, trade=Trade(200, Decimal("99.99"), Decimal("5"), AggressorSide.SELL)),
        MarketEvent(500, snapshot=broken),
    ]

    signals = ReplayEngine(instrument(), config()).run(events)

    assert len(signals) == 1
    assert signals[0].type == SignalType.WALL_REMOVED
    assert signals[0].side == SignalSide.SHORT


def test_bid_wall_hold_works_across_moex_like_tick_sizes() -> None:
    for spec in INSTRUMENTS:
        current_instrument = InstrumentConfig(spec.symbol, spec.tick_size, spec.lot_size)
        signals = ReplayEngine(current_instrument, StrategyConfig()).run(build_bid_wall_events(spec))

        assert len(signals) == 1
        assert signals[0].type == SignalType.WALL_HELD
        assert signals[0].side == SignalSide.LONG
