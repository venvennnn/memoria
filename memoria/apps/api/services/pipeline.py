from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from qdrant_client.http import models as qm

from apps.api.agents.schemas import (
    ForgetterOutput,
    GatekeeperOutput,
    LibrarianOutput,
    PolicyOutput,
    RegistrarOutput,
)
from apps.api.services import session_acl
from apps.api.services.embeddings import EmbeddingService
from apps.api.services.lyzr_client import LyzrClient
from apps.api.services.qdrant_store import QdrantStore
from apps.api.settings import Settings

SECRET_PATTERNS = [
    re.compile(r"\b(pin|password|otp|aadhaar|ssn|account number|debit card)\b", re.I),
    re.compile(r"\b\d{4,6}\b"),
]
HEALTH_PATTERNS = re.compile(r"\b(knee|health|symptom|medication|doctor|pain|flare)\b", re.I)
COMMITMENT_PATTERNS = re.compile(
    r"\b(send|owe|asked me to|mark .+ done|i owe|they owe)\b", re.I
)

_event_log: list[dict[str, Any]] = []
MAX_EVENTS = 200


def push_event(code: str, detail: str = "", meta: dict[str, Any] | None = None) -> None:
    _event_log.append(
        {
            "ts": QdrantStore.now_iso(),
            "code": code,
            "detail": detail,
            "meta": meta or {},
        }
    )
    if len(_event_log) > MAX_EVENTS:
        del _event_log[0 : len(_event_log) - MAX_EVENTS]


def get_events() -> list[dict[str, Any]]:
    return list(reversed(_event_log))


def clear_events() -> None:
    _event_log.clear()


def heuristic_gatekeeper(text: str) -> dict[str, Any]:
    lower = text.lower()
    tier = "knowledge"
    kind: str = "fact"
    confidence = 0.85
    store_text = text.strip()
    direction = None
    who = None
    what = None

    if any(p.search(text) for p in SECRET_PATTERNS) and re.search(r"\d{4}", text):
        if "pin" in lower or "password" in lower or "otp" in lower or "aadhaar" in lower:
            return GatekeeperOutput(
                tier="never",
                confidence=0.95,
                kind="secret",
                topics=["credential"],
                rationale="credential detected",
                store_text="",
            ).model_dump()

    if HEALTH_PATTERNS.search(text):
        kind = "health"
        tier = "personal"
        confidence = 0.88

    if COMMITMENT_PATTERNS.search(text):
        kind = "commitment"
        m = re.search(r"send\s+(\w+)\s+(.+?)(?:\s+tonight|\s+—|$)", text, re.I)
        if m:
            who, what = m.group(1).lower(), m.group(2).strip(" .")
            direction = "i_owe"
        m2 = re.search(r"(\w+)\s+asked me to\s+(.+)", text, re.I)
        if m2:
            who, what = m2.group(1).lower(), m2.group(2).strip()
            direction = "i_owe"

    if re.match(r"^(uh+h?|yeah|ok)\.?$", lower):
        kind = "chit_chat"
        confidence = 0.2
        tier = "ephemeral"

    topics: list[str] = []
    if kind == "health":
        topics = ["health"]
    if "burma burma" in lower or "restaurant" in lower:
        kind = "fact"
        tier = "knowledge"
        topics = ["restaurant", "weekend"]

    people: list[str] = []
    for name in ("priya", "rohan", "arjun", "dev", "ananya"):
        if name in lower:
            people.append(name)

    return GatekeeperOutput(
        tier=tier,
        confidence=confidence,
        kind=kind,
        people=people,
        topics=topics,
        direction=direction,
        who=who,
        what=what,
        rationale="heuristic classification",
        store_text=store_text if tier != "never" else "",
    ).model_dump()


