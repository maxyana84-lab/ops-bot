import httpx

from app.config import Target
from app.health import CheckResult, StateTracker, Transition, check_all

UP = Target("up", "https://up.test/health")
DOWN = Target("down", "https://down.test/health")
TIMEOUT = Target("timeout", "https://timeout.test/health")


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "up.test":
        return httpx.Response(200, text="ok")
    if request.url.host == "down.test":
        return httpx.Response(503)
    raise httpx.ConnectTimeout("timed out", request=request)


async def test_check_all():
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        up, down, timeout = await check_all(client, [UP, DOWN, TIMEOUT])
    assert up.ok and up.status_code == 200 and up.latency_ms is not None
    assert not down.ok and "HTTP 503" in down.error
    assert not timeout.ok and timeout.error == "ConnectTimeout"


def _r(ok: bool) -> CheckResult:
    return CheckResult(UP, ok, 200 if ok else None, 1.0 if ok else None, None if ok else "err")


def test_tracker_requires_consecutive_failures():
    tracker = StateTracker(failure_threshold=2)
    assert tracker.update([_r(False)]) == []  # first failure: no alert yet
    assert tracker.update([_r(True)]) == []  # flap resets the counter
    assert tracker.update([_r(False)]) == []
    [(_, transition)] = tracker.update([_r(False)])
    assert transition is Transition.DOWN
    assert tracker.update([_r(False)]) == []  # no repeated DOWN alerts
    [(_, transition)] = tracker.update([_r(True)])
    assert transition is Transition.RECOVERED
