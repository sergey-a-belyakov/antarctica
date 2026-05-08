import json
from decimal import Decimal

from antarctica.data import event_from_json_row, load_events_jsonl
from antarctica.models import AggressorSide


def test_event_from_json_row_parses_book() -> None:
    event = event_from_json_row(
        {
            "kind": "book",
            "timestamp_ms": 100,
            "bids": [{"price": "99.99", "size": "600"}],
            "asks": [{"price": "100.00", "size": "100"}],
        }
    )

    assert event.snapshot is not None
    assert event.snapshot.best_bid == Decimal("99.99")
    assert event.snapshot.best_ask == Decimal("100.00")


def test_event_from_json_row_parses_trade() -> None:
    event = event_from_json_row(
        {
            "kind": "trade",
            "timestamp_ms": 200,
            "price": "99.99",
            "size": "20",
            "aggressor": "sell",
        }
    )

    assert event.trade is not None
    assert event.trade.price == Decimal("99.99")
    assert event.trade.aggressor == AggressorSide.SELL


def test_load_events_jsonl_skips_blank_lines(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    rows = [
        {
            "kind": "book",
            "timestamp_ms": 100,
            "bids": [{"price": "99.99", "size": "600"}],
            "asks": [{"price": "100.00", "size": "100"}],
        },
        {
            "kind": "trade",
            "timestamp_ms": 200,
            "price": "99.99",
            "size": "20",
            "aggressor": "sell",
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n\n", encoding="utf-8")

    events = list(load_events_jsonl(path))

    assert len(events) == 2
    assert events[0].snapshot is not None
    assert events[1].trade is not None
