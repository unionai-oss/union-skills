"""Content lint for the skill payload.

These are the checks that catch the failures a packaging test cannot see: a
skill that loads but points at a dead reference page, a badge vocabulary that
drifts so the agent stops recognising approval gates, a docs link left pointing
at a preview deployment, or a credential pasted into an example.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import PLUGIN, SKILLS, markdown_files, skill_dirs, skill_names

# The badge vocabulary the skills define in union-self-serve and rely on
# everywhere else. Adding one means teaching the agent a new convention, so it
# has to be a deliberate edit here rather than an accident in one file.
BADGES = {"🟢 READ-ONLY", "⛔ APPROVAL GATE", "📤 TO THE UI", "📥 FROM THE UI", "🔐 SECRET"}

# Commands that create, modify or destroy something. A skill that runs any of
# these must also carry the approval-gate vocabulary.
MUTATING = re.compile(
    r"\b(?:"
    r"eksctl (?:create|delete|utils associate)"
    r"|aws (?:eks (?:create|delete|update-kubeconfig)|s3api (?:create|put|delete)"
    r"|ecr (?:create|set|delete)|iam (?:create|put|delete|update|attach|detach))"
    r"|helm (?:upgrade|install|uninstall)"
    r")\b"
)

SECRETS = [
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), "AWS access key id"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key block"),
    (re.compile(r"\baws_secret_access_key\s*=\s*['\"]?[A-Za-z0-9/+=]{40}"), "AWS secret key"),
    (re.compile(r"\bghp_[A-Za-z0-9]{36}\b"), "GitHub token"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\."), "JWT"),
]

# Docs must point at the published site, never at a preview or staging build.
BAD_DOC_HOSTS = re.compile(r"https?://[^\s)\"']*(?:docs-dog\.pages\.dev|\.vercel\.app|localhost)")

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

BADGE_EMOJI = "🟢⛔📤📥🔐"
# Markdown emphasis between the emoji and its label is presentation, not
# vocabulary: `⛔ **APPROVAL GATE**` is the same badge as `⛔ APPROVAL GATE`.
_EMPHASIS = re.compile(rf"([{BADGE_EMOJI}] ?)[*_]+")


def normalize_badges(text: str) -> str:
    return _EMPHASIS.sub(r"\1", text)


def frontmatter(text: str) -> dict[str, str]:
    """Parse the flat ``key: value`` YAML frontmatter a SKILL.md carries."""
    assert text.startswith("---\n"), "SKILL.md must open with YAML frontmatter"
    body = text.split("---\n", 2)
    assert len(body) == 3, "frontmatter is not terminated by a second ---"
    out: dict[str, str] = {}
    for line in body[1].splitlines():
        if not line.strip() or line.startswith(("#", " ", "\t")):
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        out[key.strip()] = value
    return out


# --------------------------------------------------------------------- layout


def test_skills_exist():
    names = skill_names()
    assert names, "no skills found"
    # Every directory under skills/ must actually be a skill.
    dirs = sorted(p.name for p in SKILLS.iterdir() if p.is_dir())
    assert dirs == names, f"directories without a SKILL.md: {set(dirs) - set(names)}"


@pytest.mark.parametrize("skill", skill_dirs(), ids=skill_names())
def test_frontmatter(skill: Path):
    fm = frontmatter((skill / "SKILL.md").read_text())

    assert fm.get("name") == skill.name, "frontmatter name must equal the directory name"
    assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", skill.name), "name must be kebab-case"
    assert skill.name.startswith("union-"), (
        "skills install alongside other vendors' skills in one directory, so the "
        "names must stay namespaced"
    )

    desc = fm.get("description", "")
    assert desc, "description is required — it is the only thing the agent sees when routing"
    # Long enough to route on, short enough that harnesses keep it whole.
    assert 60 <= len(desc) <= 1024, f"description is {len(desc)} chars; keep it 60–1024"
    assert not desc.endswith(":"), "description looks truncated"

    assert set(fm) <= {"name", "description", "license", "allowed-tools"}, (
        f"unexpected frontmatter keys: {set(fm) - {'name', 'description'}}"
    )


@pytest.mark.parametrize("skill", skill_dirs(), ids=skill_names())
def test_skill_has_a_title(skill: Path):
    body = (skill / "SKILL.md").read_text().split("---\n", 2)[2]
    assert re.search(r"^# \S", body, re.M), "SKILL.md needs a top-level heading"


# ---------------------------------------------------------------- correctness


@pytest.mark.parametrize("path", markdown_files(), ids=lambda p: str(p.relative_to(SKILLS)))
def test_code_fences_balanced(path: Path):
    opens = [ln for ln in path.read_text().splitlines() if ln.startswith("```")]
    assert len(opens) % 2 == 0, (
        f"unbalanced ``` fences ({len(opens)}) — an unterminated fence swallows "
        "the rest of the file when the agent reads it"
    )


@pytest.mark.parametrize("path", markdown_files(), ids=lambda p: str(p.relative_to(SKILLS)))
def test_no_secrets(path: Path):
    text = path.read_text()
    for pattern, label in SECRETS:
        assert not pattern.search(text), f"looks like a committed {label}"


@pytest.mark.parametrize("path", markdown_files(), ids=lambda p: str(p.relative_to(SKILLS)))
def test_docs_links_point_at_production(path: Path):
    bad = BAD_DOC_HOSTS.findall(path.read_text())
    assert not bad, f"links to a preview or local host: {bad}"


@pytest.mark.parametrize("path", markdown_files(), ids=lambda p: str(p.relative_to(SKILLS)))
def test_relative_links_resolve(path: Path):
    missing = []
    for href in LINK.findall(path.read_text()):
        if href.startswith(("http://", "https://", "#", "mailto:")):
            continue
        target = (path.parent / href.split("#", 1)[0]).resolve()
        if not target.exists():
            missing.append(href)
    assert not missing, f"relative links with no target: {missing}"


@pytest.mark.parametrize("path", markdown_files(), ids=lambda p: str(p.relative_to(SKILLS)))
def test_no_unresolved_placeholders(path: Path):
    text = path.read_text()
    # Only build-template markers -- `{{Key:...}}` is legitimate JMESPath inside
    # a Python f-string, and the skills use it.
    assert not re.search(r"\{\{[A-Z_]+\}\}", text), "build template placeholder left in a skill"
    for marker in ("TODO", "FIXME", "XXX:"):
        assert marker not in text, f"{marker} left in a shipped skill"


def test_cross_skill_references_resolve():
    """A skill that routes to `union-foo` must be routing to a skill that exists."""
    known = set(skill_names())
    referenced: dict[str, set[str]] = {}
    for path in markdown_files():
        found = set(re.findall(r"`(union-[a-z0-9-]+)`", path.read_text()))
        # `union-system` and friends are Kubernetes service accounts, not skills.
        found = {f for f in found if f.startswith("union-") and f not in known}
        if found:
            referenced[str(path.relative_to(SKILLS))] = found
    unknown = {
        f: v
        for f, v in referenced.items()
        if v - {"union-system", "union-selfserve", "union-task-access", "union-system-access"}
    }
    assert not unknown, f"references to skills that do not exist: {unknown}"


# ------------------------------------------------------------------- protocol


@pytest.mark.parametrize("skill", skill_dirs(), ids=skill_names())
def test_badge_vocabulary_is_closed(skill: Path):
    """Only the documented badges may appear, so the agent's cue never drifts."""
    text = normalize_badges((skill / "SKILL.md").read_text())
    used = set(re.findall(rf"[{BADGE_EMOJI}][^\n`]{{0,24}}", text))
    for token in used:
        assert any(token.startswith(b) for b in BADGES), (
            f"undocumented badge {token!r} — the vocabulary is defined in "
            "union-self-serve and must stay closed. Every badge emoji must be "
            "followed by its canonical label."
        )


