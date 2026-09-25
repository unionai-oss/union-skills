# Packaging and release

The skills in `plugins/union/` are published from this one source of truth:

| Registry | Package | Status |
|---|---|---|
| PyPI | [`union-skills`](https://pypi.org/project/union-skills/) | published |
| npm | `union-skills` | **built and validated, not published** |

**npm publishing is currently disabled** while distribution focuses on pip/uvx. The npm
package is still generated, packed and validated on every CI run, so turning it on later is
a small change to `publish.yml` — see [Enabling npm](#enabling-npm).

## Why a registry at all

A git-distributed plugin has no download counter. GitHub clone traffic is the only proxy, it
conflates CI and update re-fetches with installs, and GitHub retains just a rolling 14-day
window. PyPI publishes free, historical download data:

```
https://pypistats.org/api/packages/union-skills/recent
https://pypistats.org/api/packages/union-skills/overall
```

For full history and mirror-free numbers, query `bigquery-public-data.pypi.file_downloads`
and filter `details.installer.name IN ('pip','uv')`. Neither registry gives a unique-user
signal — they answer "is adoption trending up", not "how many teams use this".

## Layout

```
packaging/
├── build.py            # generates both source trees into ./build
├── set_version.py      # writes one version into every manifest
├── verify.py           # builds + installs each distribution, asserts contents
└── templates/
    ├── cli.py          # the Python installer CLI (PyPI)
    ├── cli.mjs         # the Node installer CLI (npm)
    └── README.md.tmpl  # the per-package README shown on PyPI/npm
```

`build.py` fans the payload out per registry:

* **PyPI** — an `src/union_skills/` package with the whole plugin vendored at
  `union_skills/plugin/` as package data, plus a `union-skills` console script.
* **npm** — the package root *is* the plugin root (`.claude-plugin/plugin.json` at the top
  level), which is what Claude Code's `npm` plugin source requires. `package.json` carries an
  explicit `files` allowlist because npm's default file selection is not reliable about
  dot-directories, plus the `pi.skills` manifest so pi reads the same tree.

The two CLIs are independent implementations of one contract. `verify.py` asserts they
declare the same harness targets and emit byte-identical `mcp` command lines, because drift
between them would silently give npm and PyPI users different behaviour.

## Local development

```bash
python packaging/build.py          # write ./build/{npm,pypi}/union-skills/
python packaging/verify.py         # what CI runs: build, install, assert
pytest                             # content lint + unit tests
```

`verify.py` needs `node`/`npm` and either `uv` or `python -m build`.

## Cutting a release

See [`RELEASING.md`](../RELEASING.md). In short: `packaging/set_version.py` sets the version,
that lands on `main` through a PR, and pushing a matching `v*` tag triggers the publish.

`.github/workflows/publish.yml` then:

1. refuses to continue unless the tag matches the plugin manifest version;
2. runs `pytest` and `verify.py` — a package that does not install, or a skill that links to
   a page that does not exist, is never published;
3. builds the npm tarball and the sdist/wheel, and runs `npm publish --dry-run` and
   `twine check`;
4. publishes to PyPI via trusted publishing — no API token stored anywhere;
5. attaches every artifact to the GitHub release.

To rehearse without publishing, run the workflow manually with `dry_run: true` (the default)
— it does everything through step 3 and stops.

`.github/workflows/packaging.yml` runs step 2 on every PR that touches `plugins/**` or
`packaging/**`.

## One-time setup

A `pypi` GitHub environment and a PyPI trusted publisher for `union-skills` — see
[First-time setup](../RELEASING.md#first-time-setup) for the exact values. No API token is
stored; the workflow's `id-token: write` permission is what authenticates, and PyPI's
*pending publishers* let that work for a name that does not exist yet.

## Enabling npm

The `npm` job in `publish.yml` is gated behind `if: false`. To turn it on: restore the
condition to `github.event_name == 'push' || inputs.dry_run == false`, create an `npm`
environment, and add the token described below.

**npm needs a token for the first publish, unlike PyPI.** npm has no equivalent of PyPI's
pending publishers: a trusted publisher can only be configured on a package that already
exists, and OIDC cannot perform a package's first publish
([npm/cli#8544](https://github.com/npm/cli/issues/8544)).

Create the token on npmjs.com and store it as the secret `NPM_TOKEN` in the `npm`
environment. Use a classic **automation** token, or a granular token with "All packages" — a
granular token scoped to specific packages cannot cover a name that does not exist yet.
Tighten it after the first release.

`--provenance` needs no extra secret — it uses the workflow's OIDC token — but it **does**
require `package.json`'s `repository.url` to match the repo the workflow runs in. `build.py`
derives that from `GITHUB_SERVER_URL` / `GITHUB_REPOSITORY` at build time so it always
matches; the hardcoded fallback is only used for local builds.

*After* the name exists on npm you can switch to OIDC trusted publishing and delete
`NPM_TOKEN`: configure the publisher on npmjs.com (pointing at this workflow file and the
`npm` environment), then drop `NODE_AUTH_TOKEN`, drop `--provenance` (OIDC generates it
automatically), and bump `node-version` to `22` or later — trusted publishing needs
npm >= 11.5.1 / Node >= 22.14.0, and the pinned Node 20 ships npm 10.x.

## Using the package as a plugin source

Once the npm job is enabled and the package is published, `marketplace.json` can point at
npm instead of (or alongside) the git source, which routes installs through a counter:

```json
{
  "name": "union",
  "source": { "source": "npm", "package": "union-skills", "version": "^0.1.0" }
}
```

There is no `pip` plugin source type. The PyPI package instead ships an installer CLI, and
`union-skills emit-plugin` satisfies the `command` source contract (print one absolute path
to the plugin directory, exit 0):

```json
{
  "name": "union",
  "source": {
    "source": "command",
    "command": "uvx --from union-skills union-skills emit-plugin",
    "timeout": 120,
    "mode": "copy"
  }
}
```

Do not make that the only path — a `command` source runs a local program at install time, so
enterprise-managed settings block it, and it needs `uv` on the machine.
