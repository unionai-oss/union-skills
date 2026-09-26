#!/usr/bin/env python3
"""Refuse a release that cannot succeed, before anything is tagged or published.

    python packaging/check_release.py v0.0.2

Checks, in the order they are cheapest to fix:

  * the version is spelled `vX.Y.Z`;
  * it is strictly greater than the version currently in the manifests, so a
    release cannot silently go backwards or re-release the same number;
  * the git tag does not already exist locally or on the remote.

PyPI versions are immutable and a tag is awkward to retract, so every one of
these is worth failing on while it is still free.

Prereleases are deliberately refused -- see ``parse_version``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "plugins" / "union" / ".claude-plugin" / "plugin.json"

VERSION = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")

# Spellings someone will reasonably try, and why each is refused. Prereleases
# need a decision this repo has not made yet: PEP 440 wants `0.0.2rc1` and npm
# semver wants `0.0.2-rc.1`, and packaging/build.py writes ONE version string
# into both a pyproject.toml and a package.json. `npm pack` rejects the PEP 440
# spelling outright, so the packaging job would fail after the tag was already
# pushed. Supporting prereleases means teaching set_version.py to write a
# different spelling per ecosystem and relaxing verify.py's one-version check.
PRERELEASE = re.compile(r"^v?\d+\.\d+\.\d+[-.]?(a|b|rc|alpha|beta|dev|post)", re.I)


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_version(version: str) -> tuple[int, int, int]:
    if PRERELEASE.match(version):
        fail(
            f"{version!r} looks like a prerelease, which this repo does not support yet.\n"
            "  PEP 440 spells it `0.0.2rc1` and npm semver spells it `0.0.2-rc.1`, and one\n"
            "  version string is written into both pyproject.toml and package.json -- so\n"
            "  `npm pack` would reject it and the packaging job would fail after the tag\n"
            "  was already pushed. Release a final vX.Y.Z, or teach set_version.py to write\n"
            "  a per-ecosystem spelling first."
        )
    match = VERSION.match(version)
    if not match:
        fail(f"{version!r} is not a vX.Y.Z version (for example v0.0.2).")
    return tuple(int(g) for g in match.groups())  # type: ignore[return-value]


def current_version() -> tuple[str, tuple[int, int, int]]:
    raw = json.loads(MANIFEST.read_text())["version"]
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", raw)
    if not match:
        fail(f"the version in {MANIFEST.relative_to(REPO)} is {raw!r}, which is not X.Y.Z.")
    return raw, tuple(int(g) for g in match.groups())  # type: ignore[return-value]


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout.strip()


def check_tag_is_free(version: str) -> None:
    if git("tag", "--list", version):
        fail(f"tag {version} already exists locally. If it was never pushed: git tag -d {version}")
    # A remote tag means this version was very likely already published, and PyPI
    # will not accept it a second time.
    if git("ls-remote", "--tags", "origin", f"refs/tags/{version}"):
        fail(
            f"tag {version} already exists on origin. Releasing it again cannot "
            "replace what is on PyPI -- versions there are immutable. Bump to the "
            "next patch instead."
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("version", help="Release version, e.g. v0.0.2")
    ap.add_argument(
        "--allow-same",
        action="store_true",
        help=(
            "Permit releasing the version already in the manifests. Needed for the "
            "very first release, where main was bumped by hand beforehand."
        ),
    )
    ap.add_argument("--skip-tag-check", action="store_true", help="Do not consult git.")
    args = ap.parse_args(argv)

    new = parse_version(args.version)
    current_raw, current = current_version()

    if new < current:
        fail(
            f"{args.version} is older than the current version {current_raw}. "
            "Releases must move forward."
        )
    if new == current and not args.allow_same:
        fail(
            f"{args.version} is already the version in the manifests ({current_raw}).\n"
            "  Bump to the next version, or pass --allow-same if this version has not "
            "been released yet (the first release, where main was bumped by hand)."
        )

    if not args.skip_tag_check:
        check_tag_is_free(args.version)

    moved = "unchanged" if new == current else f"{current_raw} -> {args.version.lstrip('v')}"
    print(f"ok: {args.version} is releasable ({moved})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
