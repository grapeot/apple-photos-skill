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
- **AI Agent Authorization Guard**: The `delete authorize` prompt prints an explicit instruction telling AI agents to STOP and obtain the most recent and explicit human authorization via a question tool or conversation before entering the confirmation phrase. AI agents must not pipe or PTY-inject the phrase without first receiving a clear, explicit, and current human confirmation. This guard is printed on every authorize prompt and must not be suppressed or skipped.
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
- **Pixel Evidence**: Use `evidence compare-images` for read-only comparison of frozen local image pairs. Passing thresholds are advisory only; the report always sets `delete_authorizing` to `false` and cannot replace complete resource-set SHA-256 equality.

### Mutations
- **Planning**: Generates side-effect-free plans for review.
- **Imports**: Limited to single-resource images and videos only; compound assets fail closed.
- **Import Uncertainty**: Uses ordered per-item PhotoKit transactions. Stop at the first unknown outcome, preserve earlier identifiers, record every remaining item as `not_attempted_after_unknown`, reconcile read-only, and never auto-retry.
- **Deletions**: Require interactive confirmation inputs and one-time authorization tokens. Piping confirmation, PTY-injecting the phrase, or reusing tokens is prohibited. AI agents must stop at the authorization prompt and obtain explicit human confirmation before proceeding.

## Known Limitations and Failure Modes

- This is a live-unverified alpha. Mutation criteria describe the target contract, not validated production readiness.
- Execution permissions are separate from Python filesystem access. The native helper separately requires macOS Photos permissions.
- Target snapshot validation fails closed if Photos access is denied or the sorted local-identifier set digest drifts from the plan. Public PhotoKit cannot prove physical library identity.
- iCloud-only assets block import planning if resource checksums cannot be retrieved under network-deny policies.
- Album titles can conflict; planning binds strictly to local identifier hashes.
- Multiple exact duplicate matches block execution rather than resolving arbitrarily.
- Concurrency shifts by external apps bypass advisory locks; live pre- and post-conditions remain mandatory.
- Helper transaction failures after dispatch report per-item evidence as `partial` or `outcome_unknown`. Receipts preserve earlier known identifiers, distinguish later `not_attempted_after_unknown` items, and must be reconciled read-only.
- **Batch delete timeout**: Large batch deletes (hundreds or thousands of assets) may cause the PhotoKit helper to time out after dispatching mutations. The CLI reports `outcome_unknown` for all items, but some or all assets may have actually been moved to Recently Deleted. Always reconcile with a fresh read after `outcome_unknown`; never assume the operation failed or succeeded based solely on the helper response.
- **PhotoKit permission**: If `doctor --capability mutation` reports `E_PERMISSION_PHOTOS` (status=2), the PhotoKit helper process has not been granted Photos access by macOS TCC. On non-GUI processes, macOS may not prompt automatically. Resetting Photos TCC state with `tccutil reset Photos` may trigger a fresh authorization dialog on the next PhotoKit call, but this is not guaranteed if denial is caused by process identity, code signing, or configuration. Consult macOS System Settings > Privacy & Security > Photos if the dialog does not appear.
- **Identifier mapping**: osxphotos UUIDs and PhotoKit local identifiers are separate namespaces. Use `asset mutation-list` to retrieve authoritative PhotoKit local identifiers for mutation. In some Photos library versions, the PhotoKit local identifier may share the same base UUID as the osxphotos UUID with a resource suffix appended (e.g., `/L0/001`), but this format is not guaranteed across all library versions or asset types. Always verify any constructed identifier exists in live PhotoKit output before using it in a deletion manifest.
- **date_taken contamination**: Imports from tools like `photos-import` may write the import timestamp into `date_taken` instead of the original capture time. osxphotos reports the contaminated value, while PhotoKit may report the correct UTC time. Do not use `date_taken` as identity evidence for duplicate detection or deletion candidate selection.

## Reporting

Include manifest digest, library snapshot, artifact paths, status counts, and non-terminal or unknown items. Do not summarize `partial`, `blocked`, or `outcome_unknown` as successes. Exclude raw token values, HMAC secrets, or private metadata.
