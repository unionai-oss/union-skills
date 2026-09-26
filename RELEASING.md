# Releasing

One version number lives in three manifests and is the source of truth for both published
distributions. `packaging/set_version.py` writes all three; nothing else should.

## Cutting a release

1. **Set the version.**

   ```bash
   python packaging/set_version.py 0.0.2
   ```

   Writes `plugins/union/.claude-plugin/plugin.json`,
   `plugins/union/.codex-plugin/plugin.json` and `package.json`.

2. **Check it locally**, exactly as CI will.

   ```bash
   pytest
   ruff check . && ruff format --check .
   python packaging/verify.py
   ```

3. **Land it on `main` through a PR.** The version bump is the whole PR; CI runs the
   packaging job on it because it touches `plugins/**`.

4. **Rehearse the publish** (optional but cheap). Run the `publish` workflow manually with
   `dry_run: true` — the default. It builds, validates, `twine check`s and
   `npm publish --dry-run`s, then stops without publishing.

5. **Tag and push.**

   ```bash
   git checkout main && git pull
   git tag v0.0.2
   git push origin v0.0.2
   ```

   The tag must match the manifest version or the workflow fails on purpose, rather than
   publishing a version nobody can trace back to a commit.

6. **Watch the run.** It publishes to PyPI and attaches the artifacts to a generated GitHub
   release.

## If something goes wrong

- **Tag/manifest mismatch.** `git tag -d v0.0.2 && git push --delete origin v0.0.2`, fix the
  manifest with `set_version.py`, land it, re-tag.
- **PyPI rejects the version as already used.** Versions on PyPI are immutable and cannot be
  reused even after deletion. Bump to the next patch and release again.
- **Re-running a tag.** Safe: the publish step uses `skip-existing: true`, so a re-run of an
  already-published version is a no-op rather than a failure.

## First-time setup

Done once per repository. No API token is created or stored.

1. **GitHub environment.** Create an environment named `pypi` (Settings → Environments). Add
   required reviewers if you want a human gate on every publish.

2. **PyPI trusted publisher.** On PyPI, add a *pending* publisher (Your projects → Publishing
   → Add a pending publisher) — pending, because the project does not exist until the first
   release:

   | Field | Value |
   |---|---|
   | PyPI project name | `union-skills` |
   | Owner | `unionai-oss` |
   | Repository name | `union-skills` |
   | Workflow name | `publish.yml` |
   | Environment name | `pypi` |

   The publisher becomes a normal one after the first successful publish.

npm is not set up; see [packaging/README.md](packaging/README.md#enabling-npm) for what that
would need.