@pytest.mark.parametrize("skill", skill_dirs(), ids=skill_names())
def test_mutating_commands_are_gated(skill: Path):
    """A skill that creates cloud resources must carry the approval-gate badge.

    This is the safety property the whole design rests on: an agent running
    `eksctl create cluster` with no gate is the failure mode these skills exist
    to prevent.
    """
    text = normalize_badges((skill / "SKILL.md").read_text())
    if not MUTATING.search(text):
        pytest.skip("no mutating commands in this skill")
    assert "⛔ APPROVAL GATE" in text, (
        "this skill runs resource-creating commands but never names an approval gate"
    )


def test_self_serve_defines_the_shared_conventions():
    """The router skill is where the conventions are defined; keep them there."""
    text = normalize_badges((SKILLS / "union-self-serve" / "SKILL.md").read_text())
    for badge in BADGES:
        assert badge in text, f"{badge} is used elsewhere but not defined in union-self-serve"
    assert "UNION_ENV_FILE" in text, "the state-file convention must be defined here"


@pytest.mark.parametrize(
    "skill",
    [s for s in skill_dirs() if s.name != "union-self-serve"],
    ids=[s.name for s in skill_dirs() if s.name != "union-self-serve"],
)
def test_state_file_is_sourced_not_assumed(skill: Path):
    """Skills that read state must source the file, because the shell is fresh.

    An agent's Bash calls do not share environment. A skill that interpolates
    `$CLUSTER_NAME` without sourcing gets an empty string and builds a resource
    name out of nothing.
    """
    text = (skill / "SKILL.md").read_text()
    if "UNION_ENV_FILE" not in text:
        pytest.skip("this skill does not use shared state")
    assert re.search(r'source "\$\{UNION_ENV_FILE', text), (
        "uses UNION_ENV_FILE but never sources it"
    )


