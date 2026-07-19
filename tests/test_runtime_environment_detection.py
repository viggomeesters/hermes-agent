import hermes_constants


def test_wsl_is_not_reported_as_a_container(monkeypatch):
    monkeypatch.setattr(hermes_constants, "is_wsl", lambda: True)
    monkeypatch.setattr(hermes_constants.os.path, "exists", lambda _path: True)
    hermes_constants._container_detected = None

    assert hermes_constants.is_container() is False
