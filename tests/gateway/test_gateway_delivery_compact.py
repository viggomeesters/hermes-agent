from gateway.config import Platform
from gateway.platforms import base


def _patch_config(monkeypatch, platform_cfg):
    def _fake_load_config():
        return {"display": {"platforms": {"telegram": platform_cfg}}}

    import hermes_cli.config as config_mod

    monkeypatch.setattr(config_mod, "load_config", _fake_load_config)


def test_gateway_delivery_cap_is_disabled_by_default(monkeypatch):
    _patch_config(monkeypatch, {})
    text = "line\n" * 50

    assert base._compact_gateway_text_for_delivery(Platform.TELEGRAM, text) == text


def test_gateway_delivery_cap_truncates_telegram_chars(monkeypatch):
    _patch_config(monkeypatch, {"final_reply_max_chars": 120})
    text = "A" * 500

    compacted = base._compact_gateway_text_for_delivery(Platform.TELEGRAM, text)

    assert base.utf16_len(compacted) <= 120
    assert compacted.endswith("…")
    forbidden_detail = "Detail" + " bewaard"
    forbidden_prompt = "Vraag " + "‘detail’"
    assert forbidden_detail not in compacted
    assert forbidden_prompt not in compacted
    assert compacted.startswith("A")


def test_gateway_delivery_cap_obeys_tiny_char_caps(monkeypatch):
    _patch_config(monkeypatch, {"final_reply_max_chars": 10})
    text = "A" * 500

    compacted = base._compact_gateway_text_for_delivery(Platform.TELEGRAM, text)

    assert base.utf16_len(compacted) <= 10
    assert compacted.endswith("…")
    assert compacted.startswith("A")


def test_gateway_delivery_line_cap_with_char_cap_stays_under_limit(monkeypatch):
    _patch_config(monkeypatch, {"final_reply_max_lines": 2, "final_reply_max_chars": 70})
    text = "first line is already quite long\nsecond line also has content\nthird line"

    compacted = base._compact_gateway_text_for_delivery(Platform.TELEGRAM, text)

    assert base.utf16_len(compacted) <= 70
    assert "third line" not in compacted


def test_gateway_delivery_cap_truncates_telegram_lines(monkeypatch):
    _patch_config(monkeypatch, {"final_reply_max_lines": 3})
    text = "one\ntwo\nthree\nfour\nfive"

    compacted = base._compact_gateway_text_for_delivery(Platform.TELEGRAM, text)

    assert compacted.startswith("one\ntwo\nthree")
    assert "four" not in compacted
    assert compacted.endswith("…")
    forbidden_detail = "Detail" + " bewaard"
    forbidden_prompt = "Vraag " + "‘detail’"
    assert forbidden_detail not in compacted
    assert forbidden_prompt not in compacted


def test_gateway_delivery_cap_ignores_other_platforms_without_config(monkeypatch):
    _patch_config(monkeypatch, {"final_reply_max_chars": 80})
    text = "B" * 200

    assert base._compact_gateway_text_for_delivery(Platform.DISCORD, text) == text