# ------------------------------------------------------------------- payload


def test_scripts_are_executable_and_valid():
    scripts = sorted(SKILLS.rglob("scripts/*.sh"))
    assert scripts, "expected at least one bundled script"
    for script in scripts:
        assert script.stat().st_mode & 0o111, f"{script.name} is not executable"
        assert script.read_text().startswith("#!"), f"{script.name} has no shebang"
        subprocess.run(["bash", "-n", str(script)], check=True, capture_output=True)


def test_manifests_are_valid_json_and_agree():
    claude = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    codex = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text())
    assert claude["name"] == codex["name"] == "union"
    assert claude["version"] == codex["version"]
    assert claude["description"] == codex["description"]


def test_mcp_servers_are_well_formed():
    servers = json.loads((PLUGIN / ".mcp.json").read_text())["mcpServers"]
    assert servers, "no MCP servers declared"
    for name, cfg in servers.items():
        if cfg.get("type") == "http" or "url" in cfg:
            assert cfg["url"].startswith("https://"), f"{name}: MCP URL must be https"
        else:
            assert cfg.get("command"), f"{name}: stdio server needs a command"
            assert isinstance(cfg.get("args", []), list), f"{name}: args must be a list"


# ------------------------------------------------------- the snapshot script


COLLECT = SKILLS / "union-debug-cluster" / "scripts" / "collect.sh"

# Anchored at a line start: "redact()" also appears in the header comment.
REDACT_FN = re.compile(r"^redact\(\) \{.*?^\}", re.M | re.S)


def redact_source() -> str:
    m = REDACT_FN.search(COLLECT.read_text())
    assert m, "collect.sh no longer defines redact()"
    return m.group(0)


# Exactly the utilities collect.sh calls. The PATH is built from these alone so
# that kubectl/aws/helm are genuinely absent -- a GitHub runner ships kubectl in
# /usr/bin, so "PATH=stub:/usr/bin" would not have tested what it claimed to.
COLLECT_NEEDS = (
    "sed",
    "grep",
    "awk",
    "date",
    "seq",
    "wc",
    "tr",
    "head",
    "cut",
    "sort",
    "cat",
    "tee",
)


