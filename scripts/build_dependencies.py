#!/usr/bin/env python3
"""Build dist/dependencies for a Wox Python plugin.

The Wox Python host only adds ``<plugin>/dependencies`` to ``sys.path``, and a
single ``.wox`` archive must serve every supported OS. Compiled wheels cannot
all live in that one directory: zxing-cpp's abi3 build is named
``zxingcpp.abi3.so`` on both macOS and Linux (and ``zxingcpp.pyd`` on every
Windows arch), so those binaries would overwrite each other.

Pure-Python dependencies are therefore installed into ``dist/dependencies`` and
the compiled packages into ``dist/dependencies/native/<platform>``, which the
plugin adds to ``sys.path`` at runtime (see ``_add_platform_native_path`` in
``src/qrcode_main.py``). Keep the platform keys below in sync with that
function.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT / "dist"
DEPS_DIR = DIST_DIR / "dependencies"
NATIVE_DIR = DEPS_DIR / "native"
BUILD_DIR = ROOT / "build"

# (directory name, uv --python-platform value)
PLATFORMS: list[tuple[str, str]] = [
    ("win_amd64", "x86_64-pc-windows-msvc"),
    ("macos_x86_64", "x86_64-apple-darwin"),
    ("macos_arm64", "aarch64-apple-darwin"),
    ("linux_x86_64", "x86_64-unknown-linux-gnu"),
]

# 3.10 and 3.11 need their own wheels; 3.12 and newer share the abi3 build.
PYTHON_VERSIONS = ["3.10", "3.11", "3.12"]

# Packages that ship compiled extensions and must be selected per platform.
NATIVE_PACKAGES = ["zxingcpp"]

# Pure-Python dependencies are platform independent, but colorama is only
# declared for Windows, so resolve them against Windows to keep it bundled.
COMMON_PLATFORM = "x86_64-pc-windows-msvc"


def run(cmd: list[str]) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def export_requirements(dest: Path) -> Path:
    """Write the locked runtime dependencies to a requirements file."""
    requirements = dest / "requirements.txt"
    run(
        [
            "uv",
            "export",
            "--no-dev",
            "--no-emit-project",
            "--format",
            "requirements.txt",
            "--no-hashes",
            "-o",
            str(requirements),
        ]
    )
    return requirements


def install(requirements: Path, target: Path, python_version: str, python_platform: str) -> None:
    """Install the locked dependencies into target for one python/platform pair."""
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    run(
        [
            "uv",
            "pip",
            "install",
            "-r",
            str(requirements),
            "--target",
            str(target),
            "--python-version",
            python_version,
            "--python-platform",
            python_platform,
            "--only-binary=:all:",
            "--quiet",
        ]
    )


def clean(path: Path) -> None:
    """Drop metadata and development leftovers from an installed tree."""
    for pattern in ("*.dist-info", "*.egg-info", "__pycache__"):
        for entry in list(path.rglob(pattern)):
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
    for pattern in ("__editable__*", ".lock"):
        for entry in list(path.rglob(pattern)):
            entry.unlink(missing_ok=True)
    for name in ("bin", "ruff"):
        shutil.rmtree(path / name, ignore_errors=True)
    for entry in list(path.rglob("*mypy*")):
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)


def merge(src: Path, dest: Path) -> None:
    shutil.copytree(src, dest, dirs_exist_ok=True)


def build_common(requirements: Path) -> None:
    """Install the platform-independent packages into dist/dependencies."""
    tmp = BUILD_DIR / "common"
    install(requirements, tmp, PYTHON_VERSIONS[-1], COMMON_PLATFORM)
    for package in NATIVE_PACKAGES:
        shutil.rmtree(tmp / package, ignore_errors=True)
    clean(tmp)
    merge(tmp, DEPS_DIR)
    shutil.rmtree(tmp, ignore_errors=True)


def build_native(requirements: Path) -> None:
    """Install the compiled packages into dist/dependencies/native/<platform>."""
    for name, platform in PLATFORMS:
        out = NATIVE_DIR / name
        shutil.rmtree(out, ignore_errors=True)
        for version in PYTHON_VERSIONS:
            tmp = BUILD_DIR / "native" / name / version
            install(requirements, tmp, version, platform)
            for package in NATIVE_PACKAGES:
                package_dir = tmp / package
                if package_dir.is_dir():
                    merge(package_dir, out / package)
            shutil.rmtree(tmp, ignore_errors=True)
        clean(out)
        files = sorted(entry.name for entry in out.rglob("*") if entry.is_file())
        print(f"  {name}: {', '.join(files)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build dist/dependencies with per-platform native binaries.")
    parser.add_argument("--keep-build", action="store_true", help="keep the intermediate build/ directory")
    args = parser.parse_args()

    if shutil.which("uv") is None:
        print("uv is required but was not found on PATH.", file=sys.stderr)
        return 1

    shutil.rmtree(DEPS_DIR, ignore_errors=True)
    shutil.rmtree(BUILD_DIR, ignore_errors=True)
    DEPS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        with tempfile.TemporaryDirectory() as tmp:
            requirements = export_requirements(Path(tmp))
            print("Installing pure-Python dependencies into dist/dependencies")
            build_common(requirements)
            print("Installing native dependencies per platform")
            build_native(requirements)
    finally:
        if not args.keep_build:
            shutil.rmtree(BUILD_DIR, ignore_errors=True)

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
