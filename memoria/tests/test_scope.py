import os

import pytest
from qdrant_client.http import models as qm

from apps.api.deps import get_embeddings, get_pipeline, get_qdrant_store, reset_caches
from apps.api.services.seed import seed_demo


@pytest.fixture(scope="module")
def qdrant_ready():
    reset_caches()
    os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
    store = get_qdrant_store()
    if not store.ping():
        pytest.skip("Qdrant not available")
    yield store


@pytest.mark.asyncio
async def test_roommate_hides_health(qdrant_ready):
    reset_caches()
    store = get_qdrant_store()
    embeddings = get_embeddings()
    uid = "demo-test-scope"
    store.delete_uid(uid)
    seed_demo(store, embeddings, uid)

    pipeline = get_pipeline()
    self_hits = pipeline.search_memories(uid, "self", "knee health", limit=10)
    home_hits = pipeline.search_memories(uid, "circle:home", "knee health", limit=10)

    self_health = [h for h in self_hits if h["payload"].get("kind") == "health" or "knee" in (h["payload"].get("text") or "").lower()]
    home_health = [h for h in home_hits if h["payload"].get("kind") == "health" or "knee" in (h["payload"].get("text") or "").lower()]

    assert len(self_health) >= 1
    assert len(home_health) == 0

    detergent = store.scroll(
        "memories",
        qm.Filter(
            must=[
                qm.FieldCondition(key="uid", match=qm.MatchValue(value=uid)),
                qm.FieldCondition(key="scope", match=qm.MatchValue(value="circle:home")),
            ]
        ),
        limit=5,
    )
    assert any("detergent" in (d["payload"].get("text") or "").lower() for d in detergent)
