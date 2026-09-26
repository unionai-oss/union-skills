"""Tests for the release gate: changelog handling and version admissibility.

These scripts decide whether a release happens, and they run in a workflow that
pushes a tag and publishes to PyPI immediately afterwards. A tag is awkward to
retract and a PyPI version cannot be replaced at all, so the interesting cases
here are the refusals.
"""

from __future__ import annotations

import subprocess
import sys

import pytest
import yaml
from conftest import REPO

CHANGELOG_PY = REPO / "packaging" / "changelog.py"
CHECK_PY = REPO / "packaging" / "check_release.py"


def run(script, *args, **kw):
    return subprocess.run(
        [sys.executable, str(script), *args], capture_output=True, text=True, **kw
    )


# ------------------------------------------------------------------ changelog


def write_changelog(tmp_path, body: str):
    p = tmp_path / "CHANGELOG.md"
    p.write_text(body)
    return p


GOOD = """# Changelog

## [v0.0.2]

### Added

- A thing.

## [v0.0.1] - 2026-09-25

First release.
"""


def test_check_accepts_a_version_with_notes(tmp_path):
    cl = write_changelog(tmp_path, GOOD)
    r = run(CHANGELOG_PY, "check", "v0.0.2", "--changelog", str(cl))
    assert r.returncode == 0, r.stderr
    assert "has changelog notes" in r.stdout


def test_check_rejects_a_version_with_no_section(tmp_path):
    cl = write_changelog(tmp_path, GOOD)
    r = run(CHANGELOG_PY, "check", "v0.9.9", "--changelog", str(cl))
    assert r.returncode == 1
    assert "has no section" in r.stderr


def test_check_rejects_a_duplicate_heading(tmp_path):
    """The failure this whole validation exists for.

    A release stamps a date onto the topmost matching heading, so prepending a
    section and then rebasing over a release commit can leave an orphaned empty
    duplicate. A dict-based lookup would silently shadow it and ship notes with
    a stray heading in them.
    """
    cl = write_changelog(
        tmp_path,
        "# Changelog\n\n## [v0.0.2]\n\n## [v0.0.2] - 2026-09-25\n\nNotes.\n",
    )
    r = run(CHANGELOG_PY, "check", "v0.0.2", "--changelog", str(cl))
    assert r.returncode == 1
    assert "Duplicate changelog heading" in r.stderr


def test_check_rejects_an_empty_section(tmp_path):
    cl = write_changelog(tmp_path, "# Changelog\n\n## [v0.0.2]\n\n## [v0.0.1]\n\nNotes.\n")
    r = run(CHANGELOG_PY, "check", "v0.0.2", "--changelog", str(cl))
    assert r.returncode == 1
    assert "no content" in r.stderr


def test_check_rejects_a_changelog_with_no_sections(tmp_path):
    cl = write_changelog(tmp_path, "# Changelog\n\nNothing structured here.\n")
    r = run(CHANGELOG_PY, "check", "v0.0.2", "--changelog", str(cl))
    assert r.returncode == 1
    assert "No `## [vX.Y.Z]` sections" in r.stderr


def test_show_prints_only_the_section_body(tmp_path):
    cl = write_changelog(tmp_path, GOOD)
    r = run(CHANGELOG_PY, "show", "v0.0.2", "--changelog", str(cl))
    assert r.returncode == 0
    assert "A thing." in r.stdout
    # Neither the heading nor the neighbouring release may leak into the notes.
    assert "## [v0.0.2]" not in r.stdout
    assert "First release" not in r.stdout


def test_stamp_dates_the_heading_and_writes_the_notes(tmp_path):
    cl = write_changelog(tmp_path, GOOD)
    notes = tmp_path / "notes.md"
    r = run(CHANGELOG_PY, "stamp", "v0.0.2", "--changelog", str(cl), "--notes", str(notes))
    assert r.returncode == 0, r.stderr

    updated = cl.read_text()
    assert "## [v0.0.2] - " in updated
    # An already-dated heading must not be touched a second time.
    assert updated.count("## [v0.0.1] - 2026-09-25") == 1
    assert "A thing." in notes.read_text()


def test_stamp_is_idempotent(tmp_path):
    """Re-running a release must not append a second date to the heading."""
    cl = write_changelog(tmp_path, GOOD)
    for _ in range(2):
        assert run(CHANGELOG_PY, "stamp", "v0.0.2", "--changelog", str(cl)).returncode == 0
    line = next(ln for ln in cl.read_text().splitlines() if ln.startswith("## [v0.0.2]"))
    assert line.count(" - ") == 1, line


@pytest.mark.parametrize("bad", ["0.0.2", "v0.0", "latest", "v0.0.2rc1"])
def test_changelog_rejects_malformed_versions(bad, tmp_path):
    cl = write_changelog(tmp_path, GOOD)
    r = run(CHANGELOG_PY, "check", bad, "--changelog", str(cl))
    assert r.returncode == 1


def test_repo_changelog_is_valid_and_covers_the_current_version():
    """The shipped CHANGELOG must always be releasable as-is."""
    from conftest import builder

    version = f"v{builder.version()}"
    r = run(CHANGELOG_PY, "check", version)
    assert r.returncode == 0, f"CHANGELOG.md has no notes for {version}:\n{r.stderr}"


# -------------------------------------------------------------- check_release


