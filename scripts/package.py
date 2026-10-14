#!/usr/bin/env python3
"""Package dist/ into wox.plugin.qrcode.wox with correct Unix permission bits.

PowerShell's Compress-Archive records no permission bits (external_attr = 0) and
no DOS directory attribute on the entries it writes. Wox extracts .wox with
fastzip, which derives a directory's mode from those fields; with
klauspost/compress/zip an entry that has neither the Unix bits nor the DOS
directory bit resolves to 0666, so the extracted directory loses its execute bit
and the next mkdir inside it fails with "permission denied".

Writing the archive ourselves lets every build host record directories as 0755
and files as 0644, which fastzip then applies verbatim.
"""

from __future__ import annotations

import argparse
import shutil
import stat
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT / "dist"
ARCHIVE_NAME = "wox.plugin.qrcode.wox"

DIR_MODE = 0o755
FILE_MODE = 0o644

# Zip "version made by" system byte for Unix. Go's zip reader keys off this byte
# to decide whether external_attr holds a Unix mode.
UNIX_CREATE_SYSTEM = 3

# MS-DOS directory attribute, kept for tools that only look at the low bits.
MSDOS_DIR_ATTR = 0x10


def _make_info(rel_path: str, is_dir: bool, mtime: float) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(rel_path)
    info.create_system = UNIX_CREATE_SYSTEM
    info.compress_type = zipfile.ZIP_DEFLATED
    mode = (stat.S_IFDIR | DIR_MODE) if is_dir else (stat.S_IFREG | FILE_MODE)
    info.external_attr = mode << 16
    if is_dir:
        info.external_attr |= MSDOS_DIR_ATTR
    local = time.localtime(mtime)
    if local.tm_year >= 1980:
        info.date_time = local[:6]
    return info


def build_archive(dist_dir: Path, output: Path) -> None:
    if not (dist_dir / "plugin.json").is_file():
        raise SystemExit(f"{dist_dir} has no plugin.json; run 'make build' first")

    entries = sorted(dist_dir.rglob("*"), key=lambda entry: entry.as_posix().lower())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for entry in entries:
            is_dir = entry.is_dir()
            rel_path = entry.relative_to(dist_dir).as_posix() + ("/" if is_dir else "")
            info = _make_info(rel_path, is_dir, entry.stat().st_mtime)
            if is_dir:
                archive.writestr(info, b"")
            else:
                # archive.write() rebuilds the ZipInfo from the OS, which would
                # drop the permission bits set above, so stream it ourselves.
                with archive.open(info, "w") as dst, entry.open("rb") as src:
                    shutil.copyfileobj(src, dst)

    print(f"Packaged {output} ({output.stat().st_size} bytes)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Package dist/ into the .wox archive.")
    parser.add_argument("--dist-dir", type=Path, default=DIST_DIR, help="directory holding plugin.json")
    parser.add_argument("--output", type=Path, default=ROOT / ARCHIVE_NAME, help="archive to write")
    args = parser.parse_args()

    build_archive(args.dist_dir, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
