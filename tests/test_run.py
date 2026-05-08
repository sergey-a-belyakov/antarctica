from flowcore.recorder import JsonlRecorder
from flowcore.run import enrich_event, recorder_path


def test_enrich_event_adds_market_metadata() -> None:
    payload = {"kind": "book", "timestamp_ms": 1}

    enriched = enrich_event(payload, "SBER", "TQBR", "moex_iss_top_of_book")

    assert enriched == {
        "kind": "book",
        "timestamp_ms": 1,
        "symbol": "SBER",
        "board": "TQBR",
        "source": "moex_iss_top_of_book",
    }


def test_recorder_path_handles_missing_path(tmp_path) -> None:
    recorder = JsonlRecorder(tmp_path, "SBER", "TQBR")

    assert recorder_path(None) is None
    assert recorder_path(recorder) is None
