# Releasing

One version number lives in three manifests and is the source of truth for the published
distribution. `packaging/set_version.py` writes all three; nothing else should.

## The normal path: the release workflow

**Actions → `release` → Run workflow.**

| Input | Value |
|---|---|
| `release_version` | `v0.0.2` — with the `v`, final releases only |
| `dry_run` | leave **checked** the first time |
| `allow_same_version` | only for the very first release; see below |

One button does the whole thing: bumps all three manifests, stamps the changelog, commits,
tags, creates the GitHub release with the changelog section as its notes, publishes to PyPI,
and attaches the wheel, sdist and npm tarball to the release.

The order is deliberate — every check runs *before* anything is written:

1. **preflight** — the version is well-formed, moves forward, has no existing tag, and has a
   `## [vX.Y.Z]` section in `CHANGELOG.md`. The notes that would be published are printed to
   the run summary so you can read them before committing to them.
2. **ci** and **packaging** — the same checks a PR gets, via the same workflow files.
3. **tag** — the first job that writes. Bumps, stamps, re-runs `verify.py` with the release
   version in place, commits, tags, pushes, creates the release.
4. **publish** — builds at the tag, re-runs the checks there, uploads to PyPI.

`dry_run` stops after step 3's local commit, before any push, and tells you in the run
summary exactly what it would have done. Rehearsing costs a few runner minutes and nothing
else, so do it.

### Write the changelog first

The release refuses to run without notes. Add the section in the PR that finishes the work,
not at release time:

```markdown
## [v0.0.2]

### Fixed

- The thing that was broken.
```

No date — the workflow stamps it. Keep the entries written for whoever reads the release
page.

`python packaging/changelog.py check v0.0.2` tells you locally whether the release would
accept it, and `show` prints the exact notes that would be published.

### The first release

`v0.0.1` is already the version in the manifests (it was bumped by hand in the PR that added
the sdist fix), so `check_release.py` would refuse it as "already the current version." Tick
**`allow_same_version`** for that one release only. Every release after it moves the version
forward and needs nothing special.

### What can go wrong

- **`main` is protected.** The workflow pushes one commit to `main` as
  `github-actions[bot]`. If a ruleset blocks that, either allow the bot to bypass it or use
  the manual path below. This is the one requirement that cannot be worked around in the
  workflow itself.
- **Prereleases are refused.** `v0.0.2rc1` and friends fail preflight with an explanation:
  PEP 440 spells them `0.0.2rc1`, npm semver spells them `0.0.2-rc.1`, and one version string
  goes into both a `pyproject.toml` and a `package.json` — so `npm pack` would reject it and
  the packaging job would fail *after* the tag was pushed. Supporting them means teaching
  `set_version.py` a per-ecosystem spelling first.
- **The tag already exists.** Preflight refuses it. PyPI versions are immutable, so a
  re-release cannot replace what is already published — bump to the next patch.
- **PyPI rejects the version as already used.** Same cause, caught later. Bump and re-run.
- **A job failed after the tag was pushed.** The tag and GitHub release exist but PyPI does
  not have the version. Fix the cause and re-run the `publish` workflow manually against
  that tag, rather than re-running `release` — the tag is already correct.

## The manual path

Still supported, and the fallback if `main` cannot accept a bot push.

```bash
python packaging/set_version.py 0.0.2
# add the CHANGELOG section, then land both on main through a PR

pytest
ruff check . && ruff format --check .
python packaging/verify.py

git checkout main && git pull
git tag v0.0.2
git push origin v0.0.2
```

The tag push triggers `publish.yml`, which refuses to continue unless the tag matches the
manifest version, then publishes and attaches the artifacts to a generated GitHub release.

To rehearse without publishing, run `publish` manually with `dry_run: true` (the default).

## First-time setup

Done once per repository. **No API token is created or stored** — PyPI trusted publishing
uses the workflow's OIDC identity.

1. **GitHub environment.** Settings → Environments → New environment → `pypi`. Add required
   reviewers if you want a human gate on every publish.

2. **PyPI trusted publisher.** As `unionai-oss`, at
   <https://pypi.org/manage/account/publishing/>, add a *pending* publisher — pending,
   because the project does not exist until the first release:

   | Field | Value |
   |---|---|
   | PyPI project name | `union-skills` |
   | Owner | `unionai-oss` |
   | Repository name | `union-skills` |
   | Workflow name | `publish.yml` |
   | Environment name | `pypi` |

   It becomes a normal publisher after the first successful publish.

   `publish.yml` is the right workflow name even when `release.yml` drives the release:
   trusted publishing checks the workflow that performs the upload, and that is always
   `publish.yml`, whether it was called as a job or triggered by a tag.

npm is not set up; see [packaging/README.md](packaging/README.md#enabling-npm) for what that
would need.
