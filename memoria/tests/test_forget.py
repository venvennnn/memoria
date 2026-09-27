import os

import pytest
from qdrant_client.http import models as qm

from apps.api.deps import get_embeddings, get_pipeline, get_qdrant_store, reset_caches
from apps.api.services.seed import reset_demo


@pytest.fixture(scope="module")
def qdrant_ready():
    reset_caches()
    os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
    os.environ.setdefault("QDRANT_API_KEY", "")
    store = get_qdrant_store()
    if not store.ping():
        pytest.skip("Qdrant not available")
    store.ensure_collections()
    yield store


@pytest.mark.asyncio
async def test_forget_health_zeros_and_keeps_rohan(qdrant_ready):
    reset_caches()
    store = get_qdrant_store()
    embeddings = get_embeddings()
    reset_demo(store, embeddings, "demo-test-forget")

    pipeline = get_pipeline()
    pre = store.count(
        "memories",
        qm.Filter(
            must=[
                qm.FieldCondition(key="uid", match=qm.MatchValue(value="demo-test-forget")),
                qm.FieldCondition(key="topics", match=qm.MatchAny(any=["health"])),
            ]
        ),
    )
    assert pre >= 1

    await pipeline.run_forget("demo-test-forget", "live", "forget everything about my health")
    post = store.count(
        "memories",
        qm.Filter(
            must=[
                qm.FieldCondition(key="uid", match=qm.MatchValue(value="demo-test-forget")),
                qm.FieldCondition(key="topics", match=qm.MatchAny(any=["health"])),
            ]
        ),
    )
    assert post == 0

    rohan = store.scroll(
        "commitments",
        qm.Filter(
            must=[
                qm.FieldCondition(key="uid", match=qm.MatchValue(value="demo-test-forget")),
                qm.FieldCondition(key="who", match=qm.MatchValue(value="arjun")),
            ]
        ),
        limit=5,
    )
    assert len(rohan) >= 1
