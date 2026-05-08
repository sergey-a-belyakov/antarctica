from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from .config import InstrumentConfig
from .data import MarketEvent
from .models import AggressorSide, BookSnapshot, Trade


class MoexIssError(RuntimeError):
    pass


class MoexIssAccessError(MoexIssError):
    pass


@dataclass(frozen=True)
class MoexSecurityInfo:
    instrument: InstrumentConfig
    board: str
    decimals: int
    short_name: str
    trading_status: str | None = None


class MoexIssClient:
    """Small MOEX ISS client for live/delayed public data.

    ISS orderbook endpoints may require market-data access and can return an
    HTML access page instead of JSON. The public securities endpoint still gives
    best bid/offer and anonymous trades, but best bid/offer is not Level II.
    """

    def __init__(
        self,
        base_url: str = "https://iss.moex.com/iss",
        timeout: float = 10.0,
        user_agent: str = "antarctica/0.1",
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.user_agent = user_agent

    def security_info(
        self,
        symbol: str,
        engine: str = "stock",
        market: str = "shares",
        board: str = "TQBR",
    ) -> MoexSecurityInfo:
        payload = self._get_json(
            f"/engines/{engine}/markets/{market}/boards/{board}/securities/{symbol}.json",
            {"iss.meta": "off"},
        )
        security = _first_row(payload, "securities")
        marketdata = _first_row(payload, "marketdata", required=False)
        if security is None:
            raise MoexIssError(f"MOEX ISS returned no security info for {symbol} on {board}")
        return MoexSecurityInfo(
            instrument=InstrumentConfig(
                symbol=symbol,
                tick_size=_decimal(security["MINSTEP"]),
                lot_size=int(security["LOTSIZE"]),
            ),
            board=str(security["BOARDID"]),
            decimals=int(security["DECIMALS"]),
            short_name=str(security["SHORTNAME"]),
            trading_status=None if marketdata is None else _optional_str(marketdata.get("TRADINGSTATUS")),
        )

    def top_of_book_snapshot(
        self,
        symbol: str,
        engine: str = "stock",
        market: str = "shares",
        board: str = "TQBR",
    ) -> BookSnapshot:
        payload = self._get_json(
            f"/engines/{engine}/markets/{market}/boards/{board}/securities/{symbol}.json",
            {"iss.meta": "off"},
        )
        row = _first_row(payload, "marketdata")
        bid_price = _optional_decimal(row.get("BID"))
        ask_price = _optional_decimal(row.get("OFFER"))
        bid_size = _optional_decimal(row.get("BIDDEPTHT")) or _optional_decimal(row.get("BIDDEPTH"))
        ask_size = _optional_decimal(row.get("OFFERDEPTHT")) or _optional_decimal(row.get("OFFERDEPTH"))
        timestamp_ms = _row_timestamp_ms(row) or _now_ms()
        bids = [] if bid_price is None else [(bid_price, bid_size or Decimal("0"))]
        asks = [] if ask_price is None else [(ask_price, ask_size or Decimal("0"))]
        return BookSnapshot.from_dicts(timestamp_ms, bids, asks)

    def orderbook_snapshot(
        self,
        symbol: str,
        engine: str = "stock",
        market: str = "shares",
        board: str = "TQBR",
    ) -> BookSnapshot:
        payload = self._get_json(
            f"/engines/{engine}/markets/{market}/boards/{board}/securities/{symbol}/orderbook.json",
            {"iss.meta": "off"},
        )
        rows = _table_rows(payload, "orderbook")
        bids: list[tuple[Decimal, Decimal]] = []
        asks: list[tuple[Decimal, Decimal]] = []
        timestamp_ms = _now_ms()
        for row in rows:
            price = _decimal(row.get("PRICE") or row.get("price"))
            size = _decimal(row.get("QUANTITY") or row.get("VOLUME") or row.get("qty"))
            side = str(row.get("BUYSELL") or row.get("SIDE") or "").upper()
            timestamp_ms = _row_timestamp_ms(row) or timestamp_ms
            if side in {"B", "BUY", "BID"}:
                bids.append((price, size))
            elif side in {"S", "SELL", "ASK", "OFFER"}:
                asks.append((price, size))
        return BookSnapshot.from_dicts(timestamp_ms, bids, asks)

    def trades(
        self,
        symbol: str,
        engine: str = "stock",
        market: str = "shares",
        board: str = "TQBR",
        limit: int | None = None,
    ) -> tuple[Trade, ...]:
        payload = self._get_json(
            f"/engines/{engine}/markets/{market}/boards/{board}/securities/{symbol}/trades.json",
            {"iss.meta": "off"},
        )
        rows = _table_rows(payload, "trades")
        if limit is not None:
            rows = rows[-limit:]
        return tuple(_trade_from_row(row) for row in rows)

    def poll_events(
        self,
        symbol: str,
        engine: str = "stock",
        market: str = "shares",
        board: str = "TQBR",
        polls: int = 3,
        interval_sec: float = 1.0,
        use_top_of_book: bool = False,
        trades_limit: int = 50,
    ) -> tuple[MarketEvent, ...]:
        events: list[MarketEvent] = []
        seen_trades: set[tuple[int, Decimal, Decimal, AggressorSide]] = set()
        for index in range(polls):
            snapshot = (
                self.top_of_book_snapshot(symbol, engine, market, board)
                if use_top_of_book
                else self.orderbook_snapshot(symbol, engine, market, board)
            )
            events.append(MarketEvent(snapshot.timestamp_ms, snapshot=snapshot))
            for trade in self.trades(symbol, engine, market, board, trades_limit):
                key = (trade.timestamp_ms, trade.price, trade.size, trade.aggressor)
                if key in seen_trades:
                    continue
                seen_trades.add(key)
                events.append(MarketEvent(trade.timestamp_ms, trade=trade))
            if index + 1 < polls:
                time.sleep(interval_sec)
        return tuple(sorted(events, key=lambda item: item.timestamp_ms))

    def _get_json(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        query = urllib.parse.urlencode(params)
        url = f"{self.base_url}{path}?{query}"
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                content_type = response.headers.get("content-type", "")
                body = response.read().decode("utf-8", "replace")
        except urllib.error.URLError as exc:
            raise MoexIssError(f"MOEX ISS request failed: {exc}") from exc
        if "json" not in content_type and not body.lstrip().startswith("{"):
            raise MoexIssAccessError(
                "MOEX ISS did not return JSON. For Level II orderbook data this usually means "
                "market-data access is not enabled for the endpoint."
            )
        return json.loads(body)


def _table_rows(payload: dict[str, Any], table: str) -> list[dict[str, Any]]:
    raw = payload.get(table)
    if not raw:
        raise MoexIssError(f"MOEX ISS response has no '{table}' table")
    columns = raw.get("columns") or []
    return [dict(zip(columns, row)) for row in raw.get("data") or []]


def _first_row(payload: dict[str, Any], table: str, required: bool = True) -> dict[str, Any] | None:
    rows = _table_rows(payload, table)
    if rows:
        return rows[0]
    if required:
        raise MoexIssError(f"MOEX ISS table '{table}' is empty")
    return None


def _trade_from_row(row: dict[str, Any]) -> Trade:
    side = str(row.get("BUYSELL") or "").upper()
    if side == "B":
        aggressor = AggressorSide.BUY
    elif side == "S":
        aggressor = AggressorSide.SELL
    else:
        aggressor = AggressorSide.UNKNOWN
    return Trade(
        timestamp_ms=_row_timestamp_ms(row) or _now_ms(),
        price=_decimal(row["PRICE"]),
        size=_decimal(row["QUANTITY"]),
        aggressor=aggressor,
    )


def _row_timestamp_ms(row: dict[str, Any]) -> int | None:
    systime = row.get("SYSTIME")
    if systime:
        return _parse_datetime_ms(str(systime))
    trade_date = row.get("TRADEDATE") or row.get("TRADE_SESSION_DATE")
    trade_time = row.get("TRADETIME") or row.get("TIME")
    if trade_date and trade_time:
        return _parse_datetime_ms(f"{trade_date} {trade_time}")
    return None


def _parse_datetime_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def _decimal(value: Any) -> Decimal:
    if value is None:
        raise MoexIssError("Expected decimal value, got null")
    return Decimal(str(value))


def _optional_decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _now_ms() -> int:
    return int(time.time() * 1000)
