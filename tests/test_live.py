from decimal import Decimal
from types import SimpleNamespace

from flowcore.live import book_key, fetch_once, trade_key
from flowcore.models import AggressorSide, BookSnapshot, Trade


class FakeClient:
    def top_of_book_snapshot(self, symbol, engine, market, board):
        return BookSnapshot.from_dicts(
            100,
            bids=[(Decimal("99.99"), Decimal("10"))],
            asks=[(Decimal("100.00"), Decimal("12"))],
        )

    def orderbook_snapshot(self, symbol, engine, market, board):
        raise AssertionError("top_of_book should be used")

    def trades(self, symbol, engine, market, board, limit):
        return (
            Trade(90, Decimal("99.99"), Decimal("1"), AggressorSide.SELL),
            Trade(90, Decimal("99.99"), Decimal("1"), AggressorSide.SELL),
        )


def test_trade_key_contains_fields_needed_for_deduplication() -> None:
    trade = Trade(1, Decimal("10.1"), Decimal("2"), AggressorSide.BUY)

    assert trade_key(trade) == (1, Decimal("10.1"), Decimal("2"), AggressorSide.BUY)


def test_fetch_once_deduplicates_seen_trades() -> None:
    args = SimpleNamespace(
        symbol="SBER",
        engine="stock",
        market="shares",
        board="TQBR",
        top_of_book=True,
        trades_limit=50,
    )
    seen = set()

    first = fetch_once(FakeClient(), args, seen)
    second = fetch_once(FakeClient(), args, seen)

    assert len(first) == 2
    assert first[0].trade is not None
    assert first[1].snapshot is not None
    assert len(second) == 1
    assert second[0].snapshot is not None


def test_fetch_once_deduplicates_seen_books() -> None:
    args = SimpleNamespace(
        symbol="SBER",
        engine="stock",
        market="shares",
        board="TQBR",
        top_of_book=True,
        trades_limit=50,
    )
    seen_trades = set()
    seen_books = set()

    first = fetch_once(FakeClient(), args, seen_trades, seen_books)
    second = fetch_once(FakeClient(), args, seen_trades, seen_books)

    assert len(first) == 2
    assert first[1].snapshot is not None
    assert second == ()


def test_book_key_contains_timestamp_and_levels() -> None:
    snapshot = BookSnapshot.from_dicts(
        100,
        bids=[(Decimal("99.99"), Decimal("10"))],
        asks=[(Decimal("100.00"), Decimal("12"))],
    )

    assert book_key(snapshot) == (
        100,
        ((Decimal("99.99"), Decimal("10")),),
        ((Decimal("100.00"), Decimal("12")),),
    )
