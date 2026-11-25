"""The plugin manifest has to report the version of the code it ships.

The manifest is a Mavis-specific file: the plugin sync preserves it, so a
sync never updates it and it drifts on its own. It is still the plugin's
identity, and a plugin that reports one version while the code it ships is
another is exactly the drift the version-line check exists to catch. v1.8.5
is how that showed up: the plugin's manifest was two versions behind, and the
release's own verification caught it in the plugin runtime.

The release updates it as part of the release, and this is the tool that does
the updating.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
UPDATER = REPO_ROOT / "ops" / "update_plugin_manifest_version.py"


def _engine_version() -> str:
    import tomllib

    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def _manifest(tmp_path: Path, version: str) -> Path:
    path = tmp_path / "plugin.json"
    path.write_text(
        json.dumps({"name": "jobs-scraper", "version": version, "description": "x"}, indent=2),
        encoding="utf-8",
    )
    return path


def _run(path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(UPDATER), *args, str(path)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_manifest_is_updated_to_the_engine_version(tmp_path: Path) -> None:
    path = _manifest(tmp_path, "0.0.1")

    result = _run(path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == _engine_version()
    assert "PLUGIN_MANIFEST_UPDATED" in result.stdout


def test_check_reports_drift(tmp_path: Path) -> None:
    path = _manifest(tmp_path, "0.0.1")

    result = _run(path, "--check")

    assert result.returncode == 1
    assert "PLUGIN_MANIFEST_DRIFT" in result.stdout
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == "0.0.1", "check must not write"


def test_check_passes_when_the_version_agrees(tmp_path: Path) -> None:
    path = _manifest(tmp_path, _engine_version())

    result = _run(path, "--check")

    assert result.returncode == 0
    assert "PLUGIN_MANIFEST_OK" in result.stdout


def test_updating_twice_is_stable(tmp_path: Path) -> None:
    path = _manifest(tmp_path, "0.0.1")
    _run(path)
    before = path.read_text(encoding="utf-8")

    result = _run(path)

    assert result.returncode == 0
    assert "PLUGIN_MANIFEST_OK" in result.stdout
    assert path.read_text(encoding="utf-8") == before


def test_a_missing_manifest_is_not_an_error(tmp_path: Path) -> None:
    result = _run(tmp_path / "nope.json")

    assert result.returncode == 0
    assert "PLUGIN_MANIFEST_MISSING" in result.stdout
