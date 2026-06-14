"""Gateway plain-text skill trigger routing."""

from types import SimpleNamespace

from gateway.plain_skill_router import rewrite_plain_skill_trigger_event


def test_plain_skill_trigger_rewrites_event_before_agent_loop(monkeypatch):
    calls = {}

    def fake_build(text, task_id=None):
        calls["text"] = text
        calls["task_id"] = task_id
        return "LOADED GO-NOW SKILL"

    monkeypatch.setattr(
        "agent.skill_commands.build_plain_skill_invocation_message",
        fake_build,
    )
    event = SimpleNamespace(text="go now: harden routing")

    assert rewrite_plain_skill_trigger_event(event, task_id="telegram:1") is True
    assert calls == {"text": "go now: harden routing", "task_id": "telegram:1"}
    assert event.text == "LOADED GO-NOW SKILL"


def test_plain_skill_trigger_noop_when_no_match(monkeypatch):
    monkeypatch.setattr(
        "agent.skill_commands.build_plain_skill_invocation_message",
        lambda text, task_id=None: None,
    )
    event = SimpleNamespace(text="ordinary chat")

    assert rewrite_plain_skill_trigger_event(event, task_id="telegram:1") is False
    assert event.text == "ordinary chat"
