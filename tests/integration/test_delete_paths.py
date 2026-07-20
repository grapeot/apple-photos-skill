from __future__ import annotations

import io
from pathlib import Path

import pytest
from conftest import FIXED_TIME

from apple_photos_cli.authorization import AuthorizationService, load_token
from apple_photos_cli.errors import EXIT_PARTIAL, ApplePhotosError
from apple_photos_cli.manifests import atomic_write_json, seal_manifest
from apple_photos_cli.state import ReplayStore


class TTY(io.StringIO):
    def isatty(self) -> bool:
        return True


def _authorize(app, manifest, tmp_path: Path):
    service = AuthorizationService(
        app.state_dir,
        now=lambda: FIXED_TIME,
        random_bytes=lambda length: b"u" * length,
    )
    path = tmp_path / "delete.token"
    service.issue(
        manifest,
        stdin=TTY(service.required_phrase(manifest) + "\n"),
        stderr=TTY(),
        output=path,
    )
    return service, path


def test_delete_plan_authorize_apply_and_replay_rejection(app, fake_bridge, tmp_path: Path) -> None:
    fake_bridge.add_asset("delete-id", b"delete")
    manifest_path = tmp_path / "delete.json"
    manifest = app.plan_delete(["delete-id"], output=manifest_path)

    assert "delete-assets" not in fake_bridge.calls
    service, token_path = _authorize(app, manifest, tmp_path)
    replay = ReplayStore(app.state_dir)
    result = app.apply_delete(manifest_path, token_path, service, replay)

    assert result.ok
    assert result.items[0]["status"] == "deleted_confirmed"
    assert replay.is_consumed(load_token(token_path)["claims"]["nonce"])

    with pytest.raises(ApplePhotosError) as captured:
        app.apply_delete(manifest_path, token_path, service, replay)
    assert captured.value.code == "E_AUTH_REPLAY"


def test_delete_precondition_drift_aborts_before_consuming_token(
    app, fake_bridge, tmp_path: Path
) -> None:
    fake_bridge.add_asset("delete-id", b"delete")
    manifest_path = tmp_path / "delete.json"
    manifest = app.plan_delete(["delete-id"], output=manifest_path)
    service, token_path = _authorize(app, manifest, tmp_path)
    token = load_token(token_path)
    fake_bridge.assets["delete-id"]["original_filename"] = "changed.jpg"
    replay = ReplayStore(app.state_dir)

    with pytest.raises(ApplePhotosError) as captured:
        app.apply_delete(manifest_path, token_path, service, replay)

    assert captured.value.code == "E_PLAN_STALE"
    assert not replay.is_consumed(token["claims"]["nonce"])
    assert "delete-assets" not in fake_bridge.calls


def test_unknown_delete_postcondition_is_not_success(app, fake_bridge, tmp_path: Path) -> None:
    fake_bridge.add_asset("delete-id", b"delete")
    fake_bridge.force_unknown_delete = True
    manifest_path = tmp_path / "delete.json"
    manifest = app.plan_delete(["delete-id"], output=manifest_path)
    service, token_path = _authorize(app, manifest, tmp_path)

    result = app.apply_delete(
        manifest_path,
        token_path,
        service,
        ReplayStore(app.state_dir),
    )

    assert not result.ok
    assert result.status == "outcome_unknown"
    assert result.items[0]["status"] == "outcome_unknown"


def test_equal_count_asset_set_drift_rejects_before_nonce(app, fake_bridge, tmp_path: Path) -> None:
    for identifier in ("a", "b", "c", "d"):
        fake_bridge.add_asset(identifier, identifier.encode())
    manifest_path = tmp_path / "delete.json"
    manifest = app.plan_delete(["d"], output=manifest_path)
    service, token_path = _authorize(app, manifest, tmp_path)
    token = load_token(token_path)
    del fake_bridge.assets["c"]
    fake_bridge.resources.pop("c")
    fake_bridge.add_asset("e", b"e")
    replay = ReplayStore(app.state_dir)

    with pytest.raises(ApplePhotosError) as captured:
        app.apply_delete(manifest_path, token_path, service, replay)

    assert captured.value.code == "E_LIBRARY_SNAPSHOT_MISMATCH"
    assert not replay.is_consumed(token["claims"]["nonce"])


