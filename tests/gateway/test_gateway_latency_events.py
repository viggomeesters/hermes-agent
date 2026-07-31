import json
from dataclasses import dataclass
from enum import Enum

from gateway.turn_latency import begin_turn, finish_turn, mark_turn_phase


class Platform(Enum):
    TELEGRAM = "telegram"


@dataclass
class Source:
    platform: Platform = Platform.TELEGRAM
    chat_id: str = "8340627826"


def test_turn_latency_writes_bounded_payload_free_local_evidence(tmp_path):
    source = Source()
    message_id = "message-42"

    begin_turn(source, message_id)
    mark_turn_phase(source, message_id, "ack")
    mark_turn_phase(source, message_id, "first_progress")
    finish_turn(source, message_id, "success", home=tmp_path)

    path = tmp_path / "logs" / "turn-latency.jsonl"
    row = json.loads(path.read_text(encoding="utf-8"))

    assert row["schema"] == "hermes.turn-latency.v1"
    assert row["platform"] == "telegram"
    assert row["outcome"] == "success"
    assert row["ack_ms"] <= row["total_ms"]
    assert row["first_progress_ms"] <= row["total_ms"]
    assert "chat_id" not in row
    assert "message_id" not in row
    assert "text" not in row
    assert "tool" not in row
    assert path.stat().st_mode & 0o777 == 0o600