def test_accepts_a_forward_version():
    r = run(CHECK_PY, "v99.0.0", "--skip-tag-check")
    assert r.returncode == 0, r.stderr
    assert "releasable" in r.stdout


def test_rejects_going_backwards():
    r = run(CHECK_PY, "v0.0.0", "--skip-tag-check")
    assert r.returncode == 1
    assert "older than the current version" in r.stderr


def test_rejects_the_current_version_unless_allowed():
    from conftest import builder

    current = f"v{builder.version()}"
    r = run(CHECK_PY, current, "--skip-tag-check")
    assert r.returncode == 1
    assert "already the version in the manifests" in r.stderr

    r = run(CHECK_PY, current, "--skip-tag-check", "--allow-same")
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("bad", ["0.0.2", "v0.0", "v0.0.2.1", "release-1", ""])
def test_rejects_malformed_versions(bad):
    r = run(CHECK_PY, bad, "--skip-tag-check")
    assert r.returncode != 0


@pytest.mark.parametrize("pre", ["v0.1.0rc1", "v0.1.0a1", "v0.1.0b2", "v0.1.0-rc.1"])
def test_rejects_prereleases_with_the_reason(pre):
    """Prereleases are refused on purpose, and the message has to say why.

    PEP 440 and npm semver spell them differently, and one version string is
    written into both a pyproject.toml and a package.json — so `npm pack` would
    reject it and the packaging job would fail after the tag was already pushed.
    """
    r = run(CHECK_PY, pre, "--skip-tag-check")
    assert r.returncode == 1
    assert "prerelease" in r.stderr
    assert "npm" in r.stderr


def test_rejects_a_tag_that_already_exists(tmp_path):
    """Guards the one mistake that cannot be undone: PyPI versions are immutable."""
    r = run(CHECK_PY, "v99.0.0", cwd=REPO)
    assert r.returncode == 0, r.stderr  # v99 does not exist, so this passes

    # Now prove the check actually consults git, using a tag that does exist.
    subprocess.run(["git", "tag", "v98.0.0"], cwd=REPO, check=True, capture_output=True)
    try:
        r = run(CHECK_PY, "v98.0.0")
        assert r.returncode == 1
        assert "already exists locally" in r.stderr
    finally:
        subprocess.run(["git", "tag", "-d", "v98.0.0"], cwd=REPO, check=True, capture_output=True)


# ------------------------------------------------------------------ workflows


WORKFLOWS = REPO / ".github" / "workflows"


def load_workflow(name: str) -> dict:
    data = yaml.safe_load((WORKFLOWS / name).read_text())
    # `on:` is parsed as the YAML boolean True, not the string "on".
    data["triggers"] = data.get(True) or data.get("on") or {}
    return data


@pytest.mark.parametrize("name", ["ci.yml", "packaging.yml", "publish.yml", "release.yml"])
def test_workflow_is_valid_yaml_with_jobs(name):
    wf = load_workflow(name)
    assert wf.get("jobs"), f"{name} declares no jobs"


@pytest.mark.parametrize("name", ["ci.yml", "packaging.yml", "publish.yml"])
def test_called_workflows_declare_workflow_call(name):
    """release.yml reuses these. Without `workflow_call` the release cannot run
    the same checks a PR does, and the `uses:` reference fails at dispatch time —
    which is only discoverable after merging to the default branch."""
    assert "workflow_call" in load_workflow(name)["triggers"], (
        f"{name} is reused by release.yml but does not declare workflow_call"
    )


def test_release_only_references_workflows_that_exist():
    for job, spec in load_workflow("release.yml")["jobs"].items():
        ref = spec.get("uses")
        if not ref:
            continue
        assert ref.startswith("./"), f"{job}: expected a local workflow, got {ref}"
        assert (REPO / ref[2:]).is_file(), f"{job} calls {ref}, which does not exist"


def test_release_grants_id_token_to_the_publish_call():
    """A reusable workflow can never hold more permission than its caller.

    publish.yml declares `id-token: write` for PyPI's OIDC exchange, but that is
    capped by the calling job's grant — so omitting it here does not fail loudly,
    it fails at the upload with an auth error after the tag is already pushed.
    """
    publish = load_workflow("release.yml")["jobs"]["publish"]
    assert publish.get("permissions", {}).get("id-token") == "write", (
        "release.yml's publish job must grant id-token: write, or trusted "
        "publishing fails after the tag has been pushed"
    )


def test_nothing_is_written_before_the_checks_pass():
    """The ordering that makes a dry run meaningful.

    Every job that writes (pushes, tags, publishes, uploads) must depend on both
    check workflows, directly or through another job that does.
    """
    jobs = load_workflow("release.yml")["jobs"]

    def deps(job: str, seen=None) -> set:
        seen = seen or set()
        for d in jobs[job].get("needs", []) or []:
            if d not in seen:
                seen.add(d)
                deps(d, seen)
        return seen

    for writer in ("tag", "publish", "attach"):
        assert {"ci", "packaging"} <= deps(writer), (
            f"{writer} writes but does not transitively depend on ci and packaging"
        )


def test_publish_is_skipped_on_a_dry_run():
    jobs = load_workflow("release.yml")["jobs"]
    for job in ("publish", "attach"):
        assert "released == 'true'" in str(jobs[job].get("if", "")), (
            f"{job} must be gated on the tag job having actually pushed"
        )
