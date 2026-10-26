"""Tests for ephemeral session authentication and FastAPI bearer validation."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api.dependencies import get_authenticated_session, get_session_manager
from security.sessions import InvalidSessionToken, SessionManager


class FakeClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 26, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value


def test_session_creation_and_resolution() -> None:
    manager = SessionManager(clock=FakeClock())
    created = manager.create_session()

    assert created.token
    assert created.session.session_id != created.token
    assert manager.resolve(created.token) == created.session


def test_tokens_are_unique_and_not_predictable_from_session_ids() -> None:
    manager = SessionManager()
    first = manager.create_session()
    second = manager.create_session()

    assert first.token != second.token
    assert first.session.session_id != second.session.session_id
    assert first.token != first.session.session_id


def test_concurrent_session_creation_is_safe() -> None:
    manager = SessionManager()
    with ThreadPoolExecutor(max_workers=8) as executor:
        sessions = list(executor.map(lambda _: manager.create_session(), range(32)))

    assert len({created.session.session_id for created in sessions}) == 32
    assert len({created.token for created in sessions}) == 32
    for created in sessions:
        assert manager.resolve(created.token) == created.session


@pytest.mark.parametrize("token", ["", "not-a-real-token", "x" * 513, None])
def test_unknown_and_malformed_tokens_are_rejected(token: str | None) -> None:
    manager = SessionManager()
    with pytest.raises(InvalidSessionToken):
        manager.resolve(token)  # type: ignore[arg-type]


def test_expiration_and_cleanup_use_controlled_clock() -> None:
    clock = FakeClock()
    manager = SessionManager(lifetime_seconds=60, clock=clock)
    created = manager.create_session()

    clock.value += timedelta(seconds=60)
    with pytest.raises(InvalidSessionToken):
        manager.resolve(created.token)
    assert manager.cleanup_expired() == 0


def test_revocation_is_immediate_and_does_not_affect_other_sessions() -> None:
    manager = SessionManager()
    first = manager.create_session()
    second = manager.create_session()

    assert manager.revoke(first.session.session_id) is True
    with pytest.raises(InvalidSessionToken):
        manager.resolve(first.token)
    assert manager.resolve(second.token) == second.session
    assert manager.revoke("missing") is False


def test_expired_sessions_are_removed() -> None:
    clock = FakeClock()
    manager = SessionManager(lifetime_seconds=1, clock=clock)
    manager.create_session()
    clock.value += timedelta(seconds=1)

    assert manager.cleanup_expired() == 1


def test_authentication_dependency_returns_session_and_hides_credentials() -> None:
    manager = SessionManager()
    created = manager.create_session()
    app = FastAPI()
    app.state.session_manager = manager

    @app.get("/protected")
    def protected(session=Depends(get_authenticated_session)):
        return {"session_id": session.session_id}

    with TestClient(app) as client:
        valid = client.get(
            "/protected",
            headers={"Authorization": f"Bearer {created.token}"},
        )
        missing = client.get("/protected")
        invalid = client.get(
            "/protected",
            headers={"Authorization": "Bearer invalid-token"},
        )

    assert valid.status_code == 200
    assert valid.json() == {"session_id": created.session.session_id}
    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert invalid.status_code == 401
    assert invalid.json()["detail"] == "Invalid authentication credentials"
    assert created.token not in invalid.text


def test_tokens_are_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    manager = SessionManager()
    created = manager.create_session()

    with caplog.at_level(logging.DEBUG):
        manager.resolve(created.token)

    assert created.token not in caplog.text