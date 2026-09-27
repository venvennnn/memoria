from fastapi import APIRouter, Query
from qdrant_client.http import models as qm

from apps.api.agents.schemas import SetStatusRequest
from apps.api.deps import get_qdrant_store

router = APIRouter(prefix="/commitments", tags=["commitments"])


@router.get("")
def list_commitments(
    uid: str = Query(...),
    principal: str = Query("self"),
    status: str = Query("open"),
):
    store = get_qdrant_store()
    flt = qm.Filter(
        must=[
            qm.FieldCondition(key="uid", match=qm.MatchValue(value=uid)),
            qm.FieldCondition(key="status", match=qm.MatchValue(value=status)),
            store.principal_scope_match(principal).must[0],
        ]
    )
    rows = store.scroll("commitments", flt, limit=100)
    return {"ok": True, "commitments": [{"id": r["id"], **r["payload"]} for r in rows]}


@router.post("/set_status")
def set_status(body: SetStatusRequest):
    store = get_qdrant_store()
    store.set_payload("commitments", body.id, {"status": body.status})
    return {"ok": True, "id": body.id, "status": body.status}
