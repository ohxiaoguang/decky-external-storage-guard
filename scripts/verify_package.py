"""Validate the release ZIP and load its backend from outside the repository."""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile
from package import ROOT, ARCHIVE

BACKEND_CHECK = """
import asyncio, importlib.util, pathlib, sys
path = pathlib.Path(sys.argv[1]) / 'main.py'
spec = importlib.util.spec_from_file_location('_', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
async def verify():
    plugin = module.Plugin()
    assert callable(plugin.get_snapshot)
    assert callable(plugin.remount_partition)
    assert callable(plugin.get_report) and callable(plugin.export_report)
    await plugin._main()
    await plugin._unload()
    await plugin._uninstall()
asyncio.run(verify())
print('Packaged backend import and lifecycle: OK')
"""


def verify():
    with ZipFile(ARCHIVE) as archive, TemporaryDirectory() as directory:
        names = archive.namelist()
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
        subprocess.run([sys.executable, "-I", "-c", BACKEND_CHECK, str(plugin)], cwd=directory, check=True, timeout=10)
        subprocess.run(["node", str(ROOT / "tests/bundle-smoke.mjs"), str(plugin / "dist/index.js")], cwd=directory, check=True, timeout=10)
        subprocess.run(["node", str(ROOT / "tests/remount-ui-smoke.mjs"), str(plugin / "dist/index.js")], cwd=directory, check=True, timeout=10)
        subprocess.run(["node", str(ROOT / "tests/report-ui-smoke.mjs"), str(plugin / "dist/index.js")], cwd=directory, check=True, timeout=15)
    print(f"ZIP structure and isolated imports: OK ({ARCHIVE.stat().st_size} bytes)")


if __name__ == "__main__":
    verify()
