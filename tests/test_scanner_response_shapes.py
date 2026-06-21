"""Soft-failure tests for unexpected Esri response shapes (issue #77).

These cover three parsing bugs that previously aborted the scan or silently
corrupted the artifact:

1. A non-numeric Esri error ``code`` raised an uncaught ``ValueError`` from
   ``admin_usage._interpret`` (called outside the scanner try/except).
2. ``admin_rbac._server_users`` indexed ``roles[0]`` without a list type-guard,
   so a comma-delimited ``roles`` string yielded the first *character*.
3. ``agol._modified_timestamp`` only handled ``int``, zeroing a real ``modified``
   epoch delivered as a JSON float.
"""

from __future__ import annotations

from honua_esri_assess.diagnostics import Diagnostic
from honua_esri_assess.entitlements.http import HttpResponse
from honua_esri_assess.scanners import admin_rbac
from honua_esri_assess.scanners.admin_usage import _coerce_error_code, _interpret
from honua_esri_assess.scanners.agol import _modified_timestamp


# --- Issue #77.1: non-numeric error code must not raise -------------------


def test_coerce_error_code_accepts_int_and_numeric_string() -> None:
    assert _coerce_error_code(403) == 403
    assert _coerce_error_code("403") == 403
    assert _coerce_error_code(403.0) == 403


def test_coerce_error_code_degrades_on_non_numeric() -> None:
    # The previous ``int(...)`` raised ValueError on any of these.
    assert _coerce_error_code("Token Required") == 0
    assert _coerce_error_code(None) == 0
    assert _coerce_error_code(True) == 0
    assert _coerce_error_code({"nested": "object"}) == 0


def test_interpret_does_not_raise_on_non_numeric_error_code() -> None:
    diagnostics: list[Diagnostic] = []
    response = HttpResponse(
        status_code=200,
        body={"error": {"code": "NOT_A_NUMBER", "message": "boom"}},
    )

    # Must degrade to a diagnostic path (return None) rather than aborting.
    result = _interpret(response, scope="usage", diagnostics=diagnostics)

    assert result is None


# --- Issue #77.2: roles as a string must not be char-indexed --------------


def test_server_users_handles_roles_as_string() -> None:
    payload = {
        "users": [
            {"username": "alice", "roles": "administrator,editor"},
        ]
    }

    users = admin_rbac._server_users(payload)

    assert len(users) == 1
    # Previously ``roles[0]`` -> "a" (first character). Now the first role.
    assert users[0].role_id == "administrator"


def test_server_users_handles_roles_as_list() -> None:
    payload = {"users": [{"username": "bob", "roles": ["publisher", "viewer"]}]}

    users = admin_rbac._server_users(payload)

    assert users[0].role_id == "publisher"


def test_server_users_defaults_when_roles_missing_or_empty() -> None:
    payload = {
        "users": [
            {"username": "carol"},
            {"username": "dave", "roles": []},
            {"username": "erin", "roles": ""},
        ]
    }

    users = admin_rbac._server_users(payload)

    assert [u.role_id for u in users] == ["user", "user", "user"]


# --- Issue #77.3: float epoch must not be zeroed --------------------------


def test_modified_timestamp_accepts_float_epoch() -> None:
    # 1700000000000 ms == 2023-11-14T22:13:20Z
    assert _modified_timestamp(1700000000000.0) == "2023-11-14T22:13:20Z"
    assert _modified_timestamp(1700000000000) == "2023-11-14T22:13:20Z"


def test_modified_timestamp_rejects_bool_and_unknown() -> None:
    # bool is an int subclass; must not be treated as an epoch.
    assert _modified_timestamp(True) == "1970-01-01T00:00:00Z"
    assert _modified_timestamp(None) == "1970-01-01T00:00:00Z"


def test_modified_timestamp_passes_through_iso_string() -> None:
    assert _modified_timestamp("2024-01-02T03:04:05Z") == "2024-01-02T03:04:05Z"
