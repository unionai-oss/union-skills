# Changelog

All notable changes to `union-skills` are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Each release gets a `## [vX.Y.Z] - YYYY-MM-DD` heading, written by hand. Nothing
automated reads this file: `publish.yml` builds the GitHub release notes from
commits with `--generate-notes`. So this is the only place a reader can see what
changed between versions — write these entries for them.

## [v0.0.5] - 2026-09-30

### Changed

- `union-connect-cluster` now makes the agent stop and ask what to call the
  cluster in Union.ai, instead of filling the **Name** field in from the EKS
  cluster's name. The name is permanent — changing it means disconnect and
  re-register — so it is the human's call. The skill already said to ask; the
  ask is now enforced by the command itself, which guards on a separate
  `UNION_CLUSTER_NAME` and refuses to run on a derived value. The EKS name is
  still offered, as a suggestion inside the question.

## [v0.0.4] - 2026-09-29

What a real self-serve setup, driven end to end, turned up. Two documented
commands were wrong when run; the rest is guidance that was missing.

### Fixed

- `union-provision-aws` no longer uses the filtered
  `describe-cluster-versions --query` form. On some AWS CLI versions
  `clusterVersionStatus` comes back `null`, so the command printed nothing at
  all — which reads exactly like "no Kubernetes versions available" and sends
  you chasing a problem that isn't there.
- `union-provision-aws` no longer verifies the IAM policies with a loop over
  `"$ROLE:policy"` pairs. In zsh — the default shell on macOS, and what an
  agent's shell tool usually gets — that collides with zsh's `:u` modifier and
  mangles the role name into a `NoSuchEntity`. The policies attached correctly
  either way, so only the check was broken, which made it a confusing failure
  to read.

### Changed

- `union-provision-aws` now runs its steps in dependency order rather than
  numbered order. None of the four cluster-pool values depend on the EKS
  cluster, so the S3 bucket and ECR repository come first and you fill in the
  UI form during the 15–20 minute cluster build instead of after it.
- `AWS_PROFILE` now belongs in the state file. Every agent command runs in a
  fresh shell, so a profile exported earlier is gone by the next command and
  the account silently falls back to the default — which is often a shared or
  production account.

### Added

- `union-self-serve` gains a status-discipline section: block on a condition
  instead of hand-polling, keep a standing done / in-flight / blocked-on-you
  table, and re-state blocked hand-offs every turn.
- `union-connect-cluster` answers the **Namespace** field (`union`) and explains
  why its IAM warning does not mean you have to go back and edit IAM; notes that
  `cloudProvider: byoc-onprem` is correct on an AWS cluster; and covers checking
  the generated `values.yaml` without printing the private key it holds.
- `union-provision-aws` sweeps for earlier half-built stacks before provisioning
  alongside them, since an abandoned EKS cluster bills indefinitely.
- Teardown now covers a cluster carrying several data plane installs, each of
  which needs disconnecting in the UI.

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
