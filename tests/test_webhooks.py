import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.webhooks import build_web_app

SECRET = "s3cr3t-s3cr3t-s3cr3t"
AUTH = {"Authorization": f"Bearer {SECRET}"}


@pytest.fixture
async def client_and_sent():
    sent: list[str] = []

    async def send(text: str) -> None:
        sent.append(text)

    client = TestClient(TestServer(build_web_app(SECRET, send)))
    await client.start_server()
    yield client, sent
    await client.close()


async def test_healthz_and_metrics(client_and_sent):
    client, _ = client_and_sent
    assert (await client.get("/healthz")).status == 200
    body = await (await client.get("/metrics")).text()
    assert "opsbot_webhooks_total" in body


async def test_rejects_missing_or_wrong_token(client_and_sent):
    client, sent = client_and_sent
    assert (await client.post("/webhook/notify", json={})).status == 401
    bad = {"Authorization": "Bearer nope"}
    assert (await client.post("/webhook/notify", json={}, headers=bad)).status == 401
    assert sent == []


async def test_rejects_invalid_json(client_and_sent):
    client, sent = client_and_sent
    resp = await client.post("/webhook/notify", data="not json", headers=AUTH)
    assert resp.status == 400
    resp = await client.post("/webhook/notify", json=[1, 2], headers=AUTH)
    assert resp.status == 400
    assert sent == []


async def test_alertmanager_is_forwarded(client_and_sent):
    client, sent = client_and_sent
    payload = {"alerts": [{"status": "firing", "labels": {"alertname": "TargetDown"}}]}
    resp = await client.post("/webhook/alertmanager", json=payload, headers=AUTH)
    assert resp.status == 200
    assert len(sent) == 1 and "TargetDown" in sent[0]


async def test_notify_is_forwarded(client_and_sent):
    client, sent = client_and_sent
    resp = await client.post("/webhook/notify", json={"title": "Deploy ok"}, headers=AUTH)
    assert resp.status == 200
    assert "Deploy ok" in sent[0]
