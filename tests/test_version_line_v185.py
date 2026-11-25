"""One build, one version — and the release flow has to believe it.

The version number is written into the package metadata, the lock file, the
engine, the two MCP server identities, the two plugin manifests and the Agent
Skill. When they disagree, the MCP server reports one version and the package
another, and a release tag can land on a commit whose metadata says something
else. `ops/check_version_line.py` is the check; these tests are the check's
own tests, run against throwaway trees rather than the repository.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER = REPO_ROOT / "ops" / "check_version_line.py"

# (relative path, content template) — {v} is the version.
CARRIERS: tuple[tuple[str, str], ...] = (
    ("pyproject.toml", '[project]\nname = "jobs-scraper"\nversion = "{v}"\n'),
    ("uv.lock", '[[package]]\nname = "jobs-scraper"\nversion = "{v}"\n'),
    ("sg_product_jobs.py", '__version__ = "{v}"\n'),
    ("server.py", 'mcp = MCPServer(\n    name="jobs-scraper",\n    version="{v}",\n)\n'),
    ("server_v1_1.py", 'mcp = MCPServer(\n    name="jobs-scraper",\n    version="{v}",\n)\n'),
    (".codex-plugin/plugin.json", '{\n  "name": "jobs-scraper",\n  "version": "{v}"\n}\n'),
    ("skills/jobs-scraper/SKILL.md", '---\nname: jobs-scraper\nmetadata:\n  version: "{v}"\n---\n'),
)


def _tree(root: Path, version: str) -> Path:
    for rel, template in CARRIERS:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(template.replace("{v}", version), encoding="utf-8")
    return root


def _run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECKER), str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_repository_version_line_agrees() -> None:
    result = subprocess.run(
        [sys.executable, str(CHECKER)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "VERSION_LINE_PASS" in result.stdout


def test_a_consistent_tree_passes(tmp_path: Path) -> None:
    root = _tree(tmp_path / "consistent", "9.9.9")
    result = _run(root)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "VERSION_LINE_PASS" in result.stdout
    assert "9.9.9" in result.stdout


def test_one_carrier_drifting_fails(tmp_path: Path) -> None:
    root = _tree(tmp_path / "drifted", "9.9.9")
    (root / "server_v1_1.py").write_text('version="1.0.0",\n', encoding="utf-8")
    result = _run(root)
    assert result.returncode == 1
    assert "VERSION_LINE_FAIL" in result.stdout
    assert "1.0.0" in result.stdout
    assert "9.9.9" in result.stdout


def test_a_missing_carrier_fails(tmp_path: Path) -> None:
    root = _tree(tmp_path / "missing", "9.9.9")
    (root / "pyproject.toml").unlink()
    result = _run(root)
    assert result.returncode == 1
    assert "pyproject.toml" in result.stdout


def test_the_optional_plugin_manifest_is_not_required(tmp_path: Path) -> None:
    """The Mavis manifest lives in the plugin runtime, not in the repository."""
    root = _tree(tmp_path / "no-manifest", "9.9.9")
    assert not (root / ".minimax-plugin" / "plugin.json").exists()
    result = _run(root)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_optional_plugin_manifest_is_checked_when_present(tmp_path: Path) -> None:
    root = _tree(tmp_path / "with-manifest", "9.9.9")
    manifest = root / ".minimax-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{\n  "version": "1.0.0"\n}\n', encoding="utf-8")
    result = _run(root)
    assert result.returncode == 1
    assert "1.0.0" in result.stdout