def test_locked_delete_revalidation_precedes_nonce(
    app, fake_bridge, tmp_path: Path, monkeypatch
) -> None:
    fake_bridge.add_asset("delete-id", b"delete")
    manifest_path = tmp_path / "delete.json"
    manifest = app.plan_delete(["delete-id"], output=manifest_path)
    service, token_path = _authorize(app, manifest, tmp_path)
    token = load_token(token_path)
    replay = ReplayStore(app.state_dir)
    original = fake_bridge.fetch_assets
    calls = 0

    def fetch(identifiers=None):
        nonlocal calls
        calls += 1
        result = original(identifiers)
        if calls == 1:
            fake_bridge.assets["delete-id"]["original_filename"] = "changed-after-fetch.jpg"
        return result

    monkeypatch.setattr(fake_bridge, "fetch_assets", fetch)
    with pytest.raises(ApplePhotosError) as captured:
        app.apply_delete(manifest_path, token_path, service, replay)

    assert captured.value.code == "E_PLAN_STALE"
    assert not replay.is_consumed(token["claims"]["nonce"])
    assert "delete-assets" not in fake_bridge.calls


def test_unknown_delete_consumes_nonce_and_writes_receipt(
    app, fake_bridge, tmp_path: Path, monkeypatch
) -> None:
    fake_bridge.add_asset("delete-id", b"delete")
    manifest_path = tmp_path / "delete.json"
    manifest = app.plan_delete(["delete-id"], output=manifest_path)
    service, token_path = _authorize(app, manifest, tmp_path)
    token = load_token(token_path)
    replay = ReplayStore(app.state_dir)

    def fail(items):
        assert replay.is_consumed(token["claims"]["nonce"])
        raise ApplePhotosError("E_OUTCOME_UNKNOWN", "Synthetic timeout.", EXIT_PARTIAL)

    monkeypatch.setattr(fake_bridge, "delete_assets", fail)
    result = app.apply_delete(manifest_path, token_path, service, replay)

    assert result.status == "outcome_unknown"
    assert app.status(result.run_id) == result.to_dict()
    assert replay.is_consumed(token["claims"]["nonce"])


def test_resealed_post_authorization_change_rejects_old_token(
    app, fake_bridge, tmp_path: Path
) -> None:
    fake_bridge.add_asset("delete-id", b"delete")
    manifest_path = tmp_path / "delete.json"
    manifest = app.plan_delete(["delete-id"], output=manifest_path)
    service, token_path = _authorize(app, manifest, tmp_path)
    token = load_token(token_path)
    changed = dict(manifest)
    changed["items"] = [dict(manifest["items"][0])]
    changed["items"][0]["expected"] = dict(changed["items"][0]["expected"])
    changed["items"][0]["expected"]["original_filename"] = "attacker-change.jpg"
    changed = seal_manifest(changed)
    atomic_write_json(manifest_path, changed)
    replay = ReplayStore(app.state_dir)

    with pytest.raises(ApplePhotosError) as captured:
        app.apply_delete(manifest_path, token_path, service, replay)

    assert captured.value.code == "E_AUTH_INVALID"
    assert not replay.is_consumed(token["claims"]["nonce"])
    assert "delete-assets" not in fake_bridge.calls


def test_delete_interrupt_after_dispatch_becomes_terminal_unknown(
    app, fake_bridge, tmp_path: Path, monkeypatch
) -> None:
    fake_bridge.add_asset("delete-id", b"delete")
    manifest_path = tmp_path / "delete.json"
    manifest = app.plan_delete(["delete-id"], output=manifest_path)
    service, token_path = _authorize(app, manifest, tmp_path)
    token = load_token(token_path)
    replay = ReplayStore(app.state_dir)

    def interrupt(items):
        assert replay.is_consumed(token["claims"]["nonce"])
        raise KeyboardInterrupt

    monkeypatch.setattr(fake_bridge, "delete_assets", interrupt)
    result = app.apply_delete(manifest_path, token_path, service, replay)

    assert result.status == "outcome_unknown"
    assert result.errors[0]["exception_type"] == "KeyboardInterrupt"
    assert app.status(result.run_id)["status"] == "outcome_unknown"
