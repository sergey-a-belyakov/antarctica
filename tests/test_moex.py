from decimal import Decimal

from flowcore.moex import _table_rows, MoexIssClient
from flowcore.models import AggressorSide


def test_table_rows_maps_moex_columns_to_dicts() -> None:
    payload = {"trades": {"columns": ["PRICE", "QUANTITY"], "data": [[318.79, 2]]}}

    assert _table_rows(payload, "trades") == [{"PRICE": 318.79, "QUANTITY": 2}]


def test_security_info_parses_tick_and_lot(monkeypatch) -> None:
    client = MoexIssClient()
    payload = {
        "securities": {
            "columns": ["SECID", "BOARDID", "SHORTNAME", "LOTSIZE", "DECIMALS", "MINSTEP"],
            "data": [["SBER", "TQBR", "Сбербанк", 1, 2, 0.01]],
        },
        "marketdata": {"columns": ["TRADINGSTATUS"], "data": [["T"]]},
    }
    monkeypatch.setattr(client, "_get_json", lambda path, params: payload)

    info = client.security_info("SBER")

    assert info.instrument.symbol == "SBER"
    assert info.instrument.tick_size == Decimal("0.01")
    assert info.instrument.lot_size == 1
    assert info.trading_status == "T"


def test_top_of_book_snapshot_parses_public_marketdata(monkeypatch) -> None:
    client = MoexIssClient()
    payload = {
        "marketdata": {
            "columns": ["BID", "BIDDEPTHT", "OFFER", "OFFERDEPTHT", "SYSTIME"],
            "data": [[319.14, 2767759, 319.15, 3807736, "2026-05-08 10:40:18"]],
        }
    }
    monkeypatch.setattr(client, "_get_json", lambda path, params: payload)

    snapshot = client.top_of_book_snapshot("SBER")

    assert snapshot.best_bid == Decimal("319.14")
    assert snapshot.best_ask == Decimal("319.15")
    assert snapshot.bids[0].size == Decimal("2767759")


def test_trades_parse_buysell_to_aggressor(monkeypatch) -> None:
    client = MoexIssClient()
    payload = {
        "trades": {
            "columns": ["PRICE", "QUANTITY", "BUYSELL", "SYSTIME"],
            "data": [[318.79, 2, "B", "2026-05-08 06:59:56"]],
        }
    }
    monkeypatch.setattr(client, "_get_json", lambda path, params: payload)

    trades = client.trades("SBER")

    assert trades[0].price == Decimal("318.79")
    assert trades[0].size == Decimal("2")
    assert trades[0].aggressor == AggressorSide.BUY
