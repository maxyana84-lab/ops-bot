"""Configuration loaded from environment variables and a YAML targets file."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Target:
    """An HTTP endpoint the bot health-checks periodically."""

    name: str
    url: str
    timeout: float = 5.0
    expected_status: int = 200


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    webhook_secret: str
    alert_chat_ids: tuple[int, ...]
    allowed_chat_ids: tuple[int, ...]
    http_host: str = "0.0.0.0"
    http_port: int = 8080
    check_interval: int = 60
    failure_threshold: int = 2
    targets: tuple[Target, ...] = field(default_factory=tuple)


def _parse_ids(raw: str) -> tuple[int, ...]:
    return tuple(int(part) for part in raw.replace(" ", "").split(",") if part)


def load_targets(path: str | os.PathLike[str] | None) -> tuple[Target, ...]:
    if not path or not Path(path).exists():
        return ()
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return tuple(Target(**item) for item in data.get("targets") or [])


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    token = env.get("TELEGRAM_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN is not set")
    secret = env.get("WEBHOOK_SECRET", "").strip()
    if len(secret) < 16:
        raise RuntimeError("WEBHOOK_SECRET must be set and at least 16 characters long")

    alert_ids = _parse_ids(env.get("ALERT_CHAT_IDS", ""))
    allowed_ids = _parse_ids(env.get("ALLOWED_CHAT_IDS", "")) or alert_ids

    return Settings(
        telegram_token=token,
        webhook_secret=secret,
        alert_chat_ids=alert_ids,
        allowed_chat_ids=allowed_ids,
        http_host=env.get("HTTP_HOST", "0.0.0.0"),
        http_port=int(env.get("HTTP_PORT", "8080")),
        check_interval=int(env.get("CHECK_INTERVAL_SECONDS", "60")),
        failure_threshold=int(env.get("FAILURE_THRESHOLD", "2")),
        targets=load_targets(env.get("TARGETS_FILE", "config/targets.yaml")),
    )
