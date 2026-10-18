"""Create a Decky installable ZIP without dev dependencies or test fixtures."""
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent.parent


def package():
    version = json.loads((ROOT / "package.json").read_text())["version"]
    name = "external-storage-guard"
    files = [ROOT / f for f in ("package.json", "plugin.json", "main.py", "README.md", "LICENSE", "dist/index.js", "dist/index.js.map")]
    files += sorted((ROOT / "storage_guard").glob("*.py"))
    for file in files:
        if not file.is_file():
            raise SystemExit(f"Missing required file: {file}; run npm run build first")
    output = ROOT / "out" / f"{name}-v{version}.zip"
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for file in files:
            archive.write(file, str(Path(name) / file.relative_to(ROOT)))
    print(output)
    return output


if __name__ == "__main__":
    package()
