import os

import pytest
from fastapi.testclient import TestClient

from apps.api.deps import reset_caches
from apps.api.main import create_app


@pytest.fixture
def client():
    reset_caches()
    os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
    os.environ.setdefault("ALLOWED_UIDS", "*")
    return TestClient(create_app())


def test_transcript_returns_200_immediately(client):
    fixture = [
        {"text": "hello world", "speaker": "USER", "is_user": True},
    ]
    resp = client.post("/omi/transcript?uid=demo&session_id=t1", json=fixture)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["accepted"] == 1


def test_rejects_unknown_uid_when_locked(client):
    os.environ["ALLOWED_UIDS"] = "only-me"
    reset_caches()
    client2 = TestClient(create_app())
    resp = client2.post("/omi/transcript?uid=demo&session_id=t1", json=[])
    assert resp.status_code == 403
