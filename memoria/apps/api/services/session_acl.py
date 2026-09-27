from __future__ import annotations

from copy import deepcopy
from typing import Any

SessionKey = tuple[str, str]

DEFAULT_ACL: dict[str, Any] = {
    "mode": "normal",
    "active_scope": ["self"],
    "tier_override": None,
    "redact_entities": [],
    "ttl_override_hours": None,
    "off_record": False,
}

_sessions: dict[SessionKey, dict[str, Any]] = {}


def get_session_acl(uid: str, session_id: str) -> dict[str, Any]:
    key = (uid, session_id)
    if key not in _sessions:
        _sessions[key] = deepcopy(DEFAULT_ACL)
    return _sessions[key]


def update_session_acl(uid: str, session_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    acl = get_session_acl(uid, session_id)
    acl.update(updates)
    _sessions[(uid, session_id)] = acl
    return acl


def reset_sessions() -> None:
    _sessions.clear()
