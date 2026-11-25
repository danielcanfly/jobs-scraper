#!/usr/bin/env python3
"""Set the Mavis plugin manifest's version to the engine's version.

The manifest is a Mavis-specific file: the plugin sync preserves it, so a sync
never updates it and it drifts on its own. It is still the plugin's identity
though, and a plugin that reports one version while the code it ships is
another is exactly the drift the version-line check exists to catch.

    python ops/update_plugin_manifest_version.py           # update it
    python ops/update_plugin_manifest_version.py --check   # only report

The path can be given as an argument; the default is the plugin runtime's
manifest.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = Path.home() / ".minimax" / "plugins" / "jobs-scraper" / ".minimax-plugin" / "plugin.json"


def engine_version() -> str:
    import tomllib

    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def main() -> int:
    check_only = "--check" in sys.argv[1:]
    paths = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    manifest = Path(paths[0]).expanduser() if paths else DEFAULT_MANIFEST

    version = engine_version()
    if not manifest.is_file():
        print(f"PLUGIN_MANIFEST_MISSING ({manifest})")
        return 0

    data = json.loads(manifest.read_text(encoding="utf-8"))
    current = data.get("version")
    if current == version:
        print(f"PLUGIN_MANIFEST_OK ({manifest} → {version})")
        return 0
    if check_only:
        print(f"PLUGIN_MANIFEST_DRIFT ({manifest}: {current} → {version})")
        return 1

    data["version"] = version
    manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PLUGIN_MANIFEST_UPDATED ({manifest} → {version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
