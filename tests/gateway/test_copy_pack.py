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



def test_external_copy_pack_dir_overrides_builtin(tmp_path):
    pack_dir = tmp_path / "packs"
    pack_dir.mkdir()
    (pack_dir / "bertus.json").write_text(
        """
        {
          "name": "bertus",
          "messages": {
            "current_complete": "External done {idx}/{total}",
            "queue_empty": "External empty",
            "queue_full_current": "External full {count}/{max_pending}{status_detail}",
            "queue_full_drain": "External drain full {action}",
            "queued_drain": "External queued {action}",
            "drain_not_accepting": "External no {action}",
            "busy_queue": "External busy {count}{status_detail}",
            "busy_queue_subagent": "External sub {count}{status_detail}",
            "busy_steer": "External steer{status_detail}",
            "busy_interrupt": "External interrupt{status_detail}",
            "processing_error": "External error {error_type}: {error_detail}"
          }
        }
        """,
        encoding="utf-8",
    )
    cfg = {
        "display": {
            "copy_pack_dirs": [str(pack_dir)],
            "platforms": {"telegram": {"copy_pack": "bertus"}},
        }
    }

    assert resolve_copy_pack(cfg, "telegram") == "bertus"
    assert copy_for(cfg, "telegram").queue_empty == "External empty"
    assert copy_for(cfg, "telegram").format("current_complete", idx=2, total=5) == "External done 2/5"


def test_invalid_external_copy_pack_falls_back_to_default(tmp_path):
    pack_dir = tmp_path / "packs"
    pack_dir.mkdir()
    (pack_dir / "broken.json").write_text('{"name":"broken","messages":{"queue_empty":"missing required"}}')
    cfg = {"display": {"copy_pack_dirs": [str(pack_dir)], "copy_pack": "broken"}}

    assert resolve_copy_pack(cfg, None) == "default"
    assert copy_for(cfg).queue_empty == "✅ Queue empty."
