from __future__ import annotations

from .config import InstrumentConfig, StrategyConfig
from .data import MarketEvent
from .detector import WallDetector
from .models import BookSnapshot
from .signals import Signal, SignalGenerator


class ReplayEngine:
    def __init__(self, instrument: InstrumentConfig, config: StrategyConfig | None = None):
        self.instrument = instrument
        self.config = config or StrategyConfig()
        self.detector = WallDetector(instrument, self.config)
        self.signals = SignalGenerator(instrument, self.config)
        self._last_snapshot: BookSnapshot | None = None

    def run(self, events: list[MarketEvent] | tuple[MarketEvent, ...]) -> tuple[Signal, ...]:
        emitted: list[Signal] = []
        for event in sorted(events, key=lambda item: item.timestamp_ms):
            emitted.extend(self.process(event))
        return tuple(emitted)

    def process(self, event: MarketEvent) -> tuple[Signal, ...]:
        if event.snapshot is not None:
            self._last_snapshot = event.snapshot
            active = self.detector.on_snapshot(event.snapshot)
            inactive = self.detector.recently_inactive(event.timestamp_ms)
            return self.signals.evaluate(event.snapshot, active, inactive)
        if event.trade is not None:
            self.detector.on_trade(event.trade)
            if self._last_snapshot is not None:
                active = self.detector.active_walls
                inactive = self.detector.recently_inactive(event.timestamp_ms)
                return self.signals.evaluate(self._last_snapshot, active, inactive)
        return ()
