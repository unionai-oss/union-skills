"""Assertions on the release pipeline.

The release process mirrors flyteorg/flyte-agent-plugins: one self-contained
`publish.yml`, triggered by pushing a `v*` tag. There are no reusable workflows
in the release path, which is what keeps it simple — every earlier attempt to
factor it broke in a way only discoverable by trying to cut a release.

These tests exist to keep it that way.
"""

from __future__ import annotations

import pytest
import yaml
from conftest import REPO, builder

WORKFLOWS = REPO / ".github" / "workflows"
PUBLISH = "publish.yml"


def load_workflow(name: str) -> dict:
    data = yaml.safe_load((WORKFLOWS / name).read_text())
    # `on:` is parsed as the YAML boolean True, not the string "on".
    data["triggers"] = data.get(True) or data.get("on") or {}
    return data


def all_workflows() -> list[str]:
    return sorted(p.name for p in WORKFLOWS.glob("*.yml"))


@pytest.mark.parametrize("name", all_workflows())
def test_workflow_is_valid_yaml_with_jobs(name):
    assert load_workflow(name).get("jobs"), f"{name} declares no jobs"


def test_publish_triggers_on_a_version_tag():
    triggers = load_workflow(PUBLISH)["triggers"]
    assert triggers["push"]["tags"] == ["v*"], (
        "publish.yml must trigger on a v* tag push — that push is the release"
    )
    assert "workflow_dispatch" in triggers, "a dry-run rehearsal path is required"


def test_publish_is_self_contained():
    """The release path must not go through a reusable workflow.

    Two independent reasons, both learned the hard way:

    * PyPI trusted publishing matches the OIDC `workflow_ref` claim, which names
      the workflow that was *triggered*, and PyPI cannot name a reusable workflow
      as a publisher at all (pypi/warehouse#11096). Keeping the upload in the
      triggered workflow means the publisher config is exactly `publish.yml`.
    * A called workflow's nested permissions are validated when the file is
      PARSED, so a job requesting more than its caller grants makes the whole
      call an invalid workflow file — regardless of any `if:` on that job.
    """
    for job, spec in load_workflow(PUBLISH)["jobs"].items():
        assert "uses" not in spec, (
            f"publish.yml job '{job}' calls {spec.get('uses')}. The release path "
            "must stay in one triggered workflow; see this test's docstring."
        )


def test_the_pypi_upload_lives_in_publish_with_oidc_and_the_environment():
    jobs = load_workflow(PUBLISH)["jobs"]
    uploaders = [
        (name, spec)
        for name, spec in jobs.items()
        if any(
            "gh-action-pypi-publish" in str(step.get("uses", ""))
            for step in (spec.get("steps") or [])
        )
    ]
    assert uploaders, "publish.yml never uploads to PyPI"
    for name, spec in uploaders:
        assert (spec.get("permissions") or {}).get("id-token") == "write", (
            f"job '{name}' uploads to PyPI but does not request id-token: write, "
            "so the OIDC exchange fails"
        )
        assert spec.get("environment") == "pypi", (
            f"job '{name}' must run in the `pypi` environment — the trusted "
            "publisher is configured against it"
        )


def test_nothing_publishes_without_a_tag_or_an_explicit_opt_in():
    """A manual dispatch defaults to dry_run and must not reach PyPI."""
    jobs = load_workflow(PUBLISH)["jobs"]
    condition = str(jobs["pypi"].get("if", ""))
    assert "github.event_name == 'push'" in condition
    assert "dry_run == false" in condition

    dry_run = load_workflow(PUBLISH)["triggers"]["workflow_dispatch"]["inputs"]["dry_run"]
    assert dry_run["default"] is True, "rehearsing must be the default"


def test_publishing_depends_on_the_build_that_verifies():
    """Nothing reaches PyPI without verify.py and the content lint passing."""
    jobs = load_workflow(PUBLISH)["jobs"]
    assert "build" in (jobs["pypi"].get("needs") or [])
    assert "pypi" in (jobs["release"].get("needs") or [])

    build_steps = " ".join(str(s.get("run", "")) for s in jobs["build"]["steps"])
    assert "packaging/verify.py" in build_steps, "the build job must run verify.py"
    assert "pytest" in build_steps, (
        "the build job must run the content lint — a release is the last place "
        "to discover that a skill links to a page that no longer exists"
    )


def test_the_tag_must_match_the_manifest():
    """A tag that disagrees with the manifest would publish a version nobody can
    trace back to a commit."""
    build = load_workflow(PUBLISH)["jobs"]["build"]
    steps = " ".join(str(s.get("run", "")) for s in build["steps"])
    assert "does not match manifest version" in steps


def test_only_a_tag_push_creates_a_github_release():
    release = load_workflow(PUBLISH)["jobs"]["release"]
    assert "refs/tags/v" in str(release.get("if", ""))
    assert (release.get("permissions") or {}).get("contents") == "write"


def test_version_is_semver_and_consistent_across_manifests():
    """set_version.py writes these three; the tag must match them."""
    import json

    versions = {
        p: json.loads((REPO / p).read_text())["version"]
        for p in (
            "plugins/union/.claude-plugin/plugin.json",
            "plugins/union/.codex-plugin/plugin.json",
            "package.json",
        )
    }
    assert len(set(versions.values())) == 1, versions
    assert builder.version() == next(iter(versions.values()))
