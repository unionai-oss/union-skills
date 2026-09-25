"""Unit tests for the installer CLI shipped in the PyPI distribution.

These run against the module imported from a freshly built tree, so they
exercise the real ``importlib.resources`` payload lookup rather than a stand-in.
``packaging/verify.py`` covers the end-to-end install from a wheel; this file
covers the behaviour that is awkward to assert from the outside — target
resolution, overwrite semantics, and the MCP command lines.
"""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest
from conftest import skill_names


def args(**kw) -> Namespace:
    base = {
        "target": None,
        "dir": None,
        "project": False,
        "dry_run": False,
        "force": False,
        "server": None,
        "scope": "user",
    }
    base.update(kw)
    return Namespace(**base)


# ------------------------------------------------------------------- payload


def test_plugin_root_carries_the_payload(cli):
    root = cli.plugin_root()
    assert (root / ".claude-plugin" / "plugin.json").is_file()
    assert (root / ".mcp.json").is_file()
    assert [p.name for p in cli.skill_dirs()] == skill_names()


def test_reference_pages_and_scripts_survive_packaging(cli):
    """Skills link to these at runtime; losing them is silent until then."""
    root = cli.plugin_root()
    assert (root / "skills" / "union-provision-aws" / "references" / "teardown.md").is_file()
    assert (root / "skills" / "union-debug-cluster" / "scripts" / "collect.sh").is_file()


# ------------------------------------------------------------------- install


def test_install_and_uninstall_roundtrip(cli, tmp_path):
    assert cli.cmd_install(args(dir=str(tmp_path))) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == skill_names()
    assert (tmp_path / skill_names()[0] / "SKILL.md").is_file()

    assert cli.cmd_uninstall(args(dir=str(tmp_path))) == 0
    assert list(tmp_path.iterdir()) == []


def test_install_skips_existing_without_force(cli, tmp_path, capsys):
    cli.cmd_install(args(dir=str(tmp_path)))
    marker = tmp_path / skill_names()[0] / "SKILL.md"
    marker.write_text("edited by hand")

    cli.cmd_install(args(dir=str(tmp_path)))
    assert marker.read_text() == "edited by hand"
    assert "skip" in capsys.readouterr().out

    cli.cmd_install(args(dir=str(tmp_path), force=True))
    assert marker.read_text() != "edited by hand"


def test_install_replaces_a_symlink_rather_than_writing_through_it(cli, tmp_path):
    """A skill name occupied by a symlink must not become a write to its target."""
    dest = tmp_path / "skills"
    dest.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (dest / skill_names()[0]).symlink_to(outside, target_is_directory=True)

    cli.cmd_install(args(dir=str(dest), force=True))
    assert not (dest / skill_names()[0]).is_symlink()
    assert list(outside.iterdir()) == []


def test_dry_run_writes_nothing(cli, tmp_path, capsys):
    assert cli.cmd_install(args(dir=str(tmp_path), dry_run=True)) == 0
    assert list(tmp_path.iterdir()) == []
    assert "Dry run" in capsys.readouterr().out


def test_uninstall_leaves_unrelated_files_alone(cli, tmp_path):
    cli.cmd_install(args(dir=str(tmp_path)))
    keep = tmp_path / "someone-elses-skill"
    keep.mkdir()
    (keep / "SKILL.md").write_text("---\nname: someone-elses-skill\n---\n")

    cli.cmd_uninstall(args(dir=str(tmp_path)))
    assert [p.name for p in tmp_path.iterdir()] == ["someone-elses-skill"]


# -------------------------------------------------------------------- targets


def test_codex_is_an_alias_for_agents(cli):
    assert cli.resolve_target("codex") is cli.resolve_target("agents")
    assert "codex" in cli.target_choices()


def test_duplicate_targets_install_once(cli, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    cli.cmd_install(args(target=["codex", "agents"], dry_run=True))
    out = capsys.readouterr().out
    assert out.count("Agent Skills standard") == 1


def test_pi_has_no_project_directory(cli, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert cli.cmd_install(args(target=["pi"], project=True, dry_run=True)) == 1
    assert "no project-level skills directory" in capsys.readouterr().err


def test_detect_finds_harnesses_by_marker_directory(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert cli.detect() == []
    (tmp_path / ".claude").mkdir()
    assert [t.name for t in cli.detect()] == ["claude"]


def test_falls_back_to_claude_when_nothing_is_detected(cli, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    cli.cmd_install(args(dry_run=True))
    assert "defaulting to Claude Code" in capsys.readouterr().err


def test_project_install_is_relative_to_cwd(cli, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cli.cmd_install(args(target=["claude"], project=True))
    assert (tmp_path / ".claude" / "skills" / skill_names()[0] / "SKILL.md").is_file()


# ------------------------------------------------------------------------ mcp


def test_mcp_servers_match_the_bundled_manifest(cli):
    declared = json.loads((cli.plugin_root() / ".mcp.json").read_text())["mcpServers"]
    assert cli.mcp_servers() == declared


def test_claude_add_command_is_add_json_with_scope(cli):
    servers = cli.mcp_servers()
    name, cfg = next(iter(servers.items()))
    cmd = cli.mcp_add_command(cli.MCP_TARGETS["claude"], name, cfg, "user")
    assert cmd[:3] == ["claude", "mcp", "add-json"]
    assert json.loads(cmd[4]) == cfg
    assert cmd[-2:] == ["--scope", "user"]


def test_codex_add_command_splits_http_from_stdio(cli):
    codex = cli.MCP_TARGETS["codex"]
    http = cli.mcp_add_command(codex, "d", {"type": "http", "url": "https://x/mcp"}, "user")
    assert http == ["codex", "mcp", "add", "d", "--url", "https://x/mcp"]

    stdio = cli.mcp_add_command(codex, "c", {"command": "uvx", "args": ["a", "b"]}, "user")
    assert stdio == ["codex", "mcp", "add", "c", "--", "uvx", "a", "b"]


def test_unknown_server_is_rejected(cli):
    with pytest.raises(SystemExit, match="Unknown server"):
        cli.selected_servers(args(server=["nope"]))


def test_mcp_install_is_a_no_op_without_a_harness_cli(cli, monkeypatch, capsys):
    monkeypatch.setattr(cli.shutil, "which", lambda _: None)
    assert cli.cmd_mcp_install(args(dry_run=True)) == 1
    assert "No harness CLI found on PATH" in capsys.readouterr().err


def test_mcp_dry_run_changes_nothing(cli, monkeypatch, capsys):
    monkeypatch.setattr(cli.shutil, "which", lambda b: f"/usr/bin/{b}")

    def explode(*a, **k):  # pragma: no cover - the point is that it is not called
        raise AssertionError("a dry run must not spawn a process")

    monkeypatch.setattr(cli.subprocess, "run", explode)
    assert cli.cmd_mcp_install(args(target=["claude"], dry_run=True)) == 0
    assert "Dry run" in capsys.readouterr().out


# ------------------------------------------------------------------- plumbing


def test_emit_plugin_prints_one_absolute_path(cli, capsys):
    assert cli.cmd_emit_plugin(args()) == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and Path(out.strip()).is_absolute()


def test_version_matches_the_manifest(cli, capsys):
    manifest = json.loads((cli.plugin_root() / ".claude-plugin" / "plugin.json").read_text())
    cli.cmd_version(args())
    assert capsys.readouterr().out.strip() == manifest["version"]


def test_parser_rejects_an_unknown_target(cli):
    with pytest.raises(SystemExit):
        cli.build_parser("union-skills").parse_args(["install", "--target", "nope"])
