from gateway.copy_pack import copy_for, resolve_copy_pack
from gateway.run import _normalize_empty_agent_response


def test_copy_pack_resolves_platform_override():
    cfg = {
        "display": {
            "copy_pack": "default",
            "platforms": {"telegram": {"copy_pack": "bertus"}},
        }
    }

    assert resolve_copy_pack(cfg, "telegram") == "bertus"
    assert resolve_copy_pack(cfg, "discord") == "default"
    assert copy_for(cfg, "telegram").queue_empty == "Backlog leeg."


def test_bertus_queue_lifecycle_copy_is_non_producty():
    copy = copy_for(
        {"display": {"platforms": {"telegram": {"copy_pack": "bertus"}}}},
        "telegram",
    )

    assert copy.format("current_complete", idx=2, total=5) == "Klus klaar. Ik pak backlog taak 2 op."
    assert copy.queue_empty == "Backlog leeg."
    assert "Current task complete" not in copy.format("current_complete", idx=1, total=1)
    assert "Queue empty" not in copy.queue_empty


def test_bertus_processing_error_copy_replaces_sorry_try_again():
    copy = copy_for({"display": {"copy_pack": "bertus"}}, "telegram")

    message = _normalize_empty_agent_response(
        {"failed": True, "error": "provider exploded"},
        "",
        copy_pack=copy,
    )

    assert "Daar ging iets stuk" in message
    assert "Niet gelukt; opnieuw sturen of /reset." in message
    assert "Sorry" not in message
    assert "Try again" not in message
