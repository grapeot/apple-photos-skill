from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from apple_photos_cli.adapters.photokit_bridge import PhotoKitProcessBridge
from apple_photos_cli.errors import ApplePhotosError


def _helper(tmp_path: Path) -> Path:
    path = tmp_path / "PhotoKitHelper"
    path.write_text("synthetic", encoding="utf-8")
    return path


def test_bridge_accepts_one_versioned_response_and_stderr_noise(tmp_path: Path) -> None:
    response = {
        "protocol_version": "1.0",
        "ok": True,
        "result": {
            "albums": [
                {
                    "local_identifier": "album-id",
                    "title": "Synthetic Album",
                    "asset_count": 0,
                    "can_add_assets": True,
                }
            ]
        },
    }

    def runner(*args, **kwargs):
        request = json.loads(kwargs["input"])
        assert request["operation"] == "list-albums"
        assert kwargs["env"].keys() <= {"HOME", "PATH", "TMPDIR", "LANG", "LC_ALL"}
        return subprocess.CompletedProcess(args[0], 0, json.dumps(response) + "\n", "diagnostic\n")

    bridge = PhotoKitProcessBridge(_helper(tmp_path), runner=runner)

    assert bridge.list_albums()[0].photokit_local_identifier == "album-id"


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        ("not-json\n", "malformed JSON"),
        ('{"protocol_version":"2.0","ok":true,"result":{}}\n', "version"),
        ('{"protocol_version":"1.0","ok":true,"result":{}}\nextra\n', "exactly one"),
    ],
)
def test_bridge_rejects_malformed_contract(tmp_path: Path, stdout: str, expected: str) -> None:
    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout, "")

    bridge = PhotoKitProcessBridge(_helper(tmp_path), runner=runner)

    with pytest.raises(ApplePhotosError, match=expected):
        bridge.probe()


def test_bridge_preserves_helper_error(tmp_path: Path) -> None:
    response = {
        "protocol_version": "1.0",
        "ok": False,
        "error": {"code": "E_PERMISSION_PHOTOS", "message": "Photos access denied."},
    }

    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, json.dumps(response) + "\n", "")

    bridge = PhotoKitProcessBridge(_helper(tmp_path), runner=runner)
    with pytest.raises(ApplePhotosError) as captured:
        bridge.probe()

    assert captured.value.code == "E_PERMISSION_PHOTOS"


def test_bridge_timeout_is_protocol_error(tmp_path: Path) -> None:
    def runner(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    bridge = PhotoKitProcessBridge(_helper(tmp_path), runner=runner)
    with pytest.raises(ApplePhotosError) as captured:
        bridge.probe()

    assert captured.value.code == "E_BACKEND_PROTOCOL"


def test_mutation_timeout_is_outcome_unknown(tmp_path: Path) -> None:
    def runner(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    bridge = PhotoKitProcessBridge(_helper(tmp_path), runner=runner)
    with pytest.raises(ApplePhotosError) as captured:
        bridge.delete_assets(
            [{"local_identifier": "asset-id", "expected": {"in_trash": False}}]
        )

    assert captured.value.code == "E_OUTCOME_UNKNOWN"
    assert captured.value.exit_code == 8


@pytest.mark.parametrize(
    "stdout",
    [
        "not-json\n",
        '{"protocol_version":"2.0","ok":true,"result":{}}\n',
        '{"protocol_version":"1.0","ok":true,"result":{}}\nextra\n',
        '{"protocol_version":"1.0","ok":true}\n',
    ],
)
def test_mutation_malformed_response_is_outcome_unknown(tmp_path: Path, stdout: str) -> None:
    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout, "")

    bridge = PhotoKitProcessBridge(_helper(tmp_path), runner=runner)
    with pytest.raises(ApplePhotosError) as captured:
        bridge.delete_assets(
            [{"local_identifier": "asset-id", "expected": {"in_trash": False}}]
        )

    assert captured.value.code == "E_OUTCOME_UNKNOWN"
    assert captured.value.exit_code == 8


def test_mutation_nonzero_exit_is_outcome_unknown(tmp_path: Path) -> None:
    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 9, "", "synthetic crash")

    bridge = PhotoKitProcessBridge(_helper(tmp_path), runner=runner)
    with pytest.raises(ApplePhotosError) as captured:
        bridge.delete_assets(
            [{"local_identifier": "asset-id", "expected": {"in_trash": False}}]
        )

    assert captured.value.code == "E_OUTCOME_UNKNOWN"
    assert captured.value.exit_code == 8


