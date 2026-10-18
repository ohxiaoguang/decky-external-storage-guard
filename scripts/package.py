"""Create a Decky installable ZIP without dev dependencies or test fixtures."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIRECTORY = "external-storage-guard"
ARCHIVE = ROOT / "out" / "External-Storage-Guard.zip"


def package():
    files = [ROOT / f for f in ("package.json", "plugin.json", "main.py", "README.md", "LICENSE", "dist/index.js", "dist/index.js.map")]
    files += sorted((ROOT / "storage_guard").glob("*.py"))
    for file in files:
        if not file.is_file():
            raise SystemExit(f"Missing required file: {file}; run npm run build first")
    output = ARCHIVE
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for file in files:
            archive.write(file, str(Path(PLUGIN_DIRECTORY) / file.relative_to(ROOT)))
    print(output)
    return output


if __name__ == "__main__":
    package()
