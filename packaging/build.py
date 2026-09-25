#!/usr/bin/env python3
"""Generate the PyPI and npm source trees for the Union skills distribution.

One source of truth -- ``plugins/union/`` -- fans out into two published
artifacts of the same name, ``union-skills``, on two registries. PyPI is the
published one; the npm tree is built and validated on every CI run so that
turning it on later is a one-line change rather than an archaeology project.

    python packaging/build.py                 # build everything into ./build
    python packaging/build.py --print-version # version from the plugin manifest
    python packaging/build.py --only pypi     # just the PyPI tree

The version comes from ``plugins/union/.claude-plugin/plugin.json``; use
``packaging/set_version.py`` to change it.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN_SRC = REPO / "plugins" / "union"
TEMPLATES = REPO / "packaging" / "templates"

# npm rejects a provenance attestation unless package.json's repository URL
# matches the repo the workflow runs in, so prefer the CI-provided slug.
REPO_URL = (
    f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}"
    if os.environ.get("GITHUB_SERVER_URL") and os.environ.get("GITHUB_REPOSITORY")
    else "https://github.com/unionai-oss/union-skills"
)

DIST = "union-skills"
MODULE = DIST.replace("-", "_")

KEYWORDS = [
    "union",
    "unionai",
    "flyte",
    "agent-skills",
    "claude-code",
    "claude-code-plugin",
    "codex",
    "mcp",
    "workflow-orchestration",
    "eks",
    "aws",
]

# Registries a README template block can be gated on.
BLOCK_TAGS = ("npm", "pypi")


def manifest() -> dict:
    return json.loads((PLUGIN_SRC / ".claude-plugin" / "plugin.json").read_text())


def version() -> str:
    return manifest()["version"]


def description() -> str:
    return manifest()["description"]


def skill_names() -> list[str]:
    return sorted(p.name for p in (PLUGIN_SRC / "skills").iterdir() if (p / "SKILL.md").is_file())


def strip_blocks(text: str, active: set[str]) -> str:
    """Keep ``<!-- <tag>-only:start -->`` sections whose tag is active, drop the rest.

    One template, two registries: each package's README should carry only the
    install instructions that actually work for it.
    """
    for tag in BLOCK_TAGS:
        start, end = f"<!-- {tag}-only:start -->\n", f"<!-- {tag}-only:end -->\n"
        if tag in active:
            text = text.replace(start, "").replace(end, "")
            continue
        while start in text:
            head, _, rest = text.partition(start)
            _, _, tail = rest.partition(end)
            text = head + tail
    return text


def render_readme(ver: str, registry: str) -> str:
    tmpl = strip_blocks((TEMPLATES / "README.md.tmpl").read_text(), {registry})
    return (
        tmpl.replace("{{DIST}}", DIST)
        .replace("{{MODULE}}", MODULE)
        .replace("{{VERSION}}", ver)
        .replace("{{REPO_URL}}", REPO_URL)
        .replace("{{DESCRIPTION}}", description())
        .replace("{{SKILL_COUNT}}", str(len(skill_names())))
    )


def copy_plugin(dest: Path) -> None:
    """Copy the plugin payload (manifests + .mcp.json + skills) into dest."""
    dest.mkdir(parents=True, exist_ok=True)
    for name in (".claude-plugin", ".codex-plugin", "skills"):
        shutil.copytree(PLUGIN_SRC / name, dest / name)
    shutil.copy2(PLUGIN_SRC / ".mcp.json", dest / ".mcp.json")


def build_npm(ver: str, outdir: Path) -> Path:
    """An npm plugin source requires the package root to BE the plugin root."""
    pkg = outdir / "npm" / DIST
    if pkg.exists():
        shutil.rmtree(pkg)
    copy_plugin(pkg)

    (pkg / "bin").mkdir()
    shutil.copy2(TEMPLATES / "cli.mjs", pkg / "bin" / "cli.mjs")
    (pkg / "bin" / "cli.mjs").chmod(0o755)

    shutil.copy2(REPO / "LICENSE", pkg / "LICENSE")
    (pkg / "README.md").write_text(render_readme(ver, "npm"))

    package_json = {
        "name": DIST,
        "version": ver,
        "description": description(),
        "license": "Apache-2.0",
        "homepage": f"{REPO_URL}#readme",
        "repository": {"type": "git", "url": f"git+{REPO_URL}.git"},
        "bugs": {"url": f"{REPO_URL}/issues"},
        "keywords": KEYWORDS + ["pi-package"],
        "type": "module",
        "bin": {DIST: "bin/cli.mjs"},
        # An explicit allowlist: the payload lives in dot-directories, which
        # npm's default file selection is not reliable about including.
        "files": [
            ".claude-plugin/",
            ".codex-plugin/",
            ".mcp.json",
            "skills/",
            "bin/",
            "README.md",
            "LICENSE",
        ],
        "engines": {"node": ">=18"},
        # pi reads its skill roots from this manifest.
        "pi": {"skills": ["./skills"]},
        "publishConfig": {"access": "public", "provenance": True},
    }
    (pkg / "package.json").write_text(json.dumps(package_json, indent=2) + "\n")
    return pkg


def build_pypi(ver: str, outdir: Path) -> Path:
    pkg = outdir / "pypi" / DIST
    if pkg.exists():
        shutil.rmtree(pkg)
    src = pkg / "src" / MODULE
    src.mkdir(parents=True)

    copy_plugin(src / "plugin")
    shutil.copy2(TEMPLATES / "cli.py", src / "cli.py")
    (src / "__init__.py").write_text(
        '"""Union.ai agent skills, installable into any agent harness."""\n\n'
        f'__version__ = "{ver}"\n\n'
        "from .cli import TARGETS, main, plugin_root\n\n"
        '__all__ = ["TARGETS", "main", "plugin_root", "__version__"]\n'
    )

    shutil.copy2(REPO / "LICENSE", pkg / "LICENSE")
    (pkg / "README.md").write_text(render_readme(ver, "pypi"))

    pyproject = f"""\
