"""Fail before publishing if the tag, package and lockfile disagree."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent


def validate_release(tag: str, package: dict, lock: dict) -> None:
    version = package.get("version")
    if not version or tag != f"v{version}":
        raise ValueError(f"Release tag {tag!r} must equal v{version} from package.json")
    if lock.get("version") != version or lock.get("packages", {}).get("", {}).get("version") != version:
        raise ValueError("package-lock.json version differs from package.json; run npm version before tagging")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 scripts/check_release.py vX.Y.Z")
    try:
        validate_release(sys.argv[1], json.loads((ROOT / "package.json").read_text()),
                         json.loads((ROOT / "package-lock.json").read_text()))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Release version validated: {sys.argv[1]}")
