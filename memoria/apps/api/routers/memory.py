from typing import Any

from fastapi import APIRouter

from apps.api.agents.schemas import MemorySearchRequest
from apps.api.deps import get_embeddings, get_pipeline, get_qdrant_store
from apps.api.services.qdrant_store import QdrantStore

router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("/search")
def memory_search(body: MemorySearchRequest):
    pipeline = get_pipeline()
    hits = pipeline.search_memories(body.uid, body.principal, body.query, body.limit)
    return {"ok": True, "results": hits}


@router.post("/delete")
def memory_delete(body: dict[str, Any]):
    store = get_qdrant_store()
    uid = body.get("uid") or body.get("must", [{}])[0].get("match")
    must = body.get("must") or []
    collections = body.get("collections") or ["memories"]
    deleted = {}
    for coll in collections:
        if coll == "receipts":
            continue
        flt = store.build_filter(uid, [m for m in must if m.get("key") != "uid"])
        pre = store.count(coll, flt)
        store.delete(coll, flt)
        post = store.count(coll, flt)
        deleted[coll] = {"pre": pre, "post": post, "deleted": pre - post}
    return {"ok": True, "deleted": deleted}


@router.post("/count")
def memory_count(body: dict[str, Any]):
    store = get_qdrant_store()
    uid = body.get("uid")
    must = body.get("must") or []
    collections = body.get("collections") or ["memories"]
    counts = {}
    for coll in collections:
        flt = store.build_filter(uid, [m for m in must if m.get("key") != "uid"])
        counts[coll] = store.count(coll, flt)
    return {"ok": True, "counts": counts}


@router.post("/upsert")
def memory_upsert(body: dict[str, Any]):
    store = get_qdrant_store()
    embeddings = get_embeddings()
    coll = body.get("collection", "memories")
    point_id = body.get("id") or store.new_id("mem")
    payload = body.get("payload") or body
    text = payload.get("text", "")
    store.upsert(coll, point_id, embeddings.embed(text), payload)
    return {"ok": True, "id": point_id}
