"""Prometheus metrics exposed by the bot itself on /metrics."""

from prometheus_client import Counter, Gauge

WEBHOOKS_TOTAL = Counter("opsbot_webhooks_total", "Webhook requests received", ["source", "result"])
COMMANDS_TOTAL = Counter("opsbot_commands_total", "Telegram commands handled", ["command"])
MESSAGES_SENT_TOTAL = Counter("opsbot_messages_sent_total", "Telegram messages sent")
SEND_ERRORS_TOTAL = Counter("opsbot_send_errors_total", "Failed Telegram sends")
TARGET_UP = Gauge("opsbot_target_up", "1 if the target passed its last check", ["target"])
TARGET_LATENCY = Gauge(
    "opsbot_target_latency_seconds", "Latency of the last successful check", ["target"]
)
