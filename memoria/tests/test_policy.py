import pytest

from apps.api.services.pipeline import heuristic_gatekeeper, heuristic_policy


def test_pin_never_no_store_text():
    gk = heuristic_gatekeeper("My debit PIN is 4419")
    assert gk["tier"] == "never"
    assert gk["store_text"] == ""
    pol = heuristic_policy(gk, {"mode": "normal", "active_scope": ["self"], "off_record": False}, "My debit PIN is 4419")
    assert pol["action"] == "discard"
    assert pol["store_text"] == ""


def test_health_is_personal_not_never():
    gk = heuristic_gatekeeper("My knee flared after stairs")
    assert gk["tier"] == "personal"
    assert gk["kind"] == "health"
    pol = heuristic_policy(gk, {"mode": "normal", "active_scope": ["self"], "off_record": False}, gk["store_text"])
    assert pol["action"] == "write"
    assert pol["tier"] == "personal"
