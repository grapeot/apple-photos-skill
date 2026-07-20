# Product Requirements

## Product

`apple-photos` is a live-unverified alpha establishing a structured, safety-gated interface for Apple Photos metadata reads and System Photo Library mutations. This schema definition is not a claim of production readiness; mutating production libraries is prohibited until live validation on a disposable library completes.

## User Capabilities

- Inspect assets and albums via structured outputs.
- Lexically search, list, and filter normalized metadata.
- Export streaming metadata dumps and checksummed metadata backups.
- Retrieve original asset resources verified by SHA-256.
- Compare frozen local image pairs with deterministic pixel-error metrics for read-only review evidence. Similarity reports must be cryptographically bound to their input manifest and must never authorize deletion.
- Plan and apply single-resource imports with exact duplicate checks.
- Plan, authorize, and execute deletions (moving items to Recently Deleted).

## Functional Requirements

- **Runtime**: Python 3.11+ using standard `argparse`.
- **Read Adapter**: Pinned `osxphotos==0.76.1` for read-only metadata queries.
- **Output**: JSON and JSONL to stdout; diagnostic logs strictly to stderr.
- **Backup**: Atomic metadata backups containing per-file SHA-256 checksums and a terminal `COMPLETE` sentinel.
- **Swift Helper Bridge**: Versioned JSON protocol over stdin/stdout for System Photo Library mutations (probe, albums, fetch, resources, import, album mapping, delete, and validation checks).
- **Immutability**: Deterministic JSON manifest canonicalization.
- **Mutation Safety**:
  - All mutation commands default to dry-run planning.
  - Applying mutations requires a frozen manifest and `--apply`.
  - Deletes require interactive TTY phrase confirmation (`DELETE <count> <digest-prefix>`) and a short-lived manifest-bound HMAC token.
  - Delete tokens expire in 15 minutes; the token nonce is consumed in a local SQLite ledger before native helper execution.
  - Revalidate the sorted PhotoKit asset-ID-set digest (snapshot) and preconditions before mutations. Snapshot equality does not prove physical library identity.

## Success Criteria

- All offline unit, contract, and integration tests pass without active Photos or helper access.
- Rejection of modified manifests, expired/replayed tokens, or mismatched snapshots prior to native helper execution.
- Mandatory SHA-256 equality for duplicate detection.
- Every batch item returns terminal evidence. Import creation stops at the first unknown per-item transaction, preserves earlier successful identifiers, and marks every remaining item `not_attempted_after_unknown`; `partial` or `outcome_unknown` statuses return a non-zero exit code and block automatic retries.
- Zero code paths write to the Photos SQLite database.
- Complete exclusion of personal identifiers, media paths, or metadata from git-tracked files.

## Non-Goals

- Writing, repairing, or mutating the Photos SQLite database.
- Interacting with or targeting non-System Photo Libraries.
- Automating or bypassing macOS TCC/PhotoKit delete confirmation prompts.
- Permanent deletion or emptying Recently Deleted.
- Using perceptual or pixel similarity as exact-duplicate proof or deletion authorization.
- Importing compound resources (Live Photos, RAW+JPEG, bursts, edited pairs, Shared Albums).
- Restoring metadata backups to Apple Photos.
- Replacing system backup solutions.
