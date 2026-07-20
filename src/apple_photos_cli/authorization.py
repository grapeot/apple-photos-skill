from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TextIO

from apple_photos_cli import CLI_MAJOR, SCHEMA_VERSION
from apple_photos_cli.canonical import canonical_json_bytes
from apple_photos_cli.errors import EXIT_AUTH, ApplePhotosError
from apple_photos_cli.manifests import atomic_write_json, format_time, parse_time


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, TypeError) as exc:
        raise ApplePhotosError(
            "E_AUTH_INVALID", "Authorization token encoding is invalid.", EXIT_AUTH
        ) from exc


class AuthorizationService:
    def __init__(
        self,
        state_dir: Path,
        *,
        now: Callable[[], datetime] | None = None,
        random_bytes: Callable[[int], bytes] = secrets.token_bytes,
        ttl: timedelta = timedelta(minutes=15),
    ) -> None:
        self.state_dir = state_dir
        self.now = now or (lambda: datetime.now(UTC))
        self.random_bytes = random_bytes
        self.ttl = ttl

    @property
    def secret_path(self) -> Path:
        return self.state_dir / "authorization-secret"

    def _secret(self) -> bytes:
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            existing = self.secret_path.read_bytes()
        except FileNotFoundError:
            value = self.random_bytes(32)
            try:
                descriptor = os.open(self.secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                return self._secret()
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
            return value
        if len(existing) != 32:
            raise ApplePhotosError(
                "E_AUTH_INVALID", "Local authorization secret has an invalid length.", EXIT_AUTH
            )
        os.chmod(self.secret_path, 0o600)
        return existing

    @staticmethod
    def required_phrase(manifest: Mapping[str, Any]) -> str:
        digest_prefix = str(manifest["manifest_sha256"]).removeprefix("sha256:")[:12]
        return f"DELETE {len(manifest['items'])} {digest_prefix}"

    def issue(
        self,
        manifest: Mapping[str, Any],
        *,
        stdin: TextIO,
        stderr: TextIO,
        output: Path,
    ) -> dict[str, Any]:
        if not stdin.isatty() or not stderr.isatty():
            raise ApplePhotosError(
                "E_AUTH_REQUIRED",
                "Delete authorization requires interactive stdin and stderr TTYs.",
                EXIT_AUTH,
            )
        phrase = self.required_phrase(manifest)
        stderr.write(
            "This will move assets to Recently Deleted and may sync across devices.\n"
            f"Library snapshot: {manifest['library_snapshot_digest']}\n"
            f"Item count: {len(manifest['items'])}\n"
            f"Type exactly: {phrase}\n> "
        )
        stderr.flush()
        if stdin.readline().rstrip("\r\n") != phrase:
            raise ApplePhotosError(
                "E_AUTH_REQUIRED", "Authorization phrase did not match.", EXIT_AUTH
            )
        issued_at = self.now().astimezone(UTC)
        claims = {
            "schema_version": SCHEMA_VERSION,
            "action": "delete_assets",
            "manifest_sha256": manifest["manifest_sha256"],
            "library_snapshot_digest": manifest["library_snapshot_digest"],
            "item_count": len(manifest["items"]),
            "issued_at": format_time(issued_at),
            "expires_at": format_time(issued_at + self.ttl),
            "nonce": self.random_bytes(32).hex(),
            "cli_major": CLI_MAJOR,
        }
        signature = hmac.new(self._secret(), canonical_json_bytes(claims), hashlib.sha256).digest()
        token = {"claims": claims, "signature": _b64encode(signature)}
        atomic_write_json(output, token, mode=0o600)
        os.chmod(output, 0o600)
        return token

    def verify(self, token: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any]:
        try:
            claims = token["claims"]
            signature = _b64decode(token["signature"])
        except (KeyError, TypeError) as exc:
            raise ApplePhotosError(
                "E_AUTH_INVALID", "Authorization token is malformed.", EXIT_AUTH
            ) from exc
        if not isinstance(claims, dict):
            raise ApplePhotosError(
                "E_AUTH_INVALID", "Authorization claims are malformed.", EXIT_AUTH
            )
        expected_signature = hmac.new(
            self._secret(), canonical_json_bytes(claims), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(signature, expected_signature):
            raise ApplePhotosError(
                "E_AUTH_INVALID", "Authorization signature is invalid.", EXIT_AUTH
            )
        expected = {
            "action": "delete_assets",
            "manifest_sha256": manifest["manifest_sha256"],
            "library_snapshot_digest": manifest["library_snapshot_digest"],
            "item_count": len(manifest["items"]),
            "cli_major": CLI_MAJOR,
        }
        for key, value in expected.items():
            if claims.get(key) != value:
                raise ApplePhotosError(
                    "E_AUTH_INVALID",
                    f"Authorization claim does not match the plan: {key}.",
                    EXIT_AUTH,
                )
        if parse_time(claims["expires_at"]) <= self.now().astimezone(UTC):
            raise ApplePhotosError("E_AUTH_EXPIRED", "Authorization token has expired.", EXIT_AUTH)
        return claims


def load_token(path: Path) -> dict[str, Any]:
    try:
        token = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApplePhotosError(
            "E_AUTH_INVALID", f"Cannot read authorization token: {path}", EXIT_AUTH
        ) from exc
    if not isinstance(token, dict):
        raise ApplePhotosError(
            "E_AUTH_INVALID", "Authorization token root must be an object.", EXIT_AUTH
        )
    return token
