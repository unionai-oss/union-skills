# Changelog

All notable changes to `union-skills` are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Each release gets a `## [vX.Y.Z] - YYYY-MM-DD` heading, written by hand. Nothing
automated reads this file: `publish.yml` builds the GitHub release notes from
commits with `--generate-notes`. So this is the only place a reader can see what
changed between versions — write these entries for them.

## [v0.0.3] - 2026-09-28

### Fixed

- `union-connect-cluster` now watches the right place for the install to
  finish. The Union.ai console shows the **Healthy** badge next to the
  cluster's name on its own page — the same badge that reads **Unhealthy**
  throughout the install — not in the cluster list, where the skill had been
  sending you.

## [v0.0.2] - 2026-09-26

No skill changes. Release machinery only, recorded here because v0.0.2 shipped
without a changelog entry.

### Changed

- Releases now happen by pushing a `v*` tag, which triggers one self-contained
  `publish.yml`. This replaces the dispatch-driven machinery, whose reusable
  workflow could not be named as a PyPI trusted publisher. See
  [`RELEASING.md`](RELEASING.md).

## [v0.0.1] - 2026-09-26

First release.

### Added

- Five skills for Union.ai self-serve setup on AWS: `union-self-serve` (router
  and shared conventions), `union-run-locally` (tracked runs),
  `union-provision-aws` (EKS Auto Mode, S3, ECR, IRSA roles),
  `union-connect-cluster` (cluster pool, registration, agent install), and
  `union-debug-cluster` (health triage plus a read-only snapshot script).
- Reference pages for bring-your-own AWS resources, the IAM model, and teardown.
- An installer CLI for Claude Code, Codex/`.agents`, Hermes, opencode and pi,
  with an opt-in `mcp` subcommand for the two bundled MCP servers.
- Distribution as `union-skills` on PyPI, plus an npm package that is built and
  validated on every run but not yet published.
