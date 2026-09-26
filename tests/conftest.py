"""Shared fixtures: the repo layout, and the built PyPI tree the CLI tests import."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "plugins" / "union"
SKILLS = PLUGIN / "skills"


def _load_builder():
    """Load packaging/build.py under an unambiguous name.

    `import build` would be ambiguous: `build` is also a PyPI package, and it is
    installed wherever this repo's own tooling runs. Which one wins then depends
    on sys.path order -- and isort classifies the name differently depending on
    whether the PyPI package happens to be installed, so even the linter's
    verdict changes between machines. Loading by path removes both problems.
    """
    path = REPO / "packaging" / "build.py"
    spec = importlib.util.spec_from_file_location("union_skills_packaging_build", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


builder = _load_builder()


def skill_dirs() -> list[Path]:
    return sorted(p for p in SKILLS.iterdir() if (p / "SKILL.md").is_file())


def skill_names() -> list[str]:
    return [p.name for p in skill_dirs()]


def markdown_files() -> list[Path]:
    """Every markdown file in the plugin payload: SKILL.md files and references."""
    return sorted(SKILLS.rglob("*.md"))


@pytest.fixture(scope="session")
def built_pypi(tmp_path_factory) -> Path:
    """Build the PyPI source tree once and return its ``src`` directory.

    The CLI resolves its payload through ``importlib.resources``, so it can only
    be imported from a generated tree where ``plugin/`` sits inside the package.
    """
    out = tmp_path_factory.mktemp("build")
    subprocess.run(
        [
            sys.executable,
            str(REPO / "packaging" / "build.py"),
            "--outdir",
            str(out),
            "--only",
            "pypi",
        ],
        check=True,
        capture_output=True,
    )
    return out / "pypi" / "union-skills" / "src"


@pytest.fixture(scope="session")
def cli(built_pypi):
    """The installer CLI module, imported from the built tree."""
    sys.path.insert(0, str(built_pypi))
    try:
        import union_skills.cli as mod
    finally:
        sys.path.remove(str(built_pypi))
    return mod
