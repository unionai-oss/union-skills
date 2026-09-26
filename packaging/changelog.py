#!/usr/bin/env python3
"""Read, validate and stamp CHANGELOG.md for a release.

The release workflow uses this three ways:

    python packaging/changelog.py check v0.0.2
        Assert the changelog is structurally sound and has a section for this
        version. Runs before anything is tagged, so a release without notes
        fails while it is still free to fix.

    python packaging/changelog.py stamp v0.0.2 --notes release-notes.md
        Write today's date onto the version's heading, in place, and write that
        section's body out for `gh release create --notes-file`.

    python packaging/changelog.py show v0.0.2
        Print the section body to stdout. For looking before you leap.

The structural checks come from a real failure mode in the repo this pattern was
taken from: because a release stamps a date onto the topmost matching heading,
prepending a new section and then rebasing over a release commit can leave an
orphaned, empty, duplicate heading behind — and a naive "is the version present"
check looks it up in a dict, where the duplicate silently shadows the orphan. The
release then ships notes with a stray heading in them. So duplicates and empty
sections are hard errors here, not warnings.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CHANGELOG = REPO / "CHANGELOG.md"

# `## [v0.0.2]` or `## [v0.0.2] - 2026-09-25`
HEADING = re.compile(r"^## \[(v[^\]]+)\]", re.M)

# What a release version may look like. Final releases only -- see
# check_release.py for why prereleases are refused.
VERSION = re.compile(r"^v\d+\.\d+\.\d+$")


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def parse_sections(text: str) -> list[tuple[str, str]]:
    """Every ``## [version]`` section, in file order, as (version, body).

    A list rather than a dict: two headings for the same version are a real and
    otherwise silent failure, and a dict would collapse them.
    """
    matches = list(HEADING.finditer(text))
    sections = []
    for i, match in enumerate(matches):
        # Each section runs from its own heading to the next one, or to EOF.
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[match.start() : end].strip()
        body = "\n".join(chunk.splitlines()[1:]).strip()
        sections.append((match.group(1), body))
    return sections


def validate(text: str) -> list[tuple[str, str]]:
    """Reject a structurally broken changelog before it reaches a release."""
    sections = parse_sections(text)
    if not sections:
        fail(
            f"No `## [vX.Y.Z]` sections found in {CHANGELOG.name}. "
            "The release workflow reads the release notes from there."
        )

    seen: set[str] = set()
    duplicates: list[str] = []
    for version, _ in sections:
        if version in seen and version not in duplicates:
            duplicates.append(version)
        seen.add(version)
    if duplicates:
        fail(
            "Duplicate changelog heading(s) for: "
            + ", ".join(f"## [{v}]" for v in duplicates)
            + "\nEach version must appear exactly once. This usually means a new "
            "section was prepended above a heading a release had already stamped "
            "with a date; merge the two by hand."
        )

    empty = [v for v, body in sections if not body]
    if empty:
        fail(
            "Changelog section(s) with no content: "
            + ", ".join(f"## [{v}]" for v in empty)
            + "\nAn empty section is a leftover heading, not a release note."
        )
    return sections


def section_body(text: str, version: str) -> str:
    bodies = dict(validate(text))
    if version not in bodies:
        fail(
            f"{version} has no section in {CHANGELOG.name}.\n"
            f"Add a `## [{version}]` heading with the notes for this release, "
            "then run the release again."
        )
    return bodies[version]


def stamp_date(text: str, version: str) -> str:
    """Rewrite the version's heading to carry today's date."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = []
    for line in text.splitlines():
        if line.startswith(f"## [{version}]"):
            out.append(f"## [{version}] - {today}")
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("action", choices=["check", "stamp", "show"])
    ap.add_argument("version", help="Release version, e.g. v0.0.2")
    ap.add_argument(
        "--notes",
        type=Path,
        help="stamp only: also write the section body here, for `gh release create --notes-file`.",
    )
    ap.add_argument("--changelog", type=Path, default=CHANGELOG)
    args = ap.parse_args(argv)

    if not VERSION.match(args.version):
        fail(f"{args.version!r} is not a vX.Y.Z version.")
    if not args.changelog.is_file():
        fail(f"{args.changelog} does not exist.")

    text = args.changelog.read_text()
    body = section_body(text, args.version)

    if args.action == "check":
        print(f"ok: {args.version} has changelog notes ({len(body.splitlines())} lines)")
        return 0

    if args.action == "show":
        print(body)
        return 0

    args.changelog.write_text(stamp_date(text, args.version))
    print(f"stamped {args.changelog.name} for {args.version}")
    if args.notes:
        args.notes.write_text(body + "\n")
        print(f"wrote release notes to {args.notes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