[build-system]
requires = ["hatchling>=1.24"]
build-backend = "hatchling.build"

[project]
name = "{DIST}"
version = "{ver}"
description = "{description()}"
readme = "README.md"
requires-python = ">=3.9"
license = "Apache-2.0"
license-files = ["LICENSE"]
authors = [{{ name = "unionai-oss" }}]
keywords = {json.dumps(KEYWORDS)}
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "Programming Language :: Python :: 3",
    "Topic :: Software Development :: Code Generators",
    "Topic :: System :: Installation/Setup",
]
dependencies = []

[project.urls]
Homepage = "{REPO_URL}"
Repository = "{REPO_URL}"
Issues = "{REPO_URL}/issues"

[project.scripts]
{DIST} = "{MODULE}.cli:main"

# The payload is markdown under src/{MODULE}/plugin/, including dot-directories.
# ignore-vcs keeps a build/ directory listed in .gitignore from being pruned.
[tool.hatch.build]
ignore-vcs = true

[tool.hatch.build.targets.wheel]
packages = ["src/{MODULE}"]
artifacts = ["src/{MODULE}/plugin/**"]

[tool.hatch.build.targets.sdist]
include = ["src", "README.md", "LICENSE", "pyproject.toml"]
artifacts = ["src/{MODULE}/plugin/**"]
"""
    (pkg / "pyproject.toml").write_text(pyproject)
    return pkg


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--outdir", default=str(REPO / "build"))
    ap.add_argument("--only", choices=["npm", "pypi"], help="Build only one registry.")
    ap.add_argument(
        "--print-version",
        action="store_true",
        help="Print the version from the plugin manifest and exit.",
    )
    args = ap.parse_args()

    ver = version()
    if args.print_version:
        print(ver)
        return 0

    outdir = Path(args.outdir).resolve()
    skills = skill_names()
    if not skills:
        raise SystemExit(f"No skills found under {PLUGIN_SRC / 'skills'}")

    print(f"version {ver}, {len(skills)} skills, out={outdir}")
    if args.only != "pypi":
        print(f"  npm  {build_npm(ver, outdir)}")
    if args.only != "npm":
        print(f"  pypi {build_pypi(ver, outdir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
