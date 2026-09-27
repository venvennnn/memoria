from fastapi import APIRouter

from apps.api.deps import get_qdrant_store, get_settings
from apps.api.settings import Settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    settings = get_settings()
    store = get_qdrant_store()
    return {
        "ok": True,
        "qdrant": store.ping(),
        "lyzr_mode": settings.lyzr_mode,
        "collections": [
            settings.collection_name(s) for s in ("memories", "commitments", "receipts", "traces")
        ],
    }
