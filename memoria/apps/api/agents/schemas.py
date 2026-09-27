from typing import Any, Literal

from pydantic import BaseModel, Field

Tier = Literal["never", "ephemeral", "personal", "knowledge"]
Kind = Literal[
    "secret",
    "health",
    "commitment",
    "decision",
    "preference",
    "fact",
    "chit_chat",
    "acl",
    "other",
]
RouteKind = Literal["content", "acl", "query", "forget", "inspect", "settle"]
CommitmentDirection = Literal["i_owe", "they_owe", "we_agreed"]
CommitmentStatus = Literal["open", "done", "dropped", "expired"]


class GatekeeperOutput(BaseModel):
    tier: Tier = "knowledge"
    confidence: float = 0.5
    kind: Kind = "other"
    people: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    entities_to_strip: list[str] = Field(default_factory=list)
    direction: str | None = None
    who: str | None = None
    what: str | None = None
    due_hint: str | None = None
    rationale: str = ""
    store_text: str = ""


class PolicyReceipt(BaseModel):
    action: str | None = None
    reason: str | None = None
    topic_bucket: str | None = None


class PolicyOutput(BaseModel):
    action: Literal["write", "discard", "quarantine", "rewrite"] = "discard"
    tier: Tier = "knowledge"
    scope: list[str] = Field(default_factory=lambda: ["self"])
    ttl_expires_at: str | None = None
    store_text: str = ""
    create_commitment: bool = False
    receipt: PolicyReceipt | None = None


class LibrarianOutput(BaseModel):
    answer: str = ""
    point_ids: list[str] = Field(default_factory=list)
    used_receipts: list[str] = Field(default_factory=list)
    principal: str = "self"


class ForgetterOutput(BaseModel):
    collections: list[str] = Field(default_factory=lambda: ["memories"])
    must: list[dict[str, Any]] = Field(default_factory=list)
    time_from: str | None = None
    time_to: str | None = None
    preview: str = ""


class RegistrarOutput(BaseModel):
    text: str = ""
    direction: CommitmentDirection = "i_owe"
    who: str = ""
    what: str = ""
    due_at: str | None = None
    people: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)


class UtteranceInput(BaseModel):
    uid: str
    session_id: str
    text: str
    speaker: str = "USER"
    is_user: bool = True
    principal: str = "self"


class MemorySearchRequest(BaseModel):
    uid: str
    principal: str = "self"
    query: str
    limit: int = 8


class SetStatusRequest(BaseModel):
    id: str
    status: CommitmentStatus


class DevUtteranceRequest(UtteranceInput):
    pass
