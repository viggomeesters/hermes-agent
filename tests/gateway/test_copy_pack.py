import json

from gateway.copy_pack import copy_for, resolve_copy_pack
from gateway.run import _normalize_empty_agent_response


BERTUS_MESSAGES = {
    "current_complete": "Klus klaar. Ik pak backlog taak {idx} op.",
    "queue_empty": "Backlog leeg.",
    "queue_full_current": "Backlog vol ({count}/{max_pending}){status_detail}. Niet gelukt; stuur opnieuw als de huidige klus klaar is.",
    "queue_full_drain": "Backlog vol — ik kon dit niet bewaren terwijl de gateway {action}. Stuur opnieuw zodra hij terug is.",
    "queued_drain": "Gateway {action}. Ik heb dit in de backlog gezet.",
    "drain_not_accepting": "Gateway {action}; ik neem nu geen extra klus aan.",
    "busy_queue": "Ik ben al bezig; dit is backlog taak {count}{status_detail}. Ik pak ’m vanzelf op.",
    "busy_queue_subagent": "Ik ben al bezig met subagents; dit is backlog taak {count}{status_detail}. Ik pak ’m op zodra die klus klaar is. /stop breekt alles af.",
    "busy_steer": "Ik heb ’m bij de lopende klus gezet{status_detail}; na de volgende toolcall lees ik ’m mee.",
    "busy_interrupt": "Ik kap de huidige klus af{status_detail}. Ik pak je nieuwe bericht zo op.",
    "processing_error": "Daar ging iets stuk ({error_type}).\nIk heb dit nodig: {error_detail}\nNiet gelukt; opnieuw sturen of /reset.",
}


def bertus_cfg(tmp_path):
    pack_dir = tmp_path / "packs"
    pack_dir.mkdir()
    (pack_dir / "bertus.json").write_text(
        json.dumps({"name": "bertus", "messages": BERTUS_MESSAGES}),
        encoding="utf-8",
    )
    return {
        "display": {
            "copy_pack_dirs": [str(pack_dir)],
            "platforms": {"telegram": {"copy_pack": "bertus"}},
        }
    }


def test_copy_pack_resolves_platform_override_from_external_dir(tmp_path):
    cfg = bertus_cfg(tmp_path)

    assert resolve_copy_pack(cfg, "telegram") == "bertus"
    assert resolve_copy_pack(cfg, "discord") == "default"
    assert copy_for(cfg, "telegram").queue_empty == "Backlog leeg."


def test_unknown_copy_pack_without_external_pack_falls_back_to_default():
    cfg = {"display": {"platforms": {"telegram": {"copy_pack": "missing-persona-pack"}}}}

    assert resolve_copy_pack(cfg, "telegram") == "default"
    assert copy_for(cfg, "telegram").queue_empty == "✅ Queue empty."


def test_bertus_queue_lifecycle_copy_is_non_producty(tmp_path):
    copy = copy_for(bertus_cfg(tmp_path), "telegram")

    assert copy.format("current_complete", idx=2, total=5) == "Klus klaar. Ik pak backlog taak 2 op."
    assert copy.queue_empty == "Backlog leeg."
    assert "Current task complete" not in copy.format("current_complete", idx=1, total=1)
    assert "Queue empty" not in copy.queue_empty


def test_bertus_processing_error_copy_replaces_sorry_try_again(tmp_path):
    copy = copy_for(bertus_cfg(tmp_path), "telegram")

    message = _normalize_empty_agent_response(
        {"failed": True, "error": "provider exploded"},
        "",
        copy_pack=copy,
    )

    assert "Daar ging iets stuk" in message
    assert "Niet gelukt; opnieuw sturen of /reset." in message
    assert "Sorry" not in message
    assert "Try again" not in message


def test_external_copy_pack_dir_loads_named_pack(tmp_path):
    cfg = bertus_cfg(tmp_path)

    assert resolve_copy_pack(cfg, "telegram") == "bertus"
    assert copy_for(cfg, "telegram").queue_empty == "Backlog leeg."
    assert copy_for(cfg, "telegram").format("current_complete", idx=2, total=5) == "Klus klaar. Ik pak backlog taak 2 op."


def test_external_copy_pack_dir_accepts_string_path(tmp_path):
    cfg = bertus_cfg(tmp_path)
    cfg["display"]["copy_pack_dirs"] = cfg["display"]["copy_pack_dirs"][0]

    assert resolve_copy_pack(cfg, "telegram") == "bertus"
    assert copy_for(cfg, "telegram").queue_empty == "Backlog leeg."


def test_invalid_external_copy_pack_falls_back_to_default(tmp_path):
    pack_dir = tmp_path / "packs"
    pack_dir.mkdir()
    (pack_dir / "broken.json").write_text('{"name":"broken","messages":{"queue_empty":"missing required"}}')
    cfg = {"display": {"copy_pack_dirs": [str(pack_dir)], "copy_pack": "broken"}}

    assert resolve_copy_pack(cfg, None) == "default"
    assert copy_for(cfg).queue_empty == "✅ Queue empty."
