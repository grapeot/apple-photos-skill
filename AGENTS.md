# Apple Photos Skill

## Project Role

Provides a safety-oriented Python CLI and agent skill to inspect Apple Photos metadata and plan PhotoKit mutations. Database writes, GUI automation, visual deduplication, and media backups are unsupported.

## Non-Negotiable Safety Rules

- **Database Safety**: Never write, migrate, repair, vacuum, or mutate Photos SQLite databases. Keep `osxphotos==0.76.1` read-only; never suggest `osxphotos import`.
- **Target Seam**: Limit mutations to the native Swift PhotoKit helper targeting the System Photo Library only.
- **Dry-run Default**: Imports and deletions default to planning; applying requires a frozen manifest and `--apply`.
- **Delete Authorization**: Deletions require interactive TTY confirmation and a short-lived, single-use, manifest-bound HMAC token.
- **Delete Execution**: Assets move to Recently Deleted only. Never empty Recently Deleted or bypass macOS confirmation prompts.
- **Duplicate Verification**: Enforce full SHA-256 resource equality. Filenames, sizes, visual matches, or database fingerprints do not prove duplicate status.
- **Failure Handling**: Fail closed if resource coverage, library snapshots, or conditions cannot be verified. Do not claim public PhotoKit proves physical library identity.
- **Testing**: Default to synthetic fixtures. Run live mutation tests only on explicit request using a disposable library.

## Project Structure

- [README.md](README.md): Installation and usage guide.
- [docs/prd.md](docs/prd.md): Requirements and success criteria.
- [docs/rfc.md](docs/rfc.md): Architecture and safety protocols.
- [docs/test.md](docs/test.md): Test strategy and gates.
- [docs/working.md](docs/working.md): Verification notes.
- [skills/apple_photos.md](skills/apple_photos.md): Canonical agent skill.
- [src/apple_photos_cli/](src/apple_photos_cli/): CLI and Python package source.
- [schemas/](schemas/): JSON schemas.
- [native/PhotoKitHelper/](native/PhotoKitHelper/): Swift helper source.
- [tests/](tests/): Synthetic tests.

## Environment and Maintenance

- **Runtime**: Target Python 3.11+ using `.venv` (`source .venv/bin/activate`).
- **Dependencies**: Install via `uv pip install -e '.[dev,photos]'`. Do not use bare `pip`.
- **Language**: English only for code, docs, CLI help, tests, and fixtures.
- **Privacy**: Exclude real names, paths, album names, IDs, hashes, emails, domains, or operational history. Use synthetic examples only.
- **Git**: Exclude local state, active library databases, media, `.env` files, tokens, and logs. Do not commit or push without explicit user request.
- **Documentation**: Sync README, RFC, schemas, skill docs, and CLI help. Record verification logs in [docs/working.md](docs/working.md).
