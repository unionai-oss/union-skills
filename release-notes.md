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
