# union-skills

Agent skills for deploying, maintaining, and developing on [Union.ai](https://www.union.ai).

The first release covers [self-serve setup](https://www.union.ai/docs/v2/union/deployment/self-serve/)
on AWS, end to end: provision the infrastructure, connect a cluster, run workflows, and
debug a data plane that will not come up.

```bash
uvx union-skills install        # copy the skills into whichever harness you use
```

## Why these exist

The self-serve docs are written for a human at a terminal. Handing them to an agent breaks
in three specific ways, and these skills exist to fix each one:

**The shell does not persist.** The docs say "run every step in the same shell session" and
pass values between steps with `export`. An agent runs each command in a fresh shell, so
every `export` evaporates — and a later step reading `${CLUSTER_NAME}` silently gets an
empty string, creating an IAM role named `-system` or an S3 policy scoped to
`arn:aws:s3:::`. The skills keep state in a file, source it at the top of every command, and
assert on it with `${VAR:?}` before interpolating it into anything.

**Some of these commands cost real money and are hard to undo.** Every command that creates,
modifies or deletes a cloud resource is marked **⛔ APPROVAL GATE**: the agent must show the
exact command and what it creates, and wait for an explicit yes. Read-only probes are marked
**🟢 READ-ONLY** and run freely. The test suite enforces that a skill containing
`eksctl create` or `aws iam put-role-policy` also carries the gate vocabulary.

**Half the flow is a web form.** Subscribing, creating an organization, creating a cluster
pool and registering a cluster exist only in the browser. The skills mark each crossing —
**📤 TO THE UI** for values the agent prints and the human pastes in, **📥 FROM THE UI** for
things the human copies back — so nobody sits waiting on a turn that is theirs.

And one thing the docs do not have to worry about: the agent install command the UI
generates contains the cluster's **client certificate and private key**. Pasting it into a
chat with an agent puts a credential in a stored transcript. `union-connect-cluster` routes
around that — clipboard straight to a file, contents never rendered — and says so plainly.

## The skills

| Skill | What it does |
|---|---|
| [`union-self-serve`](plugins/union/skills/union-self-serve/SKILL.md) | Entry point. Routes to the right step, walks the two browser-only steps (Marketplace, sign-up), and defines the state file, approval gates and hand-off protocol the others share. |
| [`union-run-locally`](plugins/union/skills/union-run-locally/SKILL.md) | Set up the `flyte` CLI and run a first workflow as a **tracked run** — on your own machine, visible in the Union.ai UI, no cluster and no AWS spend. |
| [`union-provision-aws`](plugins/union/skills/union-provision-aws/SKILL.md) | Create the EKS cluster (Auto Mode), S3 bucket, private ECR repository and the two IRSA roles, then print the six values the UI asks for. Every step gated and idempotent. |
| [`union-connect-cluster`](plugins/union/skills/union-connect-cluster/SKILL.md) | Create the cluster pool, register the cluster, install the `dp-agent` Helm release, and wait while Union.ai installs the data plane through it. |
| [`union-debug-cluster`](plugins/union/skills/union-debug-cluster/SKILL.md) | Diagnose a cluster that is unhealthy or stuck: agent not connecting, data plane never arriving, IRSA trust mismatches, S3/ECR denials, Auto Mode not scheduling, Metrics Server collisions, missing bucket CORS. Ships a read-only snapshot script. |

Reference pages that skills link to at runtime:

- [`union-provision-aws/references/existing-resources.md`](plugins/union/skills/union-provision-aws/references/existing-resources.md) — conformance checklist for AWS resources you already have.
- [`union-provision-aws/references/iam-policies.md`](plugins/union/skills/union-provision-aws/references/iam-policies.md) — what the wildcard IRSA trust actually grants, and how to narrow it after the install.
- [`union-provision-aws/references/teardown.md`](plugins/union/skills/union-provision-aws/references/teardown.md) — full cleanup, in the order it has to happen.

## Install

### pip / uvx (any harness)

```bash
uvx union-skills install                       # auto-detect installed harnesses
uvx union-skills install --target claude       # or pick them explicitly
uvx union-skills install --target agents       # the cross-harness standard location
uvx union-skills install --project             # this repo only
uvx union-skills install --dry-run             # show what would change
uvx union-skills uninstall
```

Or `pip install union-skills` and drop the `uvx`.

| `--target` | User-level | Project-level (`--project`) | Read by |
|---|---|---|---|
| `agents` | `~/.agents/skills/` | `.agents/skills/` | Codex, Hermes (project), anything following the convention |
| `claude` | `~/.claude/skills/` | `.claude/skills/` | Claude Code |
| `hermes` | `~/.hermes/skills/` | `.hermes/skills/` | Hermes |
| `opencode` | `~/.config/opencode/skills/` | `.opencode/skills/` | opencode |
| `pi` | `~/.pi/agent/skills/` | — | pi |

`codex` is accepted as an alias for `agents` — it is the same directory.

### Claude Code plugin (from git)

```
/plugin marketplace add unionai-oss/union-skills
/plugin install union@union-skills
```

This installs the whole plugin, including the MCP servers below.

### Codex

```bash
uvx union-skills install --target agents
```

Or point Codex at the plugin directly: `plugins/union/` carries a `.codex-plugin/plugin.json`
naming both the skills directory and `.mcp.json`.

### pi

`package.json` declares `pi.skills`, so pi reads `plugins/union/skills` from a checkout, and
`bin/cli.mjs` from the npm package once that is published.

## MCP servers

`install` writes skills only — they are inert markdown. The bundled MCP servers are live
tools the agent can call, so adding them is a separate, opt-in step:

```bash
uvx union-skills mcp list              # what would be added
uvx union-skills mcp install --dry-run # print the commands, change nothing
uvx union-skills mcp install           # add them
uvx union-skills mcp uninstall
```

| Server | What it is |
|---|---|
| `flyte-docs` | Hosted HTTP endpoint for searching the Flyte and Union.ai docs. |
| `flyte-cluster` | Local `uvx flyte[mcp]` process with control-plane access to your organization — runs, tasks, logs, apps, triggers, secrets. Needs `uv` and a login. |

Union.ai is a commercial superset of open-source Flyte and uses the **same `flyte` SDK and
CLI**, which is why the servers carry those names. Harnesses that consume the whole plugin
(Claude Code, Codex) pick them up from `.mcp.json` automatically.

`mcp install` drives `claude mcp add-json` / `codex mcp add` rather than editing config files
by hand, so it needs one of those CLIs on your PATH. `~/.claude.json` holds a lot of
unrelated state that a bad merge would clobber.

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest                       # content lint + CLI + packaging tests
ruff check . && ruff format --check .
python packaging/verify.py   # build both distributions and prove they install
```

`ruff format` also formats the Python code blocks inside the skills, so the examples users
copy-paste stay consistent.

### Layout

```
plugins/union/            the single source of truth — manifests, .mcp.json, skills/
packaging/                generates the PyPI and npm trees from it
  templates/cli.py        the Python installer CLI  } two implementations of one
  templates/cli.mjs       the Node installer CLI     } contract; verify.py diffs them
tests/                    content lint, CLI behaviour, build fan-out
.github/workflows/        ci, packaging, build-dists (shared), release, tag-push
```

Releases are cut from the Actions tab — **`release` → Run workflow** with a `vX.Y.Z`
version, `dry_run` on to rehearse. It bumps the manifests, stamps `CHANGELOG.md`, tags,
creates the GitHub release, and publishes to PyPI. See [RELEASING.md](RELEASING.md) for the
whole flow and the one-time PyPI setup, and [packaging/README.md](packaging/README.md) for
how the distributions are built.

Add a `## [vX.Y.Z]` section to [CHANGELOG.md](CHANGELOG.md) in the PR that finishes the
work — the release refuses to run without notes, and uses that section as the release body.

### Adding a skill

1. `plugins/union/skills/<union-name>/SKILL.md`, with `name:` matching the directory and a
   `description:` an agent can route on.
2. Use the badge vocabulary — `tests/test_skills.py` enforces that it stays closed, and that
   a skill running mutating commands carries an approval gate.
3. `pytest && python packaging/verify.py`.

## License

Apache-2.0
