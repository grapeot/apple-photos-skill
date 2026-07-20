from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path
from types import TracebackType

from apple_photos_cli.errors import EXIT_AUTH, EXIT_LOCKED, ApplePhotosError, usage_error


def default_state_dir() -> Path:
    configured = os.environ.get("APPLE_PHOTOS_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "Library" / "Application Support" / "apple-photos-skill"


def ensure_state_dir(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if any(part.lower().endswith(".photoslibrary") for part in resolved.parts):
        raise usage_error("Application state must not be stored inside a .photoslibrary bundle.")
    resolved.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(resolved, 0o700)
    return resolved


class ReplayStore:
    def __init__(self, state_dir: Path) -> None:
        self.path = state_dir / "authorization-replay.sqlite3"

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        os.chmod(self.path, 0o600)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS consumed_nonce ("
            "nonce TEXT PRIMARY KEY, manifest_sha256 TEXT NOT NULL, consumed_at TEXT NOT NULL)"
        )
        return connection

    def is_consumed(self, nonce: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM consumed_nonce WHERE nonce = ?", (nonce,)
            ).fetchone()
        return row is not None

    def consume(self, nonce: str, manifest_sha256: str, consumed_at: str) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO consumed_nonce "
                    "(nonce, manifest_sha256, consumed_at) VALUES (?, ?, ?)",
                    (nonce, manifest_sha256, consumed_at),
                )
        except sqlite3.IntegrityError as exc:
            raise ApplePhotosError(
                "E_AUTH_REPLAY", "Authorization token was already consumed.", EXIT_AUTH
            ) from exc


class LibraryLock:
    def __init__(self, state_dir: Path, library_digest: str) -> None:
        safe_name = hashlib.sha256(library_digest.encode()).hexdigest()
        self.path = state_dir / "locks" / f"{safe_name}.lock"
        self.handle: object | None = None

    def __enter__(self) -> LibraryLock:
        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise ApplePhotosError(
                "E_LOCKED", "Another mutation is active for this library.", EXIT_LOCKED
            ) from exc
        self.handle = handle
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.handle is not None:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)  # type: ignore[union-attr]
            self.handle.close()  # type: ignore[union-attr]
            self.handle = None