def run_collect(tmp_path: Path, env_extra: dict[str, str] | None = None):
    """Run collect.sh with a PATH holding only coreutils — no kubectl, no aws.

    Degrading cleanly is the property that matters: the script runs on whatever
    laptop the user happens to have, and a stack trace instead of a report is
    worse than no report.
    """
    stub = tmp_path / "bin"
    stub.mkdir()
    for tool in COLLECT_NEEDS:
        found = shutil.which(tool)
        if found:
            (stub / tool).symlink_to(found)
    assert not (stub / "kubectl").exists()

    env = {
        "PATH": str(stub),
        "HOME": str(tmp_path),
        "UNION_ENV_FILE": str(tmp_path / "absent.env"),
        **(env_extra or {}),
    }
    bash = shutil.which("bash")
    assert bash, "bash is required to run the snapshot script"
    return subprocess.run(
        [bash, str(COLLECT)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60
    )


def test_collect_degrades_without_kubectl(tmp_path):
    r = run_collect(tmp_path)
    assert "no cluster checks are possible" in r.stdout
    assert "summary:" in r.stdout
    assert "Traceback" not in r.stderr and "syntax error" not in r.stderr


def test_collect_reads_the_state_file(tmp_path):
    env_file = tmp_path / "state.env"
    env_file.write_text("export CLUSTER_NAME=my-cluster\n")
    r = run_collect(tmp_path, {"UNION_ENV_FILE": str(env_file)})
    assert str(env_file) in r.stdout
    assert "(absent)" not in r.stdout


def test_collect_redacts_identifiers(tmp_path):
    """The redaction is what makes a report safe to paste into a ticket."""
    body = redact_source()
    probe = (
        "arn:aws:eks:us-east-2:123456789012:cluster/c\n"
        "123456789012.dkr.ecr.us-east-2.amazonaws.com/r\n"
        "?X-Amz-Signature=deadbeefcafebabe&n=1\n"
        "AKIAIOSFODNN7EXAMPLE\n"
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig\n"
        "-----BEGIN RSA PRIVATE KEY-----\n"
    )
    r = subprocess.run(
        ["bash", "-c", f"{body}\nredact"],
        input=probe,
        capture_output=True,
        text=True,
        check=True,
    )
    out = r.stdout
    assert "123456789012:cluster" not in out and "<ACCOUNT-ID>:cluster" in out
    assert "123456789012.dkr.ecr" not in out
    assert "deadbeefcafebabe" not in out
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "eyJzdWIiOiIxIn0" not in out
    assert "BEGIN RSA PRIVATE KEY" not in out


def test_collect_avoids_gnu_only_sed_constructs():
    """It has to work unchanged on a stock macOS, where BSD sed has neither."""
    body = redact_source()
    assert "\\b" not in body, "BSD sed does not support \\b word boundaries"
    assert not re.search(r"/[a-z]*I[a-z]*'", body), "BSD sed does not support the I flag"


# --------------------------------------------------------------- shell blocks


SHELL_FENCE = re.compile(r"^```(?:bash|sh|shell)\n(.*?)^```", re.M | re.S)
# A `<placeholder>` used as a bare shell word is a redirect, not a placeholder.
# `--nodegroup-name <ng> --query ...` parses fine and silently creates a file
# called `--query`, which is worse than a syntax error.
BARE_PLACEHOLDER = re.compile(r"(?<![\"'\w=/])<[A-Za-z][A-Za-z0-9 _-]*>")
QUOTED_SPAN = re.compile(r"'[^']*'|\"[^\"]*\"")


def shell_blocks(path: Path) -> list[str]:
    return SHELL_FENCE.findall(path.read_text())


@pytest.mark.parametrize("path", markdown_files(), ids=lambda p: str(p.relative_to(SKILLS)))
def test_shell_blocks_parse(path: Path):
    """Every shell block must be syntactically valid.

    An agent runs these verbatim. A block that does not parse produces a shell
    syntax error rather than a useful failure, and the agent then has to guess
    whether the command or the cluster is at fault.
    """
    for i, block in enumerate(shell_blocks(path)):
        r = subprocess.run(["bash", "-n"], input=block, capture_output=True, text=True)
        assert r.returncode == 0, f"block {i} does not parse:\n{r.stderr}\n{block[:400]}"


@pytest.mark.parametrize("path", markdown_files(), ids=lambda p: str(p.relative_to(SKILLS)))
def test_placeholders_in_shell_blocks_are_quoted(path: Path):
    offenders = []
    for i, block in enumerate(shell_blocks(path)):
        for line in block.splitlines():
            if line.strip().startswith("#"):
                continue
            for hit in BARE_PLACEHOLDER.findall(QUOTED_SPAN.sub("", line)):
                offenders.append(f"block {i}: {hit} in {line.strip()[:80]}")
    assert not offenders, (
        'unquoted <placeholder> is parsed as a redirect; write "<placeholder>":\n  '
        + "\n  ".join(offenders)
    )
