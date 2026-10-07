from app.config import Target
from app.formatting import (
    TELEGRAM_LIMIT,
    format_alertmanager,
    format_notify,
    format_status,
    format_transition,
)
from app.health import CheckResult, Transition

API = Target("api", "https://api.example.com/health")


def test_alertmanager_firing_and_resolved():
    payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "HighCPU", "severity": "critical", "instance": "node-1"},
                "annotations": {"summary": "CPU > 90% for 5m"},
            },
            {
                "status": "resolved",
                "labels": {"alertname": "DiskFull", "severity": "warning"},
                "annotations": {},
            },
        ],
    }
    text = format_alertmanager(payload)
    assert "FIRING (1)" in text
    assert "RESOLVED (1)" in text
    assert "🔴 <b>HighCPU</b>" in text
    assert "<code>node-1</code>" in text
    assert "CPU &gt; 90%" in text  # HTML-escaped


def test_alertmanager_escapes_html_in_labels():
    payload = {"alerts": [{"status": "firing", "labels": {"alertname": "<script>"}}]}
    assert "&lt;script&gt;" in format_alertmanager(payload)


def test_alertmanager_empty():
    assert "empty" in format_alertmanager({"alerts": []})


def test_long_message_is_truncated():
    alerts = [
        {
            "status": "firing",
            "labels": {"alertname": f"A{i}"},
            "annotations": {"summary": "x" * 200},
        }
        for i in range(100)
    ]
    text = format_alertmanager({"alerts": alerts})
    assert len(text) <= TELEGRAM_LIMIT
    assert text.endswith("(truncated)")


def test_notify():
    text = format_notify(
        {"title": "Deploy", "text": "v1.2 to prod", "level": "success", "url": "https://x.io"}
    )
    assert text.startswith("✅ <b>Deploy</b>")
    assert 'href="https://x.io"' in text


def test_status_and_transitions():
    ok = CheckResult(API, True, 200, 42.0)
    bad = CheckResult(API, False, None, None, "ConnectTimeout")
    assert "1/2 up" in format_status([ok, bad])
    assert "DOWN" in format_transition(bad, Transition.DOWN)
    assert "recovered" in format_transition(ok, Transition.RECOVERED)
