# Verification Notes

This file records reproducible local checks. Live PhotoKit validation has not been performed.

## 2026-07-20

- **Infrastructure**: Normalization via read-only `osxphotos==0.76.1` and native PhotoKit process bridge are operational.
- **Namespaces & State**: Isolated osxphotos and PhotoKit identifier namespaces, sorted asset-ID-set snapshots, strict manifests, metadata preconditions, fail-fast per-item transaction evidence, and durable receipts are implemented.
- **Verification**: Verified `ruff check .`, 123 synthetic Python tests, and 11 offline Swift tests. Import tests prove that a missing creation placeholder or transaction error prevents later PhotoKit transaction calls, preserves earlier identifiers, emits `not_attempted_after_unknown` for remaining items, and persists those terminal statuses before returning. No test accesses real Photos libraries.
- **Library Tracking**: Public PhotoKit does not expose System Photo Library paths or physical identity. Snapshot equivalence does not prove physical library identity.
- **Packaging**: Verified wheel/sdist builds and isolated Python 3.12 wheel installation. The wheel packages schemas, the skill, documentation, and Swift helper source. The `apple-photos helper-source` command successfully locates helper source and emits structured `build_argv` arrays for compiling.
- **Security Gates**: Verified the AST SQL scanner blocks dynamic SQL, `executescript` with `DELETE` or `VACUUM`, unrecognized SQLite execution APIs, and statements outside the replay-ledger allowlist. Publication privacy scans passed.
