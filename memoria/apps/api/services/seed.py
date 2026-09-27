from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apps.api.services.embeddings import EmbeddingService
from apps.api.services.qdrant_store import QdrantStore

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _load_json(name: str) -> list | dict:
    return json.loads((DATA_DIR / name).read_text())


def seed_demo(store: QdrantStore, embeddings: EmbeddingService, uid: str = "demo") -> dict[str, int]:
    store.ensure_collections()
    memories = _load_json("seed_memories.json")
    commitments = _load_json("seed_commitments.json")
    counts = {"memories": 0, "commitments": 0, "receipts": 0}

    for row in memories:
        if row.get("uid") != uid and "uid" in row:
            continue
        row = {**row, "uid": uid}
        pid = row.pop("id")
        text = row.get("text", "")
        store.upsert("memories", pid, embeddings.embed(text), row)
        counts["memories"] += 1

    for row in commitments:
        row = {**row, "uid": uid}
        pid = row.pop("id")
        text = row.get("text", "")
        store.upsert("commitments", pid, embeddings.embed(text), row)
        counts["commitments"] += 1

    receipt = {
        "id": "rcpt_seed_credential",
        "uid": uid,
        "ts": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        "action": "discard",
        "reason": "inferred_never",
        "tier_would_have_been": "never",
        "topic_bucket": "credential",
        "count_points_affected": 1,
        "preview": "redacted credential yesterday",
        "actor": "gatekeeper",
    }
    rid = receipt.pop("id")
    store.upsert("receipts", rid, embeddings.embed(receipt["preview"]), receipt)
    counts["receipts"] += 1

    ttl_note = {
        "id": "mem_seed_ephemeral",
        "uid": uid,
        "text": "Package arriving Tuesday before noon",
        "tier": "ephemeral",
        "scope": ["self"],
        "session_id": "seed",
        "ts": datetime.now(timezone.utc).isoformat(),
        "speaker": "user",
        "is_user": True,
        "people": [],
        "topics": ["logistics"],
        "kind": "fact",
        "status": "active",
        "ttl_expires_at": (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat(),
        "consent_span": "",
        "gate_confidence": 0.9,
        "acl_source": "inferred",
        "source": "seed",
    }
    store.upsert(
        "memories",
        ttl_note["id"],
        embeddings.embed(ttl_note["text"]),
        {k: v for k, v in ttl_note.items() if k != "id"},
    )
    counts["memories"] += 1

    return counts


def reset_demo(store: QdrantStore, embeddings: EmbeddingService, uid: str = "demo") -> dict[str, int]:
    deleted = store.delete_uid(uid)
    from apps.api.services import session_acl
    from apps.api.services.pipeline import clear_events

    session_acl.reset_sessions()
    clear_events()
    seeded = seed_demo(store, embeddings, uid)
    return {"deleted": deleted, "seeded": seeded}
