#!/usr/bin/env python3
"""Create a release package for the TrakBridge plugin."""
import os
import shutil
import tarfile
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

def main() -> None:
    manifest_path = ROOT / "plugin.yaml"
    if not manifest_path.is_file():
        print("ERROR: plugin.yaml not found")
        raise SystemExit(1)
    with open(manifest_path) as f:
        manifest = yaml.safe_load(f)
    plugin_id = manifest["id"]
    version = manifest["version"]
    package_name = f"{plugin_id}-v{version}.tar.gz"
    dist_dir = ROOT / "dist"
    dist_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp) / plugin_id
        tmp_dir.mkdir(parents=True)
        shutil.copy2(manifest_path, tmp_dir / "plugin.yaml")
        entry = manifest["entry_point"]
        entry_path = ROOT / entry
        if not entry_path.is_file():
            print(f"ERROR: entry point '{entry}' not found")
            raise SystemExit(1)
        (tmp_dir / entry).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry_path, tmp_dir / entry)
        for pattern in manifest.get("extra_files", []):
            for f in ROOT.glob(pattern):
                rel = f.relative_to(ROOT)
                (tmp_dir / rel.parent).mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, tmp_dir / rel)
        archive_path = dist_dir / package_name
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(tmp_dir, arcname=plugin_id)
    print(f"Created {archive_path}")

if __name__ == "__main__":
    main()
