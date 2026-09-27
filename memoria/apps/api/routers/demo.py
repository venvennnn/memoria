from typing import Any

from fastapi import APIRouter, Query
from qdrant_client.http import models as qm

from apps.api.deps import get_embeddings, get_pipeline, get_qdrant_store, get_settings
from apps.api.services.pipeline import get_events
from apps.api.services.seed import reset_demo, seed_demo
from apps.api.agents.schemas import DevUtteranceRequest

router = APIRouter(tags=["demo"])


@router.post("/dev/utterance")
async def dev_utterance(body: DevUtteranceRequest):
    pipeline = get_pipeline()
    result = await pipeline.process_utterance(
        uid=body.uid,
        session_id=body.session_id,
        text=body.text,
        speaker=body.speaker,
        is_user=body.is_user,
        principal=body.principal,
    )
    return {"ok": True, "result": result}


@router.post("/dev/seed")
def dev_seed(uid: str = "demo"):
    store = get_qdrant_store()
    embeddings = get_embeddings()
    counts = seed_demo(store, embeddings, uid)
    return {"ok": True, "counts": counts}


@router.post("/dev/reset")
def dev_reset(uid: str = "demo"):
    store = get_qdrant_store()
    embeddings = get_embeddings()
    result = reset_demo(store, embeddings, uid)
    return {"ok": True, **result}


@router.get("/demo/state")
def demo_state(uid: str = "demo", principal: str = "self") -> dict[str, Any]:
    settings = get_settings()
    store = get_qdrant_store()
    pipeline = get_pipeline()

    mem_flt = qm.Filter(
        must=[
            qm.FieldCondition(key="uid", match=qm.MatchValue(value=uid)),
            qm.FieldCondition(key="status", match=qm.MatchValue(value="active")),
            store.principal_scope_match(principal).must[0],
        ]
    )
    memories = store.scroll("memories", mem_flt, limit=100)

    c_flt = qm.Filter(
        must=[
            qm.FieldCondition(key="uid", match=qm.MatchValue(value=uid)),
            qm.FieldCondition(key="status", match=qm.MatchValue(value="open")),
            store.principal_scope_match(principal).must[0],
        ]
    )
    commitments = store.scroll("commitments", c_flt, limit=50)

    r_flt = qm.Filter(must=[qm.FieldCondition(key="uid", match=qm.MatchValue(value=uid))])
    receipts = store.scroll("receipts", r_flt, limit=50)

    health_count = store.count(
        "memories",
        qm.Filter(
            must=[
                qm.FieldCondition(key="uid", match=qm.MatchValue(value=uid)),
                qm.FieldCondition(key="topics", match=qm.MatchAny(any=["health"])),
            ]
        ),
    )

    return {
        "uid": uid,
        "principal": principal,
        "lyzr_mode": settings.lyzr_mode,
        "events": get_events()[:40],
        "memories": [{"id": m["id"], **m["payload"]} for m in memories],
        "commitments": [{"id": c["id"], **c["payload"]} for c in commitments],
        "receipts": [{"id": r["id"], **r["payload"]} for r in receipts],
        "counts": {
            "memories": store.count("memories", qm.Filter(must=[qm.FieldCondition(key="uid", match=qm.MatchValue(value=uid))])),
            "commitments": store.count("commitments", qm.Filter(must=[qm.FieldCondition(key="uid", match=qm.MatchValue(value=uid))])),
            "receipts": store.count("receipts", qm.Filter(must=[qm.FieldCondition(key="uid", match=qm.MatchValue(value=uid))])),
            "health": health_count,
        },
        "last_forget": _last_forget(receipts),
    }


def _last_forget(receipts: list) -> dict[str, int] | None:
    for r in receipts:
        pl = r.get("payload", {})
        if pl.get("action") == "delete":
            n = int(pl.get("count_points_affected") or 0)
            return {"deleted": n, "post": 0}
    return None
