"""Tests for the release gate: changelog handling and version admissibility.

These scripts decide whether a release happens, and they run in a workflow that
pushes a tag and publishes to PyPI immediately afterwards. A tag is awkward to
retract and a PyPI version cannot be replaced at all, so the interesting cases
here are the refusals.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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

# Workflows a human or an event triggers directly. These own every elevated
# permission, and each one is a PyPI trusted-publisher identity.
ENTRY_WORKFLOWS = ["release.yml", "tag-push.yml"]
# Workflows only ever reached through `uses:`.
CALLED_WORKFLOWS = ["ci.yml", "packaging.yml", "build-dists.yml"]

# GitHub's permission ladder. A called workflow's nested job may request at most
# what the calling job grants, and this is checked when the workflow is PARSED --
# an `if:` that would skip the job at runtime does not exempt it. A violation is
# not a failed job, it is "Invalid workflow file", discovered only when someone
# tries to run the thing.
RANK = {None: 0, "none": 0, "read": 1, "write": 2}


def load_workflow(name: str) -> dict:
    data = yaml.safe_load((WORKFLOWS / name).read_text())
    # `on:` is parsed as the YAML boolean True, not the string "on".
    data["triggers"] = data.get(True) or data.get("on") or {}
    return data


@pytest.mark.parametrize("name", ENTRY_WORKFLOWS + CALLED_WORKFLOWS)
def test_workflow_is_valid_yaml_with_jobs(name):
    assert load_workflow(name).get("jobs"), f"{name} declares no jobs"


@pytest.mark.parametrize("name", CALLED_WORKFLOWS)
def test_called_workflows_declare_workflow_call(name):
    """Without `workflow_call` the `uses:` reference is invalid — and that is only
    discoverable after merging to the default branch, where dispatch appears."""
    assert "workflow_call" in load_workflow(name)["triggers"], (
        f"{name} is reused by an entry workflow but does not declare workflow_call"
    )


@pytest.mark.parametrize("entry", ENTRY_WORKFLOWS)
def test_entry_workflows_only_reference_workflows_that_exist(entry):
    for job, spec in load_workflow(entry)["jobs"].items():
        ref = spec.get("uses")
        if not ref:
            continue
        assert ref.startswith("./"), f"{job}: expected a local workflow, got {ref}"
        assert (REPO / ref[2:]).is_file(), f"{job} calls {ref}, which does not exist"


@pytest.mark.parametrize("name", CALLED_WORKFLOWS)
def test_called_workflows_request_no_elevated_permission(name):
    """The invariant that keeps every call site simple.

    This is the bug GitHub rejected once already: `contents: write` on a job in a
    called workflow made the whole call an invalid workflow file, even though an
    `if:` would have skipped that job. Keeping called workflows at `contents:
    read` means no caller has to grant anything, so no caller can get it wrong.
    """
    wf = load_workflow(name)
    for job, spec in wf["jobs"].items():
        for scope, level in (spec.get("permissions") or {}).items():
            assert RANK[level] <= RANK["read"], (
                f"{name} job '{job}' requests {scope}: {level}. Callers grant "
                "called workflows nothing, so anything above `read` makes every "
                "call an invalid workflow file. Move that job to an entry workflow."
            )


def test_called_workflows_fit_within_every_callers_grant():
    """The general form of the rule above, checked against the actual call sites."""
    for entry in ENTRY_WORKFLOWS:
        for job, spec in load_workflow(entry)["jobs"].items():
            ref = spec.get("uses")
            if not ref:
                continue
            granted = spec.get("permissions") or {}
            for nested, nspec in load_workflow(Path(ref).name)["jobs"].items():
                for scope, level in (nspec.get("permissions") or {}).items():
                    assert RANK[level] <= RANK.get(granted.get(scope)), (
                        f"{entry} job '{job}' grants {scope}: "
                        f"{granted.get(scope) or 'none'}, but {ref}'s nested job "
                        f"'{nested}' requests {scope}: {level}. GitHub rejects this "
                        f"at parse time, regardless of any `if:` on '{nested}'."
                    )


@pytest.mark.parametrize("entry", ENTRY_WORKFLOWS)
def test_the_pypi_upload_runs_in_the_entry_workflow(entry):
    """PyPI trusted publishing names a workflow that is *triggered*.

    It matches the OIDC `workflow_ref` claim, and it cannot name a reusable
    workflow at all (pypi/warehouse#11096). An upload that happened inside
    build-dists.yml would make the publisher config ambiguous at best, so the
    upload step has to live here — and needs `id-token: write` to do it.
    """
    jobs = load_workflow(entry)["jobs"]
    uploaders = [
        (name, spec)
        for name, spec in jobs.items()
        if any(
            "gh-action-pypi-publish" in str(step.get("uses", ""))
            for step in (spec.get("steps") or [])
        )
    ]
    assert uploaders, f"{entry} never uploads to PyPI"
    for name, spec in uploaders:
        assert (spec.get("permissions") or {}).get("id-token") == "write", (
            f"{entry} job '{name}' uploads to PyPI but does not request "
            "id-token: write, so the OIDC exchange fails"
        )
        assert spec.get("environment") == "pypi", (
            f"{entry} job '{name}' must run in the `pypi` environment — the "
            "trusted publisher is configured against it"
        )


def test_build_dists_is_never_an_entry_workflow():
    """It has no upload step, so it must not look like a release path."""
    triggers = load_workflow("build-dists.yml")["triggers"]
    assert "push" not in triggers, (
        "build-dists.yml must not trigger on a tag push; tag-push.yml owns that, "
        "because the PyPI upload has to run in the triggered workflow"
    )


@pytest.mark.parametrize("entry", ENTRY_WORKFLOWS)
def test_every_entry_workflow_builds_and_attaches(entry):
    """Both release paths must build from the shared workflow and end with
    artifacts on the GitHub release."""
    jobs = load_workflow(entry)["jobs"]
    assert any("build-dists.yml" in str(s.get("uses", "")) for s in jobs.values()), (
        f"{entry} never calls build-dists.yml, so it would build differently "
        "from the other release path"
    )
    assert any(
        "gh release" in str(step.get("run", ""))
        for s in jobs.values()
        for step in (s.get("steps") or [])
    ), f"{entry} never creates or uploads to a GitHub release"


def test_release_writes_nothing_before_the_checks_pass():
    """The ordering that makes a dry run meaningful.

    Every job that writes — pushes, tags, publishes, uploads — must depend on
    both check workflows, directly or through another job that does.
    """
    jobs = load_workflow("release.yml")["jobs"]

    def deps(job: str, seen=None) -> set:
        seen = seen if seen is not None else set()
        for d in jobs[job].get("needs", []) or []:
            if d not in seen:
                seen.add(d)
                deps(d, seen)
        return seen

    for writer in ("tag", "build", "pypi", "attach"):
        assert {"ci", "packaging"} <= deps(writer), (
            f"{writer} writes but does not transitively depend on ci and packaging"
        )


def test_release_publishes_nothing_on_a_dry_run():
    jobs = load_workflow("release.yml")["jobs"]
    for job in ("build", "attach"):
        assert "released == 'true'" in str(jobs[job].get("if", "")), (
            f"{job} must be gated on the tag job having actually pushed"
        )
    # `pypi` inherits the gate through `needs: [build]`; a skipped dependency
    # skips it too. Assert the chain rather than a duplicated condition.
    assert jobs["pypi"]["needs"] == ["build"]
