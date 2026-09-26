"""Tests for the build fan-out itself.

``packaging/verify.py`` proves the distributions install; this file covers the
generator's own logic — README block stripping, manifest agreement, and the
payload filter — which is cheap to test directly and expensive to debug from a
failed publish.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import REPO, builder, skill_names


def test_version_is_semver_and_consistent():
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


def test_set_version_writes_every_manifest(tmp_path, monkeypatch):
    """set_version.py is the release entry point; a manifest it forgets would
    make the publish workflow's tag check fail at the worst moment."""
    import shutil

    work = tmp_path / "repo"
    (work / "plugins" / "union" / ".claude-plugin").mkdir(parents=True)
    (work / "plugins" / "union" / ".codex-plugin").mkdir(parents=True)
    (work / "packaging").mkdir()
    shutil.copy2(REPO / "packaging" / "set_version.py", work / "packaging")
    for rel in (
        "plugins/union/.claude-plugin/plugin.json",
        "plugins/union/.codex-plugin/plugin.json",
        "package.json",
    ):
        shutil.copy2(REPO / rel, work / rel)

    subprocess.run(
        [sys.executable, str(work / "packaging" / "set_version.py"), "9.8.7"],
        check=True,
        capture_output=True,
    )
    for rel in (
        "plugins/union/.claude-plugin/plugin.json",
        "plugins/union/.codex-plugin/plugin.json",
        "package.json",
    ):
        assert json.loads((work / rel).read_text())["version"] == "9.8.7"


@pytest.mark.parametrize("bad", ["1.2", "v1.2.3", "latest", ""])
def test_set_version_rejects_non_semver(bad, tmp_path):
    r = subprocess.run(
        [sys.executable, str(REPO / "packaging" / "set_version.py"), bad],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2


# --------------------------------------------------------------------- README


def test_readme_blocks_are_stripped_per_registry():
    tmpl = (
        "always\n"
        "<!-- npm-only:start -->\nnpmtext\n<!-- npm-only:end -->\n"
        "<!-- pypi-only:start -->\npypitext\n<!-- pypi-only:end -->\n"
    )
    npm = builder.strip_blocks(tmpl, {"npm"})
    assert "npmtext" in npm and "pypitext" not in npm and "always" in npm

    pypi = builder.strip_blocks(tmpl, {"pypi"})
    assert "pypitext" in pypi and "npmtext" not in pypi

    for out in (npm, pypi):
        assert "only:start" not in out and "only:end" not in out


def test_rendered_readmes_have_no_placeholders_left():
    for registry in ("npm", "pypi"):
        text = builder.render_readme(builder.version(), registry)
        assert "{{" not in text, f"{registry} README has an unsubstituted placeholder"
        assert builder.version() in text or "uvx" in text


def test_pypi_readme_does_not_advertise_npm_installs():
    """Each registry's page should only show instructions that work there."""
    pypi = builder.render_readme(builder.version(), "pypi")
    assert "npx " not in pypi
    assert "uvx union-skills install" in pypi

    npm = builder.render_readme(builder.version(), "npm")
    assert "npx union-skills install" in npm


# --------------------------------------------------------------------- payload


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("build")
    subprocess.run(
        [sys.executable, str(REPO / "packaging" / "build.py"), "--outdir", str(out)],
        check=True,
        capture_output=True,
    )
    return out


def test_npm_package_root_is_the_plugin_root(built):
    """Claude Code's `npm` plugin source requires the manifest at the top level."""
    pkg = built / "npm" / builder.DIST
    assert (pkg / ".claude-plugin" / "plugin.json").is_file()
    assert (pkg / "skills").is_dir()


def test_npm_files_allowlist_covers_the_dot_directories(built):
    """npm's default file selection is unreliable about dot-directories, so the
    allowlist is what actually gets the payload into the tarball."""
    pkg_json = json.loads((built / "npm" / builder.DIST / "package.json").read_text())
    for required in (".claude-plugin/", ".codex-plugin/", ".mcp.json", "skills/", "bin/"):
        assert required in pkg_json["files"]
    assert pkg_json["bin"] == {builder.DIST: "bin/cli.mjs"}
    assert pkg_json["pi"]["skills"] == ["./skills"]


def test_npm_cli_is_executable(built):
    assert (built / "npm" / builder.DIST / "bin" / "cli.mjs").stat().st_mode & 0o111


def test_pypi_tree_vendors_the_plugin_as_package_data(built):
    src = built / "pypi" / builder.DIST / "src" / builder.MODULE
    assert (src / "plugin" / ".claude-plugin" / "plugin.json").is_file()
    assert (src / "cli.py").is_file()
    assert sorted(p.name for p in (src / "plugin" / "skills").iterdir()) == skill_names()


def test_pypi_console_script_matches_the_distribution_name(built):
    pyproject = (built / "pypi" / builder.DIST / "pyproject.toml").read_text()
    assert f'{builder.DIST} = "{builder.MODULE}.cli:main"' in pyproject
    assert f'name = "{builder.DIST}"' in pyproject


def test_module_name_is_importable(built):
    """`union-skills` is not a legal module name; the underscore form must be."""
    assert builder.MODULE.isidentifier()
    assert builder.DIST.replace("-", "_") == builder.MODULE


def test_build_is_idempotent(built, tmp_path):
    """Re-running the build must not accumulate stale files from a prior run."""
    stray = built / "npm" / builder.DIST / "skills" / "stale-skill"
    stray.mkdir()
    (stray / "SKILL.md").write_text("---\nname: stale-skill\n---\n# x\n")

    subprocess.run(
        [
            sys.executable,
            str(REPO / "packaging" / "build.py"),
            "--outdir",
            str(built),
            "--only",
            "npm",
        ],
        check=True,
        capture_output=True,
    )
    assert not stray.exists()


def test_cli_templates_are_copied_verbatim(built):
    """The templates are the single source of truth for both CLIs."""
    assert (built / "npm" / builder.DIST / "bin" / "cli.mjs").read_text() == (
        REPO / "packaging" / "templates" / "cli.mjs"
    ).read_text()
    assert (built / "pypi" / builder.DIST / "src" / builder.MODULE / "cli.py").read_text() == (
        REPO / "packaging" / "templates" / "cli.py"
    ).read_text()
