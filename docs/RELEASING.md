# Releasing

Releases are built only from a `v<version>` tag whose commit is reachable from
`main`. Hatch derives the package version from that tag. Add the matching
`## [<version>]` changelog entry, merge and verify CI, then create and push the
tag. The protected `release` environment should require maintainer approval and
PyPI trusted publishing; it must not store a long-lived API token.

The release workflow runs the locked suite, builds wheel and sdist once, checks
their metadata, smoke-installs both, records SHA-256 checksums, and uploads one
artifact bundle. Publication, provenance attestation, and the GitHub release all
reuse that exact bundle.

If a release is broken, fix forward with a new patch release. A maintainer may
yank the affected PyPI version while keeping its files and GitHub release for
auditability; do not retag or replace published artifacts. Security fixes are
supported only on the latest release and `main`, as documented in SECURITY.md.
