"""Validate the release ZIP and load its backend from outside the repository."""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile
from package import ROOT, ARCHIVE



def verify():
    with ZipFile(ARCHIVE) as archive, TemporaryDirectory() as directory:
        names = archive.namelist()
        assert not any(n.endswith("/operation_store.py") or n.endswith("remount-state.json") or n.endswith("remount-audit.json") for n in names)
        assert not any(n.endswith("/" + f + ".py") for n in names for f in ("events", "rules", "report", "export", "suspend", "hardware"))
        assert names and all(n.startswith("external-storage-guard/") and ".." not in Path(n).parts for n in names)
        assert sum(n.endswith("/plugin.json") for n in names) == 1
        assert not any(part in {"tests", "node_modules", "__pycache__"} for n in names for part in Path(n).parts)
        archive.extractall(directory)
        plugin = Path(directory) / "external-storage-guard"
        manifest = json.loads((plugin / "plugin.json").read_text())
        assert manifest["api_version"] == 1 and manifest["flags"] == ["root"]
        assert json.loads((plugin / "package.json").read_text())["type"] == "module"
        for file in ("main.py", "dist/index.js", "dist/index.js.map", "LICENSE", "README.md", "storage_guard/service.py"):
            assert (plugin / file).is_file(), file
        subprocess.run([sys.executable, str(ROOT / "tests/backend-runtime-smoke.py"), str(plugin)], cwd=directory, check=True, timeout=15)
        subprocess.run(["node", str(ROOT / "tests/bundle-smoke.mjs"), str(plugin / "dist/index.js")], cwd=directory, check=True, timeout=10)
        subprocess.run(["node", str(ROOT / "tests/ui-smoke.mjs"), str(plugin / "dist/index.js")], cwd=directory, check=True, timeout=20)
    print(f"ZIP structure and isolated imports: OK ({ARCHIVE.stat().st_size} bytes)")


if __name__ == "__main__":
    verify()
