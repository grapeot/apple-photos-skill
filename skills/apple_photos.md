---
name: apple-photos
description: >-
  Live-unverified alpha for Apple Photos inspection and gated PhotoKit mutations. Never use mutation commands on a production library.
disable-model-invocation: true
---

# Apple Photos Skill

> **Live-unverified alpha:** Real PhotoKit import and delete actions are unvalidated against real System Photo Libraries. Do not run mutation commands on production libraries. Offline tests use synthetic fixtures.

## Goal

Use `apple-photos` for read-only inspection. Mutation operations are restricted to explicitly approved disposable test libraries.

## Hard Boundaries

- **Databases**: Never write, patch, migrate, repair, vacuum, or query Photos SQLite outside the read-only `osxphotos` adapter.
- **Mutations**: Limit mutations to the native Swift PhotoKit helper targeting the System Photo Library (`PHPhotoLibrary.shared()`). AppleScript, `osxphotos import`, and GUI automation are prohibited.
- **Library Context**: Active or System Photo Library targets must not be switched.
- **Deduplication**: Enforce complete SHA-256 resource equality. Filenames, sizes, visual matches, or metadata fingerprints do not prove duplicate status.
- **Manifests**: Execution requires deterministic JSON integrity-checksummed frozen manifests.
- **Deletions**: Move assets to Recently Deleted only (no permanent erasure). Require interactive TTY confirmation phrase and a short-lived, single-use, manifest-bound HMAC token. Never bypass macOS delete confirmation prompts.
- **Error Handling**: Treat `partial` or `outcome_unknown` states as transaction failures. Reconcile read-only; never auto-retry.

## Acceptance Criteria

A task is complete only when all criteria hold:
- Executed operations match the reviewed library snapshot digest. Snapshot equivalence does not prove physical library identity.
- Every target asset returns a terminal status; non-terminal outcomes fail execution.
- Imports create/reuse assets only after SHA-256 resource verification, confirming bytes and album memberships post-apply.
- Deletions execute against frozen local IDs after verifying live metadata preconditions.
- Deletion tokens match action, manifest, snapshot, count, expiry, nonce, and CLI major version; the nonce is consumed before helper execution.
- Outputs conform to single JSON objects or JSONL streams starting with `run_start` and ending with `run_end`.
- Metadata backups include per-file SHA-256 checksums and a terminal `COMPLETE` sentinel.
- Reports detail success, blocked, partial, and unknown outcomes with artifact paths.

## Resource Map

- **Discovery**: `apple-photos --help` or `apple-photos doctor --capability read|mutation|all`
- **Contracts**: Schemas in checkout `schemas/` or installed wheel `apple_photos_cli/schemas/`.
- **Docs & Tests**: Checkout `docs/` or installed wheel `apple_photos_cli/bundled/docs/`.
- **Native Helper Source**: Locate via `apple-photos helper-source --format path`.
- **State Path**: Managed in `APPLE_PHOTOS_STATE_DIR`.

## Operations Guidance

### Metadata Reads
- **Lexical Search**: Search text-based metadata using `asset search`.
- **Filtering**: Apply structured JSON filters via `asset filter`. Evaluation using raw SQL or Python code is prohibited.
- **Backups**: Use `metadata dump` for stream snapshots and `metadata backup` for checksummed archives (not media files).
- **File Retrieval**: Retrieve original resources using `asset retrieve` (requires network opt-in for iCloud assets).
- **Identifier Mapping**: Discovery uses osxphotos UUIDs. Retrieve PhotoKit local identifiers using `asset mutation-list` or `album mutation-list` prior to mutation.

### Mutations
- **Planning**: Generates side-effect-free plans for review.
- **Imports**: Limited to single-resource images and videos only; compound assets fail closed.
- **Import Uncertainty**: Uses ordered per-item PhotoKit transactions. Stop at the first unknown outcome, preserve earlier identifiers, record every remaining item as `not_attempted_after_unknown`, reconcile read-only, and never auto-retry.
- **Deletions**: Require interactive confirmation inputs and one-time authorization tokens. Piping confirmation or reusing tokens is prohibited.

## Known Limitations and Failure Modes

- This is a live-unverified alpha. Mutation criteria describe the target contract, not validated production readiness.
- Execution permissions are separate from Python filesystem access. The native helper separately requires macOS Photos permissions.
- Target snapshot validation fails closed if Photos access is denied or the sorted local-identifier set digest drifts from the plan. Public PhotoKit cannot prove physical library identity.
- iCloud-only assets block import planning if resource checksums cannot be retrieved under network-deny policies.
- Album titles can conflict; planning binds strictly to local identifier hashes.
- Multiple exact duplicate matches block execution rather than resolving arbitrarily.
- Concurrency shifts by external apps bypass advisory locks; live pre- and post-conditions remain mandatory.
- Helper transaction failures after dispatch report per-item evidence as `partial` or `outcome_unknown`. Receipts preserve earlier known identifiers, distinguish later `not_attempted_after_unknown` items, and must be reconciled read-only.

## Reporting

Include manifest digest, library snapshot, artifact paths, status counts, and non-terminal or unknown items. Do not summarize `partial`, `blocked`, or `outcome_unknown` as successes. Exclude raw token values, HMAC secrets, or private metadata.
