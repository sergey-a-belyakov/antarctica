import json
from decimal import Decimal

from flowcore.recorder import JsonlRecorder


def test_jsonl_recorder_writes_symbol_board_date_path(tmp_path) -> None:
    recorder = JsonlRecorder(tmp_path, "sber", "tqbr")

    path = recorder.write({"kind": "book", "price": Decimal("318.85")}, 1778249031000)
    recorder.close()

    assert path == tmp_path / "SBER" / "TQBR" / "2026-05-08.jsonl"
    rows = path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0]) == {"kind": "book", "price": "318.85"}


def test_jsonl_recorder_rotates_by_utc_date(tmp_path) -> None:
    recorder = JsonlRecorder(tmp_path, "SBER", "TQBR")

    first = recorder.write({"kind": "book"}, 1778284799000)
    second = recorder.write({"kind": "book"}, 1778284800000)
    recorder.close()

    assert first.name == "2026-05-08.jsonl"
    assert second.name == "2026-05-09.jsonl"
