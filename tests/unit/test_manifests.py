import json
from pathlib import Path

import pytest

from apple_photos_cli.errors import ApplePhotosError
from apple_photos_cli.manifests import load_manifest


def test_manifest_tamper_is_rejected(app, fake_bridge, tmp_path: Path) -> None:
    fake_bridge.add_asset("asset-delete", b"bytes")
    path = tmp_path / "delete.json"
    app.plan_delete(["asset-delete"], output=path)
    value = json.loads(path.read_text())
    value["items"][0]["local_identifier"] = "different-id"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ApplePhotosError) as captured:
        load_manifest(path, expected_type="apple_photos_delete")

    assert captured.value.code == "E_MANIFEST_TAMPERED"


def test_manifest_type_is_enforced(app, fake_bridge, tmp_path: Path) -> None:
    fake_bridge.add_asset("asset-delete", b"bytes")
    path = tmp_path / "delete.json"
    app.plan_delete(["asset-delete"], output=path)

    with pytest.raises(ApplePhotosError) as captured:
        load_manifest(path, expected_type="apple_photos_import")

    assert captured.value.code == "E_SCHEMA_INVALID"
