#!/usr/bin/env python3
"""Build every distribution and prove it installs before we publish it.

Run locally exactly as CI runs it:

    python packaging/verify.py

Checks, on both registries:
  * every manifest agrees on one version;
  * the npm tarball carries the dot-directories Claude Code needs at the package
    root (npm's default file selection is not reliable about those);
  * the built wheel carries the skills as package data;
  * both CLIs install the full skill set into a directory and remove it again;
  * the Python and Node CLIs declare the same harness targets and emit identical
    `mcp` command lines -- they are independent implementations of one contract,
    so drift between them is a real risk.

Content-level checks on the skills themselves (frontmatter, links, the badge
vocabulary) live in tests/ and run under pytest; this file is about packaging.

Requires: node/npm, and either `uv` or `python -m build`.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Load build.py by path rather than `import build`: `build` is also a PyPI
# package, and it is installed here (this file uses it to build wheels), so a
# plain import would resolve by sys.path order.
_spec = importlib.util.spec_from_file_location(
    "union_skills_packaging_build", REPO / "packaging" / "build.py"
)
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"  ok   {message}")
    else:
        print(f"  FAIL {message}")
        FAILURES.append(message)


def run(
    cmd: list[str], cwd: Path | None = None, check: bool = True, **kw
) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, text=True, capture_output=True, **kw)


def check_versions() -> None:
    print("versions")
    versions = {}
    for path in (
        REPO / "plugins/union/.claude-plugin/plugin.json",
        REPO / "plugins/union/.codex-plugin/plugin.json",
        REPO / "package.json",
    ):
        versions[path.relative_to(REPO).as_posix()] = json.loads(path.read_text())["version"]
    check(len(set(versions.values())) == 1, f"one version across manifests: {versions}")


def check_targets(npm_pkg: Path, py_exe: str) -> None:
    """The Python and Node CLIs declare harness targets independently, so a
    target added to one and forgotten in the other is a real drift risk."""
    print("targets")
    node_out = run(
        ["node", str(npm_pkg / "bin" / "cli.mjs"), "install", "--target", "nope"],
        check=False,
    )
    py_out = run([py_exe, "install", "--target", "nope"], check=False)

    def parse(stderr: str) -> set[str]:
        # Both CLIs reject an unknown target by listing the valid ones, but
        # argparse quotes its choices and the Node parser does not.
        listed = stderr.split("choose from ")[-1].split(")")[0]
        return {t.strip().strip("'\"") for t in listed.split(",") if t.strip()}

    node_targets, py_targets = parse(node_out.stderr), parse(py_out.stderr)
    check(
        node_targets == py_targets and len(py_targets) > 1,
        f"both CLIs declare the same targets: {sorted(py_targets)}",
    )


def check_mcp(npm_pkg: Path, py_exe: str) -> None:
    """The `mcp` subcommand builds `claude`/`codex` command lines that reconfigure
    a user's harness, so the two implementations must agree exactly."""
    print("mcp")
    node_cli = str(npm_pkg / "bin" / "cli.mjs")
    declared = set(json.loads((builder.PLUGIN_SRC / ".mcp.json").read_text())["mcpServers"])

    listed = run([py_exe, "mcp", "list"]).stdout
    names = {line.split("\t")[0] for line in listed.strip().splitlines() if line.strip()}
    check(names == declared, f"`mcp list` reports the bundled servers: {sorted(names)}")

    # Both CLIs skip a harness whose binary is absent, and neither `claude` nor
    # `codex` exists on a CI runner -- without stubs every comparison below would
    # be empty-vs-empty and prove nothing. These are never executed: --dry-run
    # prints the command lines instead of running them.
    stub_dir = npm_pkg.parent / "stub-bin"
    stub_dir.mkdir(exist_ok=True)
    for binary in ("claude", "codex"):
        stub = stub_dir / binary
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)
    env = {**os.environ, "PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}"}

    for label, argv in (
        ("list", ["mcp", "list"]),
        (
            "install --target claude",
            ["mcp", "install", "--target", "claude", "--dry-run"],
        ),
        ("install --target codex", ["mcp", "install", "--target", "codex", "--dry-run"]),
        ("install (auto-detect)", ["mcp", "install", "--dry-run"]),
        ("uninstall", ["mcp", "uninstall", "--target", "claude", "--dry-run"]),
    ):
        py = run([py_exe, *argv], check=False, env=env).stdout
        node = run(["node", node_cli, *argv], check=False, env=env).stdout
        check(py == node and py.strip() != "", f"both CLIs emit identical `{label}`")


