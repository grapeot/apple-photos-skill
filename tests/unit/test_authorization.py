from __future__ import annotations

import io
from datetime import timedelta
from pathlib import Path

import pytest
from conftest import FIXED_TIME

from apple_photos_cli.authorization import AuthorizationService, load_token
from apple_photos_cli.errors import ApplePhotosError
from apple_photos_cli.state import ReplayStore


class TTYBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


def _delete_manifest(app, fake_bridge, tmp_path: Path):
    fake_bridge.add_asset("delete-me", b"asset")
    return app.plan_delete(["delete-me"], output=tmp_path / "delete.json")


def test_authorization_requires_exact_tty_phrase(app, fake_bridge, tmp_path: Path) -> None:
    manifest = _delete_manifest(app, fake_bridge, tmp_path)
    service = AuthorizationService(
        app.state_dir,
        now=lambda: FIXED_TIME,
        random_bytes=lambda length: b"r" * length,
    )
    phrase = service.required_phrase(manifest)
    token_path = tmp_path / "delete.token"

    token = service.issue(
        manifest,
        stdin=TTYBuffer(phrase + "\n"),
        stderr=TTYBuffer(),
        output=token_path,
    )

    assert token_path.stat().st_mode & 0o777 == 0o600
    assert service.verify(load_token(token_path), manifest) == token["claims"]
    assert phrase.startswith("DELETE 1 ")


def test_authorization_prompt_includes_ai_agent_guard(app, fake_bridge, tmp_path: Path) -> None:
    manifest = _delete_manifest(app, fake_bridge, tmp_path)
    service = AuthorizationService(
        app.state_dir,
        now=lambda: FIXED_TIME,
        random_bytes=lambda length: b"r" * length,
    )
    stderr = TTYBuffer()
    service.issue(
        manifest,
        stdin=TTYBuffer(service.required_phrase(manifest) + "\n"),
        stderr=stderr,
        output=tmp_path / "token",
    )
    prompt = stderr.getvalue()
    assert "AI AGENT GUARD" in prompt
    assert "MUST NOT" in prompt
    assert "explicit human authorization" in prompt
    assert "question tool" in prompt


def test_authorization_rejects_non_tty(app, fake_bridge, tmp_path: Path) -> None:
    manifest = _delete_manifest(app, fake_bridge, tmp_path)
    service = AuthorizationService(app.state_dir, now=lambda: FIXED_TIME)

    with pytest.raises(ApplePhotosError) as captured:
        service.issue(
            manifest,
            stdin=io.StringIO("anything\n"),
            stderr=io.StringIO(),
            output=tmp_path / "token",
        )

    assert captured.value.code == "E_AUTH_REQUIRED"


def test_authorization_rejects_wrong_manifest_and_expiry(app, fake_bridge, tmp_path: Path) -> None:
    manifest = _delete_manifest(app, fake_bridge, tmp_path)
    issuer = AuthorizationService(
        app.state_dir,
        now=lambda: FIXED_TIME,
        random_bytes=lambda length: b"s" * length,
    )
    token_path = tmp_path / "delete.token"
    issuer.issue(
        manifest,
        stdin=TTYBuffer(issuer.required_phrase(manifest) + "\n"),
        stderr=TTYBuffer(),
        output=token_path,
    )
    token = load_token(token_path)
    changed = dict(manifest)
    changed["manifest_sha256"] = "sha256:" + "0" * 64

    with pytest.raises(ApplePhotosError) as wrong:
        issuer.verify(token, changed)
    assert wrong.value.code == "E_AUTH_INVALID"

    expired = AuthorizationService(app.state_dir, now=lambda: FIXED_TIME + timedelta(minutes=16))
    with pytest.raises(ApplePhotosError) as expiry:
        expired.verify(token, manifest)
    assert expiry.value.code == "E_AUTH_EXPIRED"


def test_replay_store_consumes_nonce_once(tmp_path: Path) -> None:
    store = ReplayStore(tmp_path)
    store.consume("nonce", "sha256:" + "a" * 64, "2030-01-02T03:04:05Z")

    assert store.is_consumed("nonce")
    with pytest.raises(ApplePhotosError) as captured:
        store.consume("nonce", "sha256:" + "a" * 64, "2030-01-02T03:04:06Z")
    assert captured.value.code == "E_AUTH_REPLAY"