def heuristic_policy(gk: dict[str, Any], acl: dict[str, Any], raw_text: str) -> dict[str, Any]:
    if gk.get("tier") == "never" or (gk.get("confidence", 0) >= 0.8 and gk.get("tier") == "never"):
        return PolicyOutput(
            action="discard",
            tier="never",
            scope=list(acl.get("active_scope") or ["self"]),
            store_text="",
            receipt={
                "action": "discard",
                "reason": "inferred_never",
                "topic_bucket": "credential",
            },
        ).model_dump()

    if acl.get("off_record"):
        return PolicyOutput(
            action="discard",
            tier=gk.get("tier", "personal"),
            scope=["self"],
            store_text="",
            receipt={
                "action": "discard",
                "reason": "spoken_off_record",
                "topic_bucket": "other",
            },
        ).model_dump()

    scope = list(acl.get("active_scope") or ["self"])
    tier = acl.get("tier_override") or gk.get("tier", "knowledge")
    if tier == "never":
        return PolicyOutput(
            action="discard",
            tier="never",
            scope=scope,
            store_text="",
            receipt={"action": "discard", "reason": "inferred_never", "topic_bucket": "other"},
        ).model_dump()

    conf = float(gk.get("confidence") or 0.5)
    kind = gk.get("kind")
    store_text = gk.get("store_text") or raw_text

    if conf < 0.4:
        return PolicyOutput(action="discard", tier=tier, scope=scope, store_text="").model_dump()

    if 0.4 <= conf < 0.8 and kind in ("secret", "health") or acl.get("off_record"):
        return PolicyOutput(
            action="quarantine",
            tier=tier,
            scope=scope,
            store_text=store_text,
            receipt={"action": "quarantine", "reason": "low_confidence", "topic_bucket": "health"},
        ).model_dump()

    ttl = None
    if tier == "ephemeral":
        ttl = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
    if acl.get("ttl_override_hours"):
        ttl = (datetime.now(timezone.utc) + timedelta(hours=acl["ttl_override_hours"])).isoformat()

    create_commitment = gk.get("kind") == "commitment" and bool(gk.get("who") and gk.get("what"))

    return PolicyOutput(
        action="write",
        tier=tier,
        scope=scope,
        ttl_expires_at=ttl,
        store_text=store_text,
        create_commitment=create_commitment,
    ).model_dump()


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        store: QdrantStore,
        embeddings: EmbeddingService,
        lyzr: LyzrClient,
    ) -> None:
        self.settings = settings
        self.store = store
        self.embeddings = embeddings
        self.lyzr = lyzr

    def route(self, text: str) -> str:
        lower = text.lower().strip()
        if re.search(r"\bwhat are you allowed|what can the roommate|what did you refuse", lower):
            return "inspect"
        if re.search(r"\bforget\b", lower):
            return "forget"
        if re.search(r"\bwhat do i owe\b", lower) or lower.startswith("where did") or "?" in text:
            if re.search(r"\b(mark .+ done|mark the)\b", lower):
                return "settle"
            if "?" in text or lower.startswith(("where", "what", "who")):
                return "query"
        if re.search(r"\bmark .+ done\b", lower):
            return "settle"
        if re.search(
            r"\b(this is private|that's private|off the record|don't store|don't remember|"
            r"share with .+ only|work can see|work memory|personal-only|back to normal|"
            r"you can remember the decision)\b",
            lower,
        ):
            return "acl"
        if re.search(r"\bi owe\b|\basked me to\b", lower) and "?" not in text:
            return "content"
        return "content"

    async def run_gatekeeper(
        self, uid: str, session_id: str, text: str, speaker: str, is_user: bool, acl: dict
    ) -> dict[str, Any]:
        payload = {
            "text": text,
            "speaker": speaker,
            "is_user": is_user,
            "session_acl": acl,
        }
        result = await self.lyzr.infer_json("gatekeeper", uid, session_id, payload)
        if result:
            merged = heuristic_gatekeeper(text)
            merged.update({k: v for k, v in result.items() if v is not None})
            if merged.get("tier") == "never":
                merged["store_text"] = ""
            return merged
        return heuristic_gatekeeper(text)

    async def run_policy(self, gk: dict, acl: dict, raw_text: str) -> dict[str, Any]:
        payload = {"gatekeeper": gk, "session_acl": acl, "raw_text": raw_text}
        result = await self.lyzr.infer_json("policy", "system", "policy", payload)
        base = heuristic_policy(gk, acl, raw_text)
        if result:
            base.update({k: v for k, v in result.items() if v is not None})
        if gk.get("tier") == "never":
            base["action"] = "discard"
            base["tier"] = "never"
            base["store_text"] = ""
        if acl.get("off_record"):
            base["action"] = "discard"
            base["store_text"] = ""
        return base

    def apply_acl_phrase(self, uid: str, session_id: str, text: str) -> dict[str, Any]:
        lower = text.lower()
        acl = session_acl.get_session_acl(uid, session_id)
        receipt_preview = "acl update"

        if "off the record" in lower or "don't store" in lower or "don't remember" in lower:
            acl = session_acl.update_session_acl(uid, session_id, {"off_record": True, "mode": "off_record"})
            receipt_preview = "spoken off the record"
        elif "that's private" in lower or "this is private" in lower:
            acl = session_acl.update_session_acl(
                uid, session_id, {"tier_override": "personal", "mode": "personal_only"}
            )
            receipt_preview = "spoken private tier"
        elif "work can see" in lower or "work memory" in lower:
            scopes = list(set(acl.get("active_scope", ["self"]) + ["circle:work"]))
            acl = session_acl.update_session_acl(uid, session_id, {"active_scope": scopes, "mode": "work"})
            receipt_preview = "work scope enabled"
        elif "share with" in lower:
            m = re.search(r"share with\s+(\w+)\s+only", lower)
            if m:
                person = m.group(1).lower()
                acl = session_acl.update_session_acl(
                    uid,
                    session_id,
                    {"active_scope": ["self", f"person:{person}"], "mode": "shared"},
                )
                receipt_preview = f"share with {person}"
        elif "personal-only" in lower or "personal only" in lower:
            acl = session_acl.update_session_acl(
                uid, session_id, {"active_scope": ["self"], "mode": "personal_only", "tier_override": "personal"}
            )
        elif "back to normal" in lower:
            acl = session_acl.update_session_acl(
                uid,
                session_id,
                {
                    "mode": "normal",
                    "active_scope": ["self"],
                    "tier_override": None,
                    "off_record": False,
                },
            )
            receipt_preview = "acl reset"

        rid = self.store.new_id("rcpt")
        self.store.upsert(
            "receipts",
            rid,
            self.embeddings.embed(receipt_preview),
            {
                "uid": uid,
                "ts": self.store.now_iso(),
                "action": "share" if "share" in receipt_preview else "refuse_store",
                "reason": "spoken_acl",
                "topic_bucket": "other",
                "count_points_affected": 0,
                "preview": receipt_preview,
                "actor": "session_acl",
            },
        )
        push_event("RECEIPT", receipt_preview)
        return acl

    @staticmethod
    def split_compound(text: str) -> list[str]:
        parts = re.split(r"\.\s+(?=[A-Z])|;\s+| — ", text)
        cleaned = [p.strip().strip(".") for p in parts if p.strip()]
        return cleaned or [text.strip()]

    async def process_utterance(
        self,
        uid: str,
        session_id: str,
        text: str,
        speaker: str = "USER",
        is_user: bool = True,
        principal: str = "self",
    ) -> dict[str, Any]:
        text = text.strip()
        if not text:
            return {"ok": True, "skipped": True}

        segments = self.split_compound(text) if len(text) > 80 else [text]
        if len(segments) > 1:
            results = []
            for seg in segments:
                results.append(
                    await self._process_utterance_once(
                        uid, session_id, seg, speaker, is_user, principal
                    )
                )
            return {"ok": True, "results": results}
        return await self._process_utterance_once(
            uid, session_id, text, speaker, is_user, principal
        )

    async def _process_utterance_once(
        self,
        uid: str,
        session_id: str,
        text: str,
        speaker: str = "USER",
        is_user: bool = True,
        principal: str = "self",
    ) -> dict[str, Any]:
        route = self.route(text)
        acl = session_acl.get_session_acl(uid, session_id)
        trace: dict[str, Any] = {"route": route, "text_preview": text[:80]}

        if route == "acl":
            self.apply_acl_phrase(uid, session_id, text)
            await self._trace(uid, "acl", trace, ok=True)
            return {"ok": True, "route": "acl"}

        if route == "forget":
            result = await self.run_forget(uid, session_id, text)
            await self._trace(uid, "forgetter", {**trace, **result}, ok=result.get("post", 1) == 0)
            return result

        if route == "inspect":
            ans = await self.run_inspect(uid, session_id, text, principal)
            await self._trace(uid, "librarian", trace, ok=True)
            return ans

        if route == "query":
            ans = await self.run_query(uid, session_id, text, principal)
            await self._trace(uid, "librarian", {**trace, **ans}, ok=bool(ans.get("point_ids") or ans.get("refused")))
            return ans

        if route == "settle":
            return await self.run_settle(uid, text)

        lower = text.lower()
        if "off the record" in lower:
            session_acl.update_session_acl(uid, session_id, {"off_record": True, "mode": "off_record"})
            acl = session_acl.get_session_acl(uid, session_id)
        if "that's private" in lower or "that is private" in lower:
            session_acl.update_session_acl(
                uid, session_id, {"tier_override": "personal", "mode": "personal_only"}
            )
            acl = session_acl.get_session_acl(uid, session_id)
        if "work can see" in lower or "work memory" in lower:
            scopes = list(set(acl.get("active_scope", ["self"]) + ["circle:work"]))
            session_acl.update_session_acl(uid, session_id, {"active_scope": scopes, "mode": "work"})
            acl = session_acl.get_session_acl(uid, session_id)

        return await self.process_content(uid, session_id, text, speaker, is_user, acl, trace)

    async def process_content(
        self,
        uid: str,
        session_id: str,
        text: str,
        speaker: str,
        is_user: bool,
        acl: dict,
        trace: dict,
    ) -> dict[str, Any]:
        gk = await self.run_gatekeeper(uid, session_id, text, speaker, is_user, acl)
        push_event("GATE", f"{gk.get('tier')} {gk.get('confidence', 0):.2f}")

        pol = await self.run_policy(gk, acl, text)
        action = pol.get("action", "discard")
        conf = float(gk.get("confidence") or 0)

        if conf >= 0.8 and gk.get("tier") == "never":
            action = "discard"
            pol["action"] = "discard"
            pol["store_text"] = ""

        if conf >= 0.8 and gk.get("tier") != "never" and action != "discard":
            action = pol.get("action", "write")

        if 0.4 <= conf < 0.8 and gk.get("kind") in ("secret", "health"):
            action = "quarantine"
            pol["action"] = "quarantine"

        if conf < 0.4:
            push_event("DROP", "noise")
            await self._trace(uid, "gatekeeper", trace, ok=True)
            return {"ok": True, "dropped": True}

        if action == "discard":
            receipt = pol.get("receipt") or {}
            self._write_receipt(uid, receipt, pol, gk)
            push_event("RECEIPT", receipt.get("reason", "discard"))
            await self._trace(uid, "policy", trace, ok=True)
            return {"ok": True, "discarded": True}

        store_text = pol.get("store_text") or ""
        if not store_text and action != "quarantine":
            await self._trace(uid, "policy", trace, ok=True)
            return {"ok": True, "empty": True}

        scope = pol.get("scope") or acl.get("active_scope") or ["self"]
        if "work can see" in text.lower() and "circle:work" not in scope:
            scope = list(set(scope + ["circle:work"]))

        tier = pol.get("tier") or gk.get("tier") or "knowledge"
        status = "quarantine" if action == "quarantine" else "active"
        point_id = self.store.new_id("mem")
        payload = {
            "uid": uid,
            "text": store_text,
            "tier": tier,
            "scope": scope,
            "session_id": session_id,
            "ts": self.store.now_iso(),
            "speaker": speaker.lower(),
            "is_user": is_user,
            "people": gk.get("people") or [],
            "topics": gk.get("topics") or [],
            "kind": gk.get("kind") or "fact",
            "status": status,
            "ttl_expires_at": pol.get("ttl_expires_at"),
            "consent_span": text[:120],
            "gate_confidence": conf,
            "acl_source": "spoken" if acl.get("mode") != "normal" else "inferred",
            "source": "omi_transcript",
        }
        self.store.upsert("memories", point_id, self.embeddings.embed(store_text), payload)
        push_event("WRITE", f"{tier} {point_id}")

        if pol.get("create_commitment") or gk.get("kind") == "commitment":
            await self._register_commitment(uid, session_id, gk, pol, scope, point_id, text)

        await self._trace(uid, "gatekeeper", {**trace, "point_ids": [point_id]}, ok=True)
        return {"ok": True, "memory_id": point_id, "action": action}

    async def _register_commitment(
        self, uid, session_id, gk, pol, scope, memory_id, raw_text
    ) -> None:
        reg_payload = {"gatekeeper": gk, "text": raw_text, "scope": scope}
        reg = await self.lyzr.infer_json("registrar", uid, session_id, reg_payload)
        if not reg.get("who"):
            reg = RegistrarOutput(
                text=gk.get("store_text") or raw_text,
                direction=(gk.get("direction") or "i_owe"),
                who=gk.get("who") or "",
                what=gk.get("what") or "",
                people=gk.get("people") or [],
                topics=gk.get("topics") or [],
            ).model_dump()

        cid = self.store.new_id("cmt")
        cpayload = {
            "uid": uid,
            "text": reg.get("text") or raw_text,
            "direction": reg.get("direction") or "i_owe",
            "who": reg.get("who") or gk.get("who"),
            "what": reg.get("what") or gk.get("what"),
            "due_at": reg.get("due_at"),
            "status": "open",
            "tier": pol.get("tier") or "knowledge",
            "scope": scope,
            "people": reg.get("people") or gk.get("people") or [],
            "topics": reg.get("topics") or gk.get("topics") or [],
            "memory_id": memory_id,
            "ts": self.store.now_iso(),
        }
        self.store.upsert("commitments", cid, self.embeddings.embed(cpayload["text"]), cpayload)
        push_event("WRITE", f"commitment {cid}")

    def _write_receipt(self, uid: str, receipt: dict, pol: dict, gk: dict) -> None:
        rid = self.store.new_id("rcpt")
        reason = (receipt.get("reason") if isinstance(receipt, dict) else None) or "inferred_never"
        bucket = (receipt.get("topic_bucket") if isinstance(receipt, dict) else None) or "other"
        preview = f"redacted 1 item at {datetime.now().strftime('%H:%M')}"
        self.store.upsert(
            "receipts",
            rid,
            self.embeddings.embed(preview),
            {
                "uid": uid,
                "ts": self.store.now_iso(),
                "action": (receipt.get("action") if isinstance(receipt, dict) else None) or "discard",
                "reason": reason,
                "tier_would_have_been": pol.get("tier") or gk.get("tier"),
                "topic_bucket": bucket,
                "count_points_affected": 1,
                "preview": preview,
                "actor": "gatekeeper",
            },
        )

    async def run_forget(self, uid: str, session_id: str, text: str) -> dict[str, Any]:
        payload = {"uid": uid, "text": text}
        spec = await self.lyzr.infer_json("forgetter", uid, session_id, payload)
        if not spec.get("must"):
            spec = self._heuristic_forget(uid, text)
        fo = ForgetterOutput.model_validate(spec)

        pre_total = 0
        deleted_total = 0
        post_total = 0
        collections = [c for c in fo.collections if c != "receipts"]

        for coll in collections:
            flt = self.store.build_filter(uid, [m for m in fo.must if m.get("key") != "uid"])
            pre = self.store.count(coll, flt)
            deleted = self.store.delete(coll, flt)
            post = self.store.count(coll, flt)
            pre_total += pre
            deleted_total += deleted
            post_total += post

        rid = self.store.new_id("rcpt")
        preview = fo.preview or "forget"
        self.store.upsert(
            "receipts",
            rid,
            self.embeddings.embed(preview),
            {
                "uid": uid,
                "ts": self.store.now_iso(),
                "action": "delete",
                "reason": "spoken_acl",
                "topic_bucket": "health" if "health" in text.lower() else "other",
                "count_points_affected": deleted_total,
                "preview": preview,
                "actor": "forgetter",
            },
        )
        push_event("FORGET", f"{pre_total}→{post_total}")
        return {"ok": True, "pre": pre_total, "post": post_total, "deleted": deleted_total}

    def _heuristic_forget(self, uid: str, text: str) -> dict[str, Any]:
        must = [{"key": "uid", "match": uid}]
        if "health" in text.lower():
            must.append({"key": "topics", "match_any": ["health"]})
        if "afternoon" in text.lower():
            pass
        return ForgetterOutput(
            collections=["memories", "commitments"],
            must=must,
            preview="forget health memories" if "health" in text.lower() else "forget",
        ).model_dump()

    async def run_query(self, uid: str, session_id: str, question: str, principal: str) -> dict[str, Any]:
        q = question.lower()
        if "owe" in q:
            flt = qm.Filter(
                must=[
                    qm.FieldCondition(key="uid", match=qm.MatchValue(value=uid)),
                    qm.FieldCondition(key="status", match=qm.MatchValue(value="open")),
                    self.store.principal_scope_match(principal).must[0],
                ]
            )
            commits = self.store.scroll("commitments", flt, limit=20)
            if commits:
                parts = [
                    f"{c['payload'].get('who')}: {c['payload'].get('what') or c['payload'].get('text')}"
                    for c in commits
                ]
                return LibrarianOutput(
                    answer="Open commitments: " + "; ".join(parts),
                    point_ids=[c["id"] for c in commits],
                    principal=principal,
                ).model_dump()

        memories = self._scoped_memories(uid, principal)
        receipts = self._recent_receipts(uid)
        if self._receipt_blocks_topic(question, receipts):
            return {
                "answer": "You asked me not to remember that.",
                "point_ids": [],
                "used_receipts": [r["id"] for r in receipts[:3]],
                "principal": principal,
                "refused": True,
            }

        payload = {"principal": principal, "question": question, "points": memories, "receipts": receipts}
        result = await self.lyzr.infer_json("librarian", uid, session_id, payload)
        lib = LibrarianOutput.model_validate({**{"answer": "", "point_ids": []}, **result})

        if not lib.point_ids:
            lib = self._heuristic_librarian(question, memories, principal)

        if lib.point_ids and not self._validate_citations(lib.point_ids, memories):
            return {
                "answer": "I cannot claim that without a citation.",
                "point_ids": [],
                "principal": principal,
                "refused": True,
            }

        if not lib.point_ids and not memories:
            lib.answer = "I have no memory I'm allowed to use for that."

        return lib.model_dump()

    async def run_inspect(self, uid: str, session_id: str, text: str, principal: str) -> dict[str, Any]:
        lower = text.lower()
        if "refuse" in lower:
            receipts = self._recent_receipts(uid)
            lines = [r["payload"].get("preview", "") for r in receipts[:5]]
            return {"answer": "; ".join(lines) or "Nothing refused yet.", "point_ids": []}
        mems = self._scoped_memories(uid, principal)
        scopes = sorted({s for m in mems for s in m.get("payload", {}).get("scope", [])})
        return {
            "answer": f"Visible scopes for {principal}: {', '.join(scopes) or 'none'}.",
            "point_ids": [m["id"] for m in mems[:5]],
            "principal": principal,
        }

    def _heuristic_librarian(self, question: str, memories: list, principal: str) -> LibrarianOutput:
        q = question.lower()
        for m in memories:
            p = m["payload"]
            text = (p.get("text") or "").lower()
            if "priya" in q or "eat" in q or "restaurant" in q:
                if "burma" in text or "priya" in text:
                    return LibrarianOutput(
                        answer=f"Priya recommended {p.get('text')}.",
                        point_ids=[m["id"]],
                        principal=principal,
                    )
            if "knee" in q or "health" in q:
                if p.get("kind") == "health" or "knee" in text:
                    return LibrarianOutput(
                        answer=p.get("text", ""),
                        point_ids=[m["id"]],
                        principal=principal,
                    )
            if "owe" in q:
                continue
        return LibrarianOutput(
            answer="I have no memory I'm allowed to use for that.",
            point_ids=[],
            principal=principal,
        )

    def _validate_citations(self, point_ids: list[str], memories: list) -> bool:
        valid = {m["id"] for m in memories}
        return all(pid in valid for pid in point_ids)

    def _receipt_blocks_topic(self, question: str, receipts: list) -> bool:
        q = question.lower()
        if "knee" in q or "health" in q:
            for r in receipts:
                pl = r.get("payload", {})
                if pl.get("action") == "delete" and pl.get("topic_bucket") == "health":
                    return True
                if pl.get("reason") == "spoken_acl" and "health" in (pl.get("preview") or "").lower():
                    return True
        return False

    def _scoped_memories(self, uid: str, principal: str) -> list[dict]:
        flt = qm.Filter(
            must=[
                qm.FieldCondition(key="uid", match=qm.MatchValue(value=uid)),
                qm.FieldCondition(key="status", match=qm.MatchValue(value="active")),
                self.store.principal_scope_match(principal).must[0],
            ]
        )
        return self.store.scroll("memories", flt, limit=50)

    def _recent_receipts(self, uid: str) -> list[dict]:
        flt = qm.Filter(must=[qm.FieldCondition(key="uid", match=qm.MatchValue(value=uid))])
        return self.store.scroll("receipts", flt, limit=20)

    async def run_settle(self, uid: str, text: str) -> dict[str, Any]:
        lower = text.lower()
        status = "done" if "done" in lower else "dropped"
        flt = qm.Filter(
            must=[
                qm.FieldCondition(key="uid", match=qm.MatchValue(value=uid)),
                qm.FieldCondition(key="status", match=qm.MatchValue(value="open")),
            ]
        )
        commits = self.store.scroll("commitments", flt, limit=20)
        updated = []
        for c in commits:
            pl = c["payload"]
            who = (pl.get("who") or "").lower()
            what = (pl.get("what") or "").lower()
            if who and who in lower:
                if "spec" in lower and "spec" in what:
                    self.store.set_payload("commitments", c["id"], {"status": status})
                    updated.append(c["id"])
                elif "spec" not in lower:
                    self.store.set_payload("commitments", c["id"], {"status": status})
                    updated.append(c["id"])
        push_event("SETTLE", status)
        return {"ok": True, "updated": updated, "status": status}

    async def _trace(self, uid: str, agent: str, data: dict, ok: bool) -> None:
        tid = self.store.new_id("tr")
        self.store.upsert(
            "traces",
            tid,
            self.embeddings.embed(str(data)[:200]),
            {
                "uid": uid,
                "agent": agent,
                "ts": self.store.now_iso(),
                "ok": ok,
                "detail": data,
            },
        )

    def search_memories(self, uid: str, principal: str, query: str, limit: int = 8) -> list[dict]:
        flt = qm.Filter(
            must=[
                qm.FieldCondition(key="uid", match=qm.MatchValue(value=uid)),
                qm.FieldCondition(key="status", match=qm.MatchValue(value="active")),
                self.store.principal_scope_match(principal).must[0],
            ]
        )
        vec = self.embeddings.embed(query)
        return self.store.search("memories", vec, flt, limit=limit)

    def sweep_ttl(self) -> int:
        now = datetime.now(timezone.utc).isoformat()
        flt = qm.Filter(
            must=[
                qm.FieldCondition(
                    key="ttl_expires_at",
                    range=qm.DatetimeRange(lt=now),
                )
            ]
        )
        count = self.store.delete("memories", flt)
        if count:
            rid = self.store.new_id("rcpt")
            self.store.upsert(
                "receipts",
                rid,
                self.embeddings.embed("ttl sweep"),
                {
                    "uid": "system",
                    "ts": self.store.now_iso(),
                    "action": "delete",
                    "reason": "ttl",
                    "count_points_affected": count,
                    "preview": f"ttl sweep {count}",
                    "actor": "sweeper",
                },
            )
        return count