def test_bridge_rejects_scalar_json_root(tmp_path: Path) -> None:
    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, "[]\n", "")

    with pytest.raises(ApplePhotosError) as captured:
        PhotoKitProcessBridge(_helper(tmp_path), runner=runner).probe()

    assert captured.value.code == "E_BACKEND_PROTOCOL"


def test_unavailable_resource_preserves_backend_diagnostic(tmp_path: Path) -> None:
    response = {
        "protocol_version": "1.0",
        "ok": True,
        "result": {
            "resources": [
                {
                    "local_identifier": "asset-id",
                    "role": "photo",
                    "uti": "image/jpeg",
                    "byte_count": 0,
                    "sha256": "",
                    "availability": "unavailable",
                    "path": None,
                    "backend_error": "Synthetic resource is offline.",
                }
            ]
        },
    }

    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, json.dumps(response) + "\n", "")

    bridge = PhotoKitProcessBridge(_helper(tmp_path), runner=runner)
    resource = bridge.read_resources(["asset-id"])[0]

    assert resource.availability == "unavailable"
    assert resource.backend_error == "Synthetic resource is offline."


def test_import_bridge_accepts_structured_partial_evidence(tmp_path: Path) -> None:
    response = {
        "protocol_version": "1.0",
        "ok": True,
        "result": {
            "status": "partial",
            "items": [
                {
                    "item_id": "src_1",
                    "local_identifier": "local-1",
                    "status": "created_identifier_known",
                    "evidence": "photokit_placeholder",
                },
                {
                    "item_id": "src_2",
                    "local_identifier": None,
                    "status": "outcome_unknown",
                    "evidence": "placeholder_missing_after_creation_registered",
                },
                {
                    "item_id": "src_3",
                    "local_identifier": None,
                    "status": "not_attempted_after_unknown",
                    "evidence": "not_attempted_after_unknown",
                },
            ],
        },
    }

    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, json.dumps(response) + "\n", "")

    result = PhotoKitProcessBridge(_helper(tmp_path), runner=runner).import_assets(
        [{"item_id": "src_1"}, {"item_id": "src_2"}, {"item_id": "src_3"}],
        "album-id",
    )

    assert result == response["result"]


@pytest.mark.parametrize(
    "result",
    [
        {"status": "succeeded", "items": []},
        {
            "status": "succeeded",
            "items": [
                {
                    "item_id": "src_1",
                    "local_identifier": None,
                    "status": "outcome_unknown",
                    "evidence": "transaction_outcome_unknown",
                }
            ],
        },
        {
            "status": "outcome_unknown",
            "items": [
                {
                    "item_id": "src_1",
                    "local_identifier": "local-1",
                    "status": "created_identifier_known",
                    "evidence": "photokit_placeholder",
                }
            ],
        },
        {
            "status": "outcome_unknown",
            "items": [
                {
                    "item_id": "src_1",
                    "local_identifier": None,
                    "status": "not_attempted_after_unknown",
                    "evidence": "not_attempted_after_unknown",
                }
            ],
        },
        {
            "status": "outcome_unknown",
            "items": [
                {
                    "item_id": "src_1",
                    "local_identifier": None,
                    "status": "outcome_unknown",
                    "evidence": "unbounded_helper_reason",
                }
            ],
        },
    ],
)
def test_import_bridge_rejects_malformed_or_contradictory_evidence(
    tmp_path: Path, result: dict
) -> None:
    response = {"protocol_version": "1.0", "ok": True, "result": result}

    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, json.dumps(response) + "\n", "")

    bridge = PhotoKitProcessBridge(_helper(tmp_path), runner=runner)
    with pytest.raises(ApplePhotosError) as captured:
        bridge.import_assets([{"item_id": "src_1"}], "album-id")

    assert captured.value.code == "E_OUTCOME_UNKNOWN"
