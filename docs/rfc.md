# Architecture RFC

## System Architecture and Trust Domains

The architecture isolates operations across three boundaries:
1. **Read-Only Adapter**: Pinned `osxphotos==0.76.1` normalization. Performs read-only queries against selected libraries, with zero SQLite write or mutation capacity.
2. **Swift Helper Process**: A compiled native binary performing PhotoKit mutations against the System Photo Library via `PHPhotoLibrary.shared()`. AppleScript or GUI automation is prohibited.
3. **Python Orchestrator**: CLI argument parsing, asset/album filtering, deterministic manifest generation, HMAC-SHA-256 deletion authorization, advisory locking, and JSON/JSONL formatting.

## Core Safety Invariants

- **SQLite Writes**: Prohibited.
- **Library Snapshots**: Manifests bind to the sorted PhotoKit asset-ID-set digest. This detects content-set drift; it does not verify physical library identity.
- **Deduplication**: Requires complete SHA-256 resource equality. Timestamps, names, sizes, or metadata fingerprints are insufficient.
- **Execution Freeze**: Resolves operations using identifiers frozen in the manifest; search/filter routines are never rerun at execution time.
- **Deletions**: Require interactive TTY confirmation and a single-use HMAC token.
- **Preconditions**: Precondition failures abort the batch before calling native helper mutations.
- **Postconditions**: Unverifiable post-mutation states report as `partial` or `outcome_unknown` and return non-zero exit codes.
- **Import Transaction Isolation**: Payloads are validated as a batch. Execution uses ordered per-item PhotoKit transactions and stops at the first unknown outcome. Earlier successful identifiers remain available; every remaining item receives `not_attempted_after_unknown` evidence without invoking another PhotoKit transaction.

## Component Specifications

### OsxphotosReader
Lazily instantiates the adapter, maps `PhotoInfo` to `AssetRecord` entities, and exposes normalized metadata.

### PhotoKitProcessBridge
Spawns the native helper without a shell and communicates through JSON on stdin/stdout. Successful responses may include stderr diagnostics without invalidating the protocol result. Protocol errors and timeouts raise structured exceptions; non-zero exits attach truncated stderr to the structured error detail.

### Application Orchestration
Coordinates components using dependency injection. Integrates fakes for the reader and process bridge to run unit and integration tests offline.

## Cryptographic Manifests and Safety Gates

### Canonical Manifests
Uses UTF-8, sorted keys, compact separators, and no non-finite numbers. The `manifest_sha256` field is the lowercase hex digest of the manifest object with that field omitted.
- **Import Manifest**: Records source paths, album IDs, snapshots, UTIs, and resource SHA-256 hashes. Apply step rejects symlinks, non-regular files, or size mismatches.
- **Library Snapshot**: Contains sorted local-identifier digests, item counts, and diagnostic sentinels. Exposes no filesystem path or physical ID; `physical_identity_verified` remains false.
- **Delete Manifest**: Freezes target local identifiers and metadata. The apply step validates live metadata against these targets prior to helper execution.

### Delete Authorization Tokens
A local 32-byte HMAC secret (mode `0600` in the CLI state directory) signs a canonical payload containing: manifest digest, snapshot digest, count, timestamp, nonce, and CLI major version.
Applying requires interactive confirmation of `DELETE <count> <digest-prefix>` and consumes the token nonce in a local SQLite ledger before helper execution.

## State and Locking

Locks bind to the library snapshot digest in `APPLE_PHOTOS_STATE_DIR` (defaulting to the OS Application Support path). State files must never sit inside a `.photoslibrary` bundle. Locking coordinates this CLI only; delete operations repeat target validation inside their PhotoKit transaction.

Prior to dispatching helper mutations, the orchestrator writes a `commit_pending` journal. It logs `commit_reported` upon helper response and a receipt post-verification. Import responses preserve ordered terminal evidence: `created_identifier_known`, the first `outcome_unknown`, and `not_attempted_after_unknown` for every remaining item. The orchestrator journals these statuses immediately, propagates uncertainty to batch duplicates, and performs no later album or verification mutations. Dispatch exceptions log an `outcome_unknown` receipt; callers must reconcile read-only and must not auto-retry.

## Metadata Backup Architecture

Metadata backups construct snapshots in temporary directories. Data files are streamed, flushed, fsynced, and hashed before the manifest is written. The backup directory is then atomically renamed and tagged with a `COMPLETE` marker.

## Failure Semantics and Exit Codes

The CLI maps failures to these exit codes:
- `2`: Usage/Schema Error
- `3`: Unsupported Capability
- `4`: Permission/Authorization Failure
- `5`: Stale Plan/Conflict
- `6`: Dependency/Read Failure
- `7`: Local Protocol/Bridge Error
- `8`: Partial/Integrity/Unknown Outcome
- `9`: Backend Transaction Failure
- `10`: Lock Contention
