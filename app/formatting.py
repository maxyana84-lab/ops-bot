"""Render alerts and status reports as Telegram HTML messages."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from html import escape
from typing import Any

from .health import CheckResult, Transition

TELEGRAM_LIMIT = 4096

SEVERITY_ICONS = {"critical": "🔴", "warning": "🟠", "info": "🔵"}
LEVEL_ICONS = {"success": "✅", "failure": "❌", "warning": "⚠️", "info": "ℹ️"}


def truncate(text: str, limit: int = TELEGRAM_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n… (truncated)"


def format_alertmanager(payload: Mapping[str, Any]) -> str:
    """Format an Alertmanager webhook payload (version 4)."""
    alerts = payload.get("alerts") or []
    firing = [a for a in alerts if a.get("status") == "firing"]
    resolved = [a for a in alerts if a.get("status") == "resolved"]

    lines: list[str] = []
    for title, group, resolved_group in (("FIRING", firing, False), ("RESOLVED", resolved, True)):
        if not group:
            continue
        lines.append(f"<b>{title} ({len(group)})</b>")
        for alert in group:
            labels = alert.get("labels") or {}
            annotations = alert.get("annotations") or {}
            severity = str(labels.get("severity", "info")).lower()
            icon = "✅" if resolved_group else SEVERITY_ICONS.get(severity, "⚪")
            name = escape(str(labels.get("alertname", "unknown")))
            lines.append(f"{icon} <b>{name}</b> [{escape(severity)}]")
            if instance := labels.get("instance"):
                lines.append(f"   instance: <code>{escape(str(instance))}</code>")
            summary = annotations.get("summary") or annotations.get("description")
            if summary:
                lines.append(f"   {escape(str(summary))}")
        lines.append("")

    if not lines:
        return "ℹ️ Alertmanager sent an empty notification."
    return truncate("\n".join(lines).strip())


def format_notify(payload: Mapping[str, Any]) -> str:
    """Format a generic notification, e.g. from a CI/CD pipeline."""
    level = str(payload.get("level", "info")).lower()
    icon = LEVEL_ICONS.get(level, "ℹ️")
    title = escape(str(payload.get("title") or "Notification"))
    text = escape(str(payload.get("text") or ""))
    url = payload.get("url")
    message = f"{icon} <b>{title}</b>"
    if text:
        message += f"\n{text}"
    if url:
        message += f'\n<a href="{escape(str(url), quote=True)}">Open</a>'
    return truncate(message)


def _result_line(result: CheckResult) -> str:
    name = escape(result.target.name)
    if result.ok:
        return f"🟢 <b>{name}</b> — {result.latency_ms:.0f} ms"
    return f"🔴 <b>{name}</b> — {escape(result.error or 'failed')}"


def format_status(results: Iterable[CheckResult]) -> str:
    results = list(results)
    if not results:
        return "No targets configured. Add some to <code>config/targets.yaml</code>."
    up = sum(r.ok for r in results)
    header = f"<b>Status: {up}/{len(results)} up</b>"
    return truncate("\n".join([header, *(_result_line(r) for r in results)]))


def format_transition(result: CheckResult, transition: Transition) -> str:
    name = escape(result.target.name)
    url = escape(result.target.url)
    if transition is Transition.DOWN:
        error = escape(result.error or "check failed")
        return f"🔴 <b>{name} is DOWN</b>\n{error}\n<code>{url}</code>"
    return f"✅ <b>{name} recovered</b> — {result.latency_ms:.0f} ms\n<code>{url}</code>"
