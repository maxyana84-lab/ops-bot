"""HTTP health checks and up/down state tracking with flap protection."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

import httpx

from .config import Target


@dataclass(frozen=True)
class CheckResult:
    target: Target
    ok: bool
    status_code: int | None
    latency_ms: float | None
    error: str | None = None


class Transition(StrEnum):
    DOWN = "down"
    RECOVERED = "recovered"


async def check_target(client: httpx.AsyncClient, target: Target) -> CheckResult:
    started = time.perf_counter()
    try:
        response = await client.get(target.url, timeout=target.timeout, follow_redirects=True)
    except httpx.HTTPError as exc:
        return CheckResult(target, False, None, None, type(exc).__name__)

    latency_ms = (time.perf_counter() - started) * 1000
    ok = response.status_code == target.expected_status
    error = None if ok else f"HTTP {response.status_code} (expected {target.expected_status})"
    return CheckResult(target, ok, response.status_code, latency_ms, error)


async def check_all(client: httpx.AsyncClient, targets: Iterable[Target]) -> list[CheckResult]:
    return list(await asyncio.gather(*(check_target(client, t) for t in targets)))


class StateTracker:
    """Turns a stream of check results into DOWN / RECOVERED transitions.

    A target is reported DOWN only after ``failure_threshold`` consecutive
    failures, so a single slow response does not wake anyone up at night.
    """

    def __init__(self, failure_threshold: int = 2) -> None:
        self.failure_threshold = max(1, failure_threshold)
        self._failures: dict[str, int] = {}
        self._down: set[str] = set()

    def is_down(self, name: str) -> bool:
        return name in self._down

    def update(self, results: Iterable[CheckResult]) -> list[tuple[CheckResult, Transition]]:
        transitions: list[tuple[CheckResult, Transition]] = []
        for result in results:
            name = result.target.name
            if result.ok:
                self._failures[name] = 0
                if name in self._down:
                    self._down.discard(name)
                    transitions.append((result, Transition.RECOVERED))
                continue

            self._failures[name] = self._failures.get(name, 0) + 1
            if self._failures[name] >= self.failure_threshold and name not in self._down:
                self._down.add(name)
                transitions.append((result, Transition.DOWN))
        return transitions
