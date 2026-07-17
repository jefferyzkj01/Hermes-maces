from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = (
    "LICENSE",
    "docs/SECURITY.md",
    "docs/INSTALLATION.md",
    "docs/ROLL_OUT.md",
    "docs/PUBLIC_RELEASE_GUIDE.md",
    "docs/PUBLIC_BETA_VALIDATION.md",
    "docs/releases/v1.2.0.md",
)

FORBIDDEN_FILE_NAMES = {
    ".coverage",
    ".DS_Store",
    "subconscious.db",
    "subconscious.db-wal",
    "subconscious.db-shm",
}
FORBIDDEN_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "build",
    "data",
    "dist",
    "htmlcov",
}

SCAN_EXCLUSIONS = {
    ".github/workflows/test.yml",
    "docs/PUBLIC_RELEASE_GUIDE.md",
    "scripts/check_public_boundary.py",
}

PRIVATE_PATH = re.compile(r"/Users/[^/\s]+/|[A-Za-z]:\\Users\\")
PRIVATE_KEY = re.compile(r"BEGIN\s+[^\n]*PRIVATE KEY")


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def is_runtime_artifact(relative: str) -> bool:
    path = Path(relative)
    parts = set(path.parts)
    return (
        path.name in FORBIDDEN_FILE_NAMES
        or path.suffix in {".pyc", ".pyo"}
        or any(part in FORBIDDEN_DIR_NAMES or part.endswith(".egg-info") for part in parts)
    )


def main() -> None:
    errors: list[str] = []

    for relative in REQUIRED:
        if not (ROOT / relative).is_file():
            errors.append(f"missing required release file: {relative}")

    if (ROOT / "config.yaml").exists():
        errors.append("repository-owned config.yaml is forbidden")
    if (ROOT / "data").exists():
        errors.append("repository data/ directory is forbidden")

    for relative in tracked_files():
        normalized = relative.replace("\\", "/")
        if is_runtime_artifact(normalized):
            errors.append(f"tracked local/runtime artifact: {relative}")

        path = ROOT / relative
        if not path.is_file():
            continue
        if normalized.startswith("tests/") or normalized in SCAN_EXCLUSIONS:
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        if PRIVATE_PATH.search(text):
            errors.append(f"possible private absolute user path in {relative}")
        if PRIVATE_KEY.search(text):
            errors.append(f"possible private-key material in {relative}")

    if errors:
        raise SystemExit("Public boundary contract failed:\n- " + "\n- ".join(errors))

    print("Public boundary contract passed")


if __name__ == "__main__":
    main()
