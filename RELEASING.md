# Releasing

How to publish a new version of `union-skills` to PyPI.

The version comes from `plugins/union/.claude-plugin/plugin.json` and the tag must match it —
CI refuses to publish otherwise. `packaging/set_version.py` writes that manifest and the two
that must agree with it; nothing else should.

For how the package is built, see [`packaging/README.md`](packaging/README.md). npm
publishing is currently disabled; that document explains how to turn it on.

## First-time setup

Needed once per repository, not once per release. Skip if
<https://pypi.org/project/union-skills/> already exists.

- [ ] Create a GitHub environment named `pypi` (**Settings → Environments**). Add required
      reviewers if you want a human gate before each publish.
- [ ] Add a PyPI trusted publisher for `union-skills` at
      <https://pypi.org/manage/account/publishing/>, using the settings below. Before the
      first release the project does not exist yet, so add it under **pending publishers**.

| Field | Value |
|---|---|
| PyPI project name | `union-skills` |
| Owner | `unionai-oss` |
| Repository name | `union-skills` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

No API tokens are stored anywhere. The workflow authenticates over OIDC through its
`id-token: write` permission.

`publish.yml` is the correct workflow name because the tag push triggers it directly — it is
the workflow PyPI sees. PyPI matches the OIDC `workflow_ref` claim, and it cannot name a
reusable workflow as a publisher at all, which is why the release path deliberately stays in
one self-contained workflow.

## Release checklist

### 1. Pick the version

- [ ] Decide the new version. These are `SKILL.md` files, so judge the bump by what changes
      for someone whose agent already loads them: **patch** for wording and fixes, **minor**
      for new skills or a changed workflow, **major** for renaming or removing a skill (that
      breaks `/union:<skill>` invocations and any harness pinned to a path).
- [ ] Confirm the version is not already on PyPI. A version can never be re-uploaded, even
      after a yank:

      ```bash
      curl -s -o /dev/null -w '%{http_code}\n' https://pypi.org/pypi/union-skills/0.0.2/json
      # 404 = free to use, 200 = already published, pick the next one
      ```

### 2. Prepare the commit

- [ ] Start from an up-to-date `main` with a clean tree:

      ```bash
      git checkout main && git pull origin main && git status
      ```

- [ ] Set the version everywhere (plugin manifest, Codex manifest, root `package.json`):

      ```bash
      python packaging/set_version.py 0.0.2
      ```

- [ ] Add a `## [v0.0.2]` section to [`CHANGELOG.md`](CHANGELOG.md). Not enforced by CI —
      the GitHub release notes are generated from commits — but it is the only place a
      reader can see what changed between versions.

- [ ] Verify locally. This is the same check CI runs:

      ```bash
      python packaging/verify.py
      pytest
      ```

- [ ] Commit and open a PR, so the bump lands through review like anything else:

      ```bash
      git checkout -b release-0.0.2
      git commit -am "release 0.0.2"
      git push -u origin release-0.0.2 && gh pr create --fill
      ```

- [ ] Merge once `ci` and `packaging` are green.

### 3. Tag

- [ ] Tag the **merge commit on `main`**, not the branch:

      ```bash
      git checkout main && git pull origin main
      git tag v0.0.2
      git push origin v0.0.2
      ```

      The `v` prefix is required — `publish.yml` triggers on `v*` — and the rest must match
      the manifest exactly. A mismatch fails the build job with a message naming both
      versions.

### 4. Watch the publish

- [ ] Follow the run at
      <https://github.com/unionai-oss/union-skills/actions/workflows/publish.yml>, or from
      the terminal once the tag push has registered:

      ```bash
      gh run watch "$(gh run list --workflow=publish.yml --limit=1 --json databaseId --jq '.[0].databaseId')"
      ```

      It builds and verifies, publishes to PyPI, then attaches the artifacts to a GitHub
      release.

### 5. Confirm it landed

- [ ] PyPI shows the new version:

      ```bash
      curl -s https://pypi.org/pypi/union-skills/json | python3 -c 'import json,sys; print(json.load(sys.stdin)["info"]["version"])'
      ```

- [ ] A real install works end to end, from a clean cache:

      ```bash
      uvx --refresh --from union-skills==0.0.2 union-skills list          # expect 5 skills
      uvx --refresh --from union-skills==0.0.2 union-skills install --dry-run
      ```

- [ ] The GitHub release exists and carries the sdist, wheel and npm tarball:
      `gh release view v0.0.2`.

## When something goes wrong

**The tag does not match the manifest.** The build job stops before publishing anything.
Delete the tag (`git push origin :v0.0.2`), fix the version with `set_version.py`, and tag
again.

**`invalid-publisher` from PyPI.** The trusted publisher does not match the claims in the
error. Check the `workflow_ref` line it prints: it should end in `publish.yml`, and the
publisher's **Workflow name** must be exactly that. The tag is still valid, so once the
publisher is fixed, re-run the failed job rather than re-tagging.

**The publish failed after the tag was pushed.** The tag is fine; nothing reached PyPI and no
GitHub release exists, because the `release` job runs after `pypi`. Fix the cause and re-run
the failed jobs on that run — the built artifacts are still attached to it.

**A bad version reached PyPI.** You cannot overwrite or re-upload it, even after deleting it.
Publish a new patch version with the fix. Yank the bad one from the PyPI project page —
yanking hides it from new resolutions while leaving anyone who pinned it working.

**Rehearse without publishing.** Run `publish.yml` manually from the Actions tab with
`dry_run: true` (the default). It builds, verifies and validates the package, then stops
before any upload.

## After the release

- [ ] Consider whether the marketplace entry should pin the new version. The git source in
      `.claude-plugin/marketplace.json` tracks the default branch and needs no change; only
      an explicit `version` pin would.
- [ ] Adoption numbers show up within about a day at
      <https://pypistats.org/packages/union-skills>. Note PyPI counts downloads, not people —
      CI re-installs and mirrors are in there too.
