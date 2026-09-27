from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from apps.api.settings import Settings

COLLECTION_SUFFIXES = ("memories", "commitments", "receipts", "traces")

PAYLOAD_INDEX_FIELDS = {
    "memories": [
        "tier",
        "scope",
        "status",
        "people",
        "topics",
        "kind",
        "session_id",
        "uid",
        "acl_source",
        "ts",
        "ttl_expires_at",
    ],
    "commitments": [
        "tier",
        "scope",
        "status",
        "people",
        "topics",
        "kind",
        "session_id",
        "uid",
        "direction",
        "ts",
    ],
    "receipts": ["uid", "action", "reason", "ts"],
    "traces": ["uid", "agent", "ok", "ts"],
}


class QdrantStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        kwargs: dict[str, Any] = {"url": settings.qdrant_url}
        if settings.qdrant_api_key:
            kwargs["api_key"] = settings.qdrant_api_key
        self.client = QdrantClient(**kwargs)
        self._bootstrapped = False

    def collection(self, suffix: str) -> str:
        return self.settings.collection_name(suffix)

    def ensure_collections(self) -> None:
        if self._bootstrapped:
            return
        dim = self.settings.embedding_dim
        for suffix in COLLECTION_SUFFIXES:
            name = self.collection(suffix)
            if not self.client.collection_exists(name):
                self.client.create_collection(
                    collection_name=name,
                    vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
                )
            self._ensure_indexes(name, suffix)
        self._bootstrapped = True

    def _ensure_indexes(self, collection: str, suffix: str) -> None:
        fields = PAYLOAD_INDEX_FIELDS.get(suffix, [])
        for field in fields:
            try:
                if field in ("ts", "ttl_expires_at"):
                    self.client.create_payload_index(
                        collection_name=collection,
                        field_name=field,
                        field_schema=qm.PayloadSchemaType.DATETIME,
                    )
                else:
                    self.client.create_payload_index(
                        collection_name=collection,
                        field_name=field,
                        field_schema=qm.PayloadSchemaType.KEYWORD,
                    )
            except Exception:
                pass

    def ping(self) -> bool:
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False

    def upsert(
        self,
        collection_suffix: str,
        point_id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> str:
        self.ensure_collections()
        name = self.collection(collection_suffix)
        self.client.upsert(
            collection_name=name,
            points=[
                qm.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )
            ],
        )
        return point_id

    def set_payload(self, collection_suffix: str, point_id: str, payload: dict[str, Any]) -> None:
        self.ensure_collections()
        name = self.collection(collection_suffix)
        self.client.set_payload(collection_name=name, payload=payload, points=[point_id])

    def search(
        self,
        collection_suffix: str,
        vector: list[float],
        filter_: qm.Filter | None,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        self.ensure_collections()
        name = self.collection(collection_suffix)
        results = self.client.search(
            collection_name=name,
            query_vector=vector,
            query_filter=filter_,
            limit=limit,
            with_payload=True,
        )
        out: list[dict[str, Any]] = []
        for hit in results:
            out.append(
                {
                    "id": str(hit.id),
                    "score": hit.score,
                    "payload": hit.payload or {},
                }
            )
        return out

    def scroll(
        self,
        collection_suffix: str,
        filter_: qm.Filter | None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self.ensure_collections()
        name = self.collection(collection_suffix)
        points, _ = self.client.scroll(
            collection_name=name,
            scroll_filter=filter_,
            limit=limit,
            with_payload=True,
        )
        return [{"id": str(p.id), "payload": p.payload or {}} for p in points]

    def count(self, collection_suffix: str, filter_: qm.Filter | None = None) -> int:
        self.ensure_collections()
        name = self.collection(collection_suffix)
        result = self.client.count(collection_name=name, count_filter=filter_, exact=True)
        return int(result.count)

    def delete(self, collection_suffix: str, filter_: qm.Filter) -> int:
        self.ensure_collections()
        name = self.collection(collection_suffix)
        pre = self.count(collection_suffix, filter_)
        self.client.delete(
            collection_name=name,
            points_selector=qm.FilterSelector(filter=filter_),
        )
        post = self.count(collection_suffix, filter_)
        return pre - post

    def delete_uid(self, uid: str) -> dict[str, int]:
        deleted: dict[str, int] = {}
        for suffix in COLLECTION_SUFFIXES:
            flt = qm.Filter(must=[qm.FieldCondition(key="uid", match=qm.MatchValue(value=uid))])
            deleted[suffix] = self.delete(suffix, flt)
        return deleted

    @staticmethod
    def new_id(prefix: str = "mem") -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).astimezone().isoformat()

    @staticmethod
    def build_filter(uid: str, must: list[dict[str, Any]] | None = None) -> qm.Filter:
        conditions: list[Any] = [
            qm.FieldCondition(key="uid", match=qm.MatchValue(value=uid)),
        ]
        for clause in must or []:
            key = clause.get("key")
            if "match" in clause:
                conditions.append(
                    qm.FieldCondition(key=key, match=qm.MatchValue(value=clause["match"]))
                )
            elif "match_any" in clause:
                conditions.append(
                    qm.FieldCondition(
                        key=key,
                        match=qm.MatchAny(any=clause["match_any"]),
                    )
                )
        return qm.Filter(must=conditions)

    @staticmethod
    def scope_filter(principal: str) -> qm.FieldCondition:
        return qm.FieldCondition(key="scope", match=qm.MatchAny(any=[principal, "self"] if principal != "self" else ["self"]))

    @staticmethod
    def principal_scope_match(principal: str) -> qm.Filter:
        if principal == "self":
            return qm.Filter(
                must=[
                    qm.FieldCondition(key="scope", match=qm.MatchAny(any=["self"])),
                ]
            )
        return qm.Filter(
            must=[
                qm.FieldCondition(key="scope", match=qm.MatchValue(value=principal)),
            ]
        )
