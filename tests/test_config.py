import pytest

from app.config import load_settings

BASE = {"TELEGRAM_TOKEN": "123:abc", "WEBHOOK_SECRET": "x" * 16}


def test_parses_ids_and_defaults_allowed_to_alert_ids(tmp_path):
    targets = tmp_path / "targets.yaml"
    targets.write_text("targets:\n  - name: api\n    url: https://api.test\n    timeout: 2\n")
    settings = load_settings({**BASE, "ALERT_CHAT_IDS": "1, -100200", "TARGETS_FILE": str(targets)})
    assert settings.alert_chat_ids == (1, -100200)
    assert settings.allowed_chat_ids == (1, -100200)
    assert settings.targets[0].name == "api" and settings.targets[0].timeout == 2


def test_missing_token_fails():
    with pytest.raises(RuntimeError, match="TELEGRAM_TOKEN"):
        load_settings({"WEBHOOK_SECRET": "x" * 16})


def test_short_secret_fails():
    with pytest.raises(RuntimeError, match="WEBHOOK_SECRET"):
        load_settings({"TELEGRAM_TOKEN": "1:a", "WEBHOOK_SECRET": "short"})


def test_missing_targets_file_is_ok():
    assert load_settings({**BASE, "TARGETS_FILE": "/nope.yaml"}).targets == ()
