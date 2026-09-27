from fastapi import APIRouter, Query
from qdrant_client.http import models as qm

from apps.api.deps import get_qdrant_store

router = APIRouter(prefix="/receipts", tags=["receipts"])


@router.get("")
def list_receipts(uid: str = Query(...), limit: int = 50):
    store = get_qdrant_store()
    flt = qm.Filter(must=[qm.FieldCondition(key="uid", match=qm.MatchValue(value=uid))])
    rows = store.scroll("receipts", flt, limit=limit)
    return {"ok": True, "receipts": [{"id": r["id"], **r["payload"]} for r in rows]}