def check_npm(pkg: Path, workdir: Path) -> None:
    dist = builder.DIST
    print(f"npm {dist}")
    out = run(["npm", "pack", "--dry-run", "--json"], cwd=pkg).stdout
    files = {f["path"] for f in json.loads(out)[0]["files"]}
    for required in (
        ".claude-plugin/plugin.json",
        ".codex-plugin/plugin.json",
        ".mcp.json",
        "bin/cli.mjs",
    ):
        check(required in files, f"tarball contains {required}")
    packed = {f.split("/")[1] for f in files if f.startswith("skills/")}
    check(
        packed == set(builder.skill_names()),
        f"tarball contains all {len(builder.skill_names())} skills",
    )

    dest = workdir / f"npm-{dist}"
    cli = str(pkg / "bin" / "cli.mjs")
    run(["node", cli, "install", "--dir", str(dest)])
    installed = sorted(p.name for p in dest.iterdir() if (p / "SKILL.md").is_file())
    check(installed == builder.skill_names(), f"`{dist} install --dir` writes every skill")
    run(["node", cli, "uninstall", "--dir", str(dest)])
    check(not any(dest.iterdir()), f"`{dist} uninstall --dir` removes them again")
    check(
        run(["node", cli, "version"]).stdout.strip() == builder.version(),
        "`version` matches manifest",
    )
    emitted = run(["node", cli, "emit-plugin"]).stdout
    check(
        emitted.count("\n") == 1 and Path(emitted.strip()).is_absolute(),
        "`emit-plugin` prints exactly one absolute path",
    )


def build_wheel(pkg: Path) -> Path:
    try:
        run([sys.executable, "-m", "build", "--wheel"], cwd=pkg)
    except (subprocess.CalledProcessError, FileNotFoundError):
        run(["uv", "build", "--wheel"], cwd=pkg)
    return next((pkg / "dist").glob("*.whl"))


def check_pypi(pkg: Path, workdir: Path, npm_pkg: Path) -> None:
    dist, mod = builder.DIST, builder.MODULE
    print(f"pypi {dist}")
    wheel = build_wheel(pkg)

    names = set(zipfile.ZipFile(wheel).namelist())
    check(
        f"{mod}/plugin/.claude-plugin/plugin.json" in names,
        "wheel contains .claude-plugin/plugin.json",
    )
    check(f"{mod}/plugin/.mcp.json" in names, "wheel contains .mcp.json")
    packed = {n.split("/")[3] for n in names if n.startswith(f"{mod}/plugin/skills/")}
    check(
        packed == set(builder.skill_names()),
        f"wheel contains all {len(builder.skill_names())} skills",
    )
    # Non-SKILL.md payload (reference pages, scripts) is easy to lose to a
    # packaging filter, and its absence only shows up when an agent follows a
    # link at runtime.
    check(
        any(n.endswith("references/teardown.md") for n in names),
        "wheel contains skill reference pages",
    )
    check(
        any(n.endswith("scripts/collect.sh") for n in names),
        "wheel contains skill scripts",
    )

    venv = workdir / f"venv-{dist}"
    if shutil.which("uv"):
        run(["uv", "venv", "--quiet", str(venv)])
        run(["uv", "pip", "install", "--quiet", "--python", str(venv / "bin/python"), str(wheel)])
    else:
        run([sys.executable, "-m", "venv", str(venv)])
        run([str(venv / "bin/pip"), "install", "--quiet", str(wheel)])

    exe = str(venv / "bin" / dist)
    dest = workdir / f"pypi-{dist}"
    run([exe, "install", "--dir", str(dest)])
    installed = sorted(p.name for p in dest.iterdir() if (p / "SKILL.md").is_file())
    check(installed == builder.skill_names(), f"`{dist} install --dir` writes every skill")
    run([exe, "uninstall", "--dir", str(dest)])
    check(not any(dest.iterdir()), f"`{dist} uninstall --dir` removes them again")
    check(
        run([exe, "version"]).stdout.strip() == builder.version(),
        "`version` matches manifest",
    )
    emitted = run([exe, "emit-plugin"]).stdout
    check(
        emitted.count("\n") == 1 and Path(emitted.strip()).is_absolute(),
        "`emit-plugin` prints exactly one absolute path",
    )
    check_targets(npm_pkg, exe)
    check_mcp(npm_pkg, exe)


def main() -> int:
    check_versions()

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        outdir = workdir / "build"
        subprocess.run(
            [sys.executable, str(REPO / "packaging/build.py"), "--outdir", str(outdir)],
            check=True,
        )
        npm_pkg = outdir / "npm" / builder.DIST
        check_npm(npm_pkg, workdir)
        check_pypi(outdir / "pypi" / builder.DIST, workdir, npm_pkg)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
